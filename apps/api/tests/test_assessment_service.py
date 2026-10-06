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


def _problem(key):
    from app.assessment.loader import spec_for

    for spec_key in ("aptitude", "coding_check", "spatial"):
        found = next((i for i in spec_for(spec_key).items if i.key == key), None)
        if found:
            return found
    raise AssertionError(key)


def right(item, wrong=()):
    """The right answer to a problem, except for the keys in `wrong`."""
    found = _problem(item["key"])
    if item["key"] in wrong:
        return {"option": next(o.key for o in found.options if o.key != found.answer)}
    return {"option": found.answer}


def scripted(plan: dict[str, list], otherwise=True):
    """Answers an adaptive test's questions in order, per dimension: True right, False wrong, None skip —
    {"aptitude:logical": [False, False, True]}; after the list (or for other dimensions), `otherwise`."""
    count: dict[str, int] = {}

    def choose(item):
        found = _problem(item["key"])
        n = count[found.dimension] = count.get(found.dimension, 0) + 1
        steps = plan.get(found.dimension, [])
        ok = steps[n - 1] if n <= len(steps) else otherwise
        if ok is None:
            return None
        return {"option": found.answer if ok else next(o.key for o in found.options if o.key != found.answer)}

    return choose


def levels(seen, dimension):
    return [p.difficulty for p in map(_problem, seen) if p.dimension == dimension]


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
    first = view["item"]["options"]
    assert say.startswith("पंद्रह सवाल") and f"ए: {first[0]['label']['hi']}." in say and f"बी: {first[1]['label']['hi']}." in say


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


def test_the_thinking_skills_test_climbs_and_falls_with_the_answers(db_session):
    """Class 10 starts at level 3: a right answer makes the next question harder, a wrong or skipped one easier."""
    asha = student(db_session)
    view, seen = take(db_session, asha, "aptitude", choose=scripted({
        "aptitude:numerical": [True] * 5, "aptitude:logical": [False] * 5,
        "aptitude:verbal": [True, None, True, False, True]}))
    assert len(seen) == 15
    assert [_problem(k).dimension for k in seen[:3]] == ["aptitude:numerical", "aptitude:logical", "aptitude:verbal"], "they take turns"
    assert levels(seen, "aptitude:numerical") == [3, 4, 5, 5, 5]
    assert levels(seen, "aptitude:logical") == [3, 2, 1, 1, 1]
    assert levels(seen, "aptitude:verbal") == [3, 4, 3, 4, 3]
    scores = {s["dimension"]: s for s in view["result"]["scores"]}
    assert scores["aptitude:numerical"]["score"] == 0.88 and scores["aptitude:numerical"]["says"]["en"] == "level 5 of 5 · 5 of 5 right"
    assert scores["aptitude:logical"]["score"] == 0.12 and scores["aptitude:logical"]["says"]["en"] == "below level 1 · 0 of 5 right"
    assert scores["aptitude:verbal"]["says"]["hi"] == "स्तर 5 में से 3 · 5 में से 3 सही" and scores["aptitude:verbal"]["detail"]["skipped"] == 1
    review = view["result"]["review"]
    assert len(review) == 15 and all(r["explanation"] and r["answer"] for r in review)


def test_younger_students_start_easier(db_session):
    for class_level, stage, first in ((6, None, 1), (8, None, 2), (12, None, 3), (12, "ug_y2", 3)):
        kid = student(db_session, f"s{class_level}{stage}", class_level=class_level)
        kid.education_stage = stage
        db_session.commit()
        view = service.start(db_session, kid, "aptitude")
        assert _problem(view["item"]["key"]).difficulty == first, (class_level, stage)


def test_a_retake_gets_new_questions(db_session):
    asha = student(db_session)
    taken = [set(take(db_session, asha, "aptitude", choose=right)[1]) for _ in range(3)]
    assert not (taken[0] & taken[1]) and not (taken[2] & (taken[0] | taken[1])), "no question twice"


def test_going_back_shows_the_same_question_with_its_answer(db_session):
    asha = student(db_session)
    view = service.start(db_session, asha, "aptitude")
    first = view["item"]["key"]
    view = service.answer(db_session, asha, view["attempt_id"], first, right(view["item"]))
    second = view["item"]["key"]
    back = service.back(db_session, asha, view["attempt_id"])
    assert back["item"]["key"] == first and back["item"]["answer"] == right({"key": first})
    again = service.answer(db_session, asha, view["attempt_id"], first, right(back["item"]))
    assert again["item"]["key"] == second


def test_questions_that_cant_matter_to_the_students_goal_are_skipped(db_session):
    """A JEE student heading for computer science isn't asked about biology and hospitals; a NEET student isn't
    asked about building robots; a student still exploring is asked everything."""
    love = lambda item: {"option": "love"} if any(o["key"] == "love" for o in item["options"]) else {"option": item["options"][0]["key"]}
    jee = student(db_session, "jee", class_level=11)
    jee.target_exam_code = "JEE_MAIN"
    neet = student(db_session, "neet", class_level=11)
    neet.target_exam_code = "NEET_UG"
    exploring = student(db_session, "exploring", class_level=9)
    db_session.commit()
    asked = {name: set(take(db_session, who, "interests", choose=love)[1]) for name, who in (("jee", jee), ("neet", neet), ("exploring", exploring))}
    assert not {"int_biology", "biology_side", "hospital"} & asked["jee"] and "build_things" in asked["jee"]
    assert not {"build_things", "physics_side", "maths_style"} & asked["neet"] and "hospital" in asked["neet"]
    assert {"int_biology", "hospital", "build_things"} <= asked["exploring"]
    assert db_session.query(AssessmentAttempt).filter_by(student_profile_id=jee.id).one().track == "engineering"


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
    assert listed["aptitude"]["est_minutes"] == 12


def test_history_only_calls_a_change_a_change_beyond_the_noise(db_session):
    asha = student(db_session)
    take(db_session, asha, "aptitude", choose=scripted({"aptitude:numerical": [False, False, False, True, True],
                                                        "aptitude:logical": [True, True, True, True, False]}))
    take(db_session, asha, "aptitude", choose=scripted({"aptitude:logical": [True, True, True, False, True]}))
    history = service.history(db_session, asha, "aptitude")
    assert len(history["attempts"]) == 2
    change = {row["dimension"]: row for row in history["since_previous"]}
    assert change["aptitude:numerical"]["change"] == 1, "0.24 → 0.88: well beyond the noise"
    assert change["aptitude:numerical"]["before"]["en"] == "level 2 of 5 · 2 of 5 right"
    assert change["aptitude:logical"]["change"] == 0, "0.84 → 0.84"


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
