"""Taking an assessment: what comes next, back and skip, resuming, finishing, scoring, retakes."""

import pytest

from app.assessment import service
from app.assessment.service import AssessmentError
from app.memory import consent
from app.models.assessment import AssessmentAttempt, AssessmentResponse, AssessmentScore, CareerAlignmentSnapshot
from app.models.memory import StudentEvent
from app.models.student import AcademicRecord, StudentProfile
from app.models.user import User
from app.seed.careers import seed_careers

GUARDIAN = {"name": "Sunita", "relationship": "mother", "contact": "x"}


def student(db, name="asha", class_level=10, stream=None, memory=False):
    user = User(email=f"{name}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    profile = StudentProfile(user_id=user.id, name=name, class_level=class_level, stream=stream)
    db.add(profile)
    db.commit()
    if memory:
        consent.decide(db, profile, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    return profile


def take(db, profile, key, choose=lambda item: {"option": item["options"][0]["key"]}, language="en"):
    """Answers every item with `choose(item)` (None = skip) until the attempt completes."""
    view = service.start(db, profile, key, language=language)
    seen = []
    while not view["complete"]:
        item = view["item"]
        seen.append(item["key"])
        picked = choose(item)
        view = service.answer(db, profile, view["attempt_id"], item["key"], picked, skipped=picked is None)
        assert len(seen) < 100
    return view, seen


def right(item, wrong=()):
    """The right answer to a problem, except for the keys in `wrong`."""
    from app.assessment.loader import spec_for

    for spec_key in ("aptitude", "coding_check"):
        found = next((i for i in spec_for(spec_key).items if i.key == item["key"]), None)
        if found:
            if item["key"] in wrong:
                return {"option": next(o.key for o in found.options if o.key != found.answer)}
            return {"option": found.answer}
    raise AssertionError(item["key"])


# ---------------- what comes next ----------------

def test_the_first_question_comes_with_the_introduction(db_session):
    asha = student(db_session)
    view = service.start(db_session, asha, "interests")
    assert view["item"]["key"] == "int_maths" and view["can_go_back"] is False
    assert view["item"]["say"].startswith("Let's find out what you enjoy.")
    assert view["progress"] == {"answered": 0, "estimate": view["progress"]["estimate"]}


def test_follow_ups_only_for_what_you_like(db_session):
    asha = student(db_session)
    view = service.start(db_session, asha, "interests")
    view = service.answer(db_session, asha, view["attempt_id"], "int_maths", {"option": "hard"})
    assert view["item"]["key"] == "int_physics", "no 'what kind of maths' for someone who struggles with it"
    view = service.answer(db_session, asha, view["attempt_id"], "int_physics", {"option": "love"})
    assert view["item"]["key"] == "physics_side"


def test_going_back_shows_your_answer_and_changing_it_drops_stale_follow_ups(db_session):
    asha = student(db_session)
    attempt_id = service.start(db_session, asha, "interests")["attempt_id"]
    service.answer(db_session, asha, attempt_id, "int_maths", {"option": "love"})
    service.answer(db_session, asha, attempt_id, "maths_style", {"option": "logic"})
    view = service.back(db_session, asha, attempt_id)
    assert view["item"]["key"] == "maths_style" and view["item"]["answer"] == {"option": "logic"}
    view = service.back(db_session, asha, attempt_id)
    assert view["item"]["key"] == "int_maths" and view["can_go_back"] is False
    view = service.answer(db_session, asha, attempt_id, "int_maths", {"option": "hard"})
    assert view["item"]["key"] == "int_physics"
    keys = {r.item.key for r in db_session.query(AssessmentResponse)}
    assert keys == {"int_maths"}, "the maths follow-up no longer applies, so its answer is gone"


def test_skipping_moves_on(db_session):
    asha = student(db_session)
    attempt_id = service.start(db_session, asha, "interests")["attempt_id"]
    view = service.answer(db_session, asha, attempt_id, "int_maths", skipped=True)
    assert view["item"]["key"] == "int_physics" and view["progress"]["answered"] == 1


def test_an_unfinished_attempt_is_picked_up_where_you_stopped(db_session):
    asha = student(db_session)
    first = service.start(db_session, asha, "interests")
    service.answer(db_session, asha, first["attempt_id"], "int_maths", {"option": "hard"})
    again = service.start(db_session, asha, "interests")
    assert again["attempt_id"] == first["attempt_id"] and again["item"]["key"] == "int_physics"
    assert "Let's find out" not in again["item"]["say"]


@pytest.mark.parametrize("item_key, answer, message", [
    ("int_maths", {"option": "adore"}, "isn't one of the answers"),
    ("int_maths", None, "No answer"),
    ("maths_style", {"option": "logic"}, "isn't part of this assessment"),  # its condition isn't met yet
])
def test_wrong_answers_are_refused(db_session, item_key, answer, message):
    asha = student(db_session)
    attempt_id = service.start(db_session, asha, "interests")["attempt_id"]
    with pytest.raises(AssessmentError, match=message):
        service.answer(db_session, asha, attempt_id, item_key, answer)


def test_one_student_cannot_touch_anothers_attempt(db_session):
    asha, ravi = student(db_session), student(db_session, "ravi")
    attempt_id = service.start(db_session, asha, "interests")["attempt_id"]
    with pytest.raises(AssessmentError) as e:
        service.answer(db_session, ravi, attempt_id, "int_maths", {"option": "love"})
    assert e.value.not_found


def test_questions_are_spoken_in_the_attempts_language(db_session):
    asha = student(db_session)
    view = service.start(db_session, asha, "aptitude", language="hi")
    say = view["item"]["say"]
    assert say.startswith("पंद्रह छोटे सवाल") and "ए: ₹50." in say and "बी: ₹60." in say


# ---------------- finishing and scoring ----------------

def test_interests_complete_with_scores_and_directions(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    view, seen = take(db_session, asha, "interests")
    assert view["complete"] and view["status"] == "completed"
    assert "learn_how" in seen and seen[-1] == "pressure"
    scores = {s["dimension"]: s for s in view["result"]["scores"]}
    # The same answers through MAYA's original engine give the same levels: the port is faithful.
    from app.services.assessment_engine import dimension_levels, load_bank

    first = {q["id"]: q["options"][0]["id"] for q in load_bank()["questions"]}
    old = dimension_levels({k: v for k, v in first.items() if k in seen})
    for dim, s in scores.items():
        if not dim.startswith("learning:"):
            assert s["score"] == pytest.approx(old[dim], abs=1e-4), dim
    assert scores["learning:watching"]["says"]["en"] == "100%"
    assert db_session.query(CareerAlignmentSnapshot).count() == 1, "directions are kept when an attempt completes"


def test_aptitude_counts_right_answers_with_skips(db_session):
    asha = student(db_session)
    view, seen = take(db_session, asha, "aptitude",
                      choose=lambda item: None if item["key"] == "a_num_5" else right(item, wrong={"a_log_1"}))
    assert len(seen) == 15 and all(k.startswith("a_") for k in seen), "one form only"
    scores = {s["dimension"]: s for s in view["result"]["scores"]}
    assert scores["aptitude:numerical"]["says"]["en"] == "4 of 5 right, 1 skipped"
    assert scores["aptitude:logical"]["says"]["hi"] == "5 में से 4 सही"
    assert scores["aptitude:verbal"]["score"] == 1.0
    review = {r["key"]: r for r in view["result"]["review"]}
    assert review["a_log_1"]["right"] is False and review["a_log_1"]["answer"] == "c" and review["a_log_1"]["explanation"]


def test_a_retake_gets_the_other_form(db_session):
    asha = student(db_session)
    forms = []
    for _ in range(3):
        view, seen = take(db_session, asha, "aptitude", choose=right)
        forms.append(seen[0][0])
    assert forms == ["a", "b", "a"]


def test_skills_are_levels(db_session):
    asha = student(db_session)
    view, _ = take(db_session, asha, "skills", choose=lambda item: {"option": "l2"})
    scores = {s["dimension"]: s for s in view["result"]["scores"]}
    assert round(scores["skill:programming"]["score"], 3) == 0.667
    assert scores["skill:programming"]["says"]["en"] == "level 3 of 4"


def test_marks_by_class_with_the_stream_already_known(db_session):
    priya = student(db_session, "priya", class_level=11, stream="PCB")
    view = service.start(db_session, priya, "academic")
    assert view["item"]["key"] == "sr_physics", "the stream is on her profile, so it isn't asked again"
    with pytest.raises(AssessmentError, match="0 to 100"):
        service.answer(db_session, priya, view["attempt_id"], "sr_physics", {"value": 101})
    view, seen = take(db_session, priya, "academic", choose=lambda item: {"value": 80})
    assert seen == ["sr_physics", "sr_chemistry", "sr_biology", "sr_english"]
    record = db_session.query(AcademicRecord).one()
    assert record.subject_marks == {"physics": 80.0, "chemistry": 80.0, "biology": 80.0, "english": 80.0}


def test_younger_students_get_class_ten_subjects(db_session):
    asha = student(db_session, class_level=9)
    view, seen = take(db_session, asha, "academic", choose=lambda item: {"value": 72.5})
    assert seen == ["jr_maths", "jr_science", "jr_social_science", "jr_english", "jr_hindi"]
    assert view["result"]["scores"][0]["says"]["en"] == "72.5%"


# ---------------- the list, history, the timeline, deleting ----------------

def test_the_list_shows_what_you_have_done(db_session):
    asha = student(db_session)
    take(db_session, asha, "skills")
    started = service.start(db_session, asha, "interests")
    service.answer(db_session, asha, started["attempt_id"], "int_maths", {"option": "love"})
    listed = {i["key"]: i for i in service.instruments(db_session, asha)}
    assert [i["key"] for i in service.instruments(db_session, asha)][:3] == ["interests", "aptitude", "skills"]
    assert listed["skills"]["times_taken"] == 1 and listed["skills"]["last_completed"]
    assert listed["interests"]["in_progress"] == {"attempt_id": started["attempt_id"], "answered": 1}
    assert listed["aptitude"]["est_minutes"] == 10


def test_history_only_calls_a_change_a_change_beyond_the_noise(db_session):
    asha = student(db_session)
    take(db_session, asha, "aptitude", choose=lambda i: right(i, wrong={"a_num_1", "a_num_2", "a_num_3", "a_log_1"}))
    take(db_session, asha, "aptitude", choose=lambda i: right(i, wrong={"b_num_1", "b_log_1"}))
    history = service.history(db_session, asha, "aptitude")
    assert len(history["attempts"]) == 2
    change = {row["dimension"]: row for row in history["since_previous"]}
    assert change["aptitude:numerical"]["change"] == 1, "2 of 5 → 4 of 5: two more right"
    assert change["aptitude:numerical"]["before"]["en"] == "2 of 5 right"
    assert change["aptitude:logical"]["change"] == 0, "4 of 5 → 4 of 5"


def test_finishing_goes_on_the_timeline_only_with_the_memory_permission(db_session):
    asha, ravi = student(db_session, memory=True), student(db_session, "ravi")
    take(db_session, asha, "skills")
    take(db_session, ravi, "skills")
    events = db_session.query(StudentEvent).all()
    assert [(e.student_profile_id, e.event_type) for e in events] == [(asha.id, "ASSESSMENT_COMPLETED")]


def test_deleting_an_attempt_really_deletes_it(db_session):
    seed_careers(db_session)
    asha = student(db_session, memory=True)
    view, _ = take(db_session, asha, "interests")
    service.delete_attempt(db_session, asha, view["attempt_id"])
    for model in (AssessmentAttempt, AssessmentResponse, AssessmentScore, CareerAlignmentSnapshot, StudentEvent):
        assert db_session.query(model).count() == 0, model.__name__
