"""MAYA's conversational career assessment: which questions get asked, how answers turn
into a ranking, and that the ranking clearly separates good fits from poor ones."""

import pytest

from app.models.career import CareerOption
from app.seed.careers import load_library, seed_careers
from app.services import assessment_engine as eng

FUTURE_DOCTOR = dict(
    int_maths="meh", int_physics="like", physics_side="numericals", build_things="no", int_chemistry="like",
    chemistry_side="medicines", int_biology="love", biology_side="body", biology_role="treat", hospital="fine",
    int_computer="meh", int_commerce="no", int_arts="no", int_language="like", language_side="teaching",
    int_society="like", saturday="friends", group_role="together", compliment="kind", people="people",
    speaking="fine", broken="call", rules="rules", workplace="lab", adventure="sometimes", matters="helping",
    sector="govt", years="long", pressure="fine",
)
CODER = dict(
    int_maths="love", maths_style="logic", int_physics="like", physics_side="numericals", build_things="maybe",
    int_chemistry="meh", int_biology="hard", hospital="avoid", int_computer="love", computer_side="apps",
    int_commerce="like", commerce_side="business", int_arts="no", int_language="no", int_society="no",
    saturday="read", group_role="research", compliment="smart", people="alone", speaking="nervous", broken="why",
    rules="own", workplace="desk", adventure="routine", matters="money", sector="private", years="short", pressure="fine",
)


@pytest.fixture()
def careers(db_session):
    seed_careers(db_session)
    return db_session.query(CareerOption).all()


def ids(questions):
    return {q["id"] for q in questions}


def test_follow_ups_only_for_subjects_the_student_likes():
    liked = eng.questions_asked({"int_physics": "love"})
    disliked = eng.questions_asked({"int_physics": "hard"})
    assert {"physics_side", "build_things"} <= ids(liked)
    assert not {"physics_side", "build_things"} & ids(disliked)


def test_the_conversation_is_long_enough_to_know_the_student():
    all_liked = {q["id"]: q["options"][0]["id"] for q in eng.load_bank()["questions"]}
    assert len(eng.questions_asked({})) >= 20
    assert len(eng.questions_asked(all_liked)) >= 30


def test_levels_are_fair_to_follow_up_questions():
    # Loving maths and then picking a maths-heavy follow-up is a full maths level —
    # not diluted by questions that were never asked.
    levels = eng.dimension_levels({"int_maths": "love", "maths_style": "calculus"})
    assert levels["maths"] == pytest.approx(1.0)
    assert eng.dimension_levels({"int_maths": "hard"})["maths"] == 0.0
    assert eng.dimension_levels({})["maths"] == eng.NEUTRAL, "no answer is neutral, not zero"


def test_a_future_doctor_gets_medicine_on_top(careers):
    ranked = eng.rank_careers(careers, FUTURE_DOCTOR)
    assert ranked[0]["career"].key == "mbbs"
    assert ranked[0]["label"] == "Best match"
    assert "you want to diagnose and treat patients" in ranked[0]["reasons"]


def test_choosing_to_care_rather_than_treat_puts_nursing_first(careers):
    ranked = eng.rank_careers(careers, {**FUTURE_DOCTOR, "biology_role": "care"})
    assert ranked[0]["career"].key == "nursing"


def test_a_coder_gets_computing_and_medicine_is_clearly_a_poor_fit(careers):
    ranked = eng.rank_careers(careers, CODER)
    top_keys = [r["career"].key for r in ranked[:2]]
    assert set(top_keys) == {"cse", "ai_data"}
    mbbs = next(r for r in ranked if r["career"].key == "mbbs")
    assert mbbs["label"] == "Not a natural fit"
    assert any("blood and hospitals" in w for w in mbbs["watch_outs"]), "it says why"


def test_labels_separate_good_from_poor_fits(careers):
    ranked = eng.rank_careers(careers, CODER)
    labels = [r["label"] for r in ranked]
    assert labels[0] == "Best match"
    assert "Not a natural fit" in labels
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] - scores[-1] > 50, "a real spread, not everything at 'moderate'"


def test_a_hard_requirement_costs_real_points(careers):
    must_fail = eng.score_career({"biology": 3, "blood_ok": 3}, ["blood_ok"], {"biology": 1.0, "blood_ok": 0.0})
    no_must = eng.score_career({"biology": 3, "blood_ok": 3}, [], {"biology": 1.0, "blood_ok": 0.0})
    assert must_fail["score"] == pytest.approx(no_must["score"] * eng.MUST_PENALTY)


def test_library_and_questions_agree_on_dimensions():
    dims = set(eng.load_bank()["dimensions"])
    for career in load_library():
        assert set(career["profile"]) <= dims, career["key"]
    for q in eng.load_bank()["questions"]:
        for o in q["options"]:
            assert set(o["weights"]) <= dims, (q["id"], o["id"])


def test_every_career_has_a_full_guide():
    for career in load_library():
        d = career["details"]
        assert d["how_to_prepare"] and d["start_now"] and d["resources"] and d["roles"], career["key"]
        assert d["earnings"]["entry"], career["key"]
        for r in d["resources"]:
            assert r["url"].startswith("https://"), (career["key"], r["url"])


def test_the_api_ranks_every_career(client, db_session, careers):
    client.post("/api/auth/register", json={
        "email": "assess@example.com", "password": "pw-for-tests-123", "name": "Riya", "class_level": 11,
    })
    token = client.post("/api/auth/login", json={
        "email": "assess@example.com", "password": "pw-for-tests-123",
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    bank = client.get("/api/careers/assessment/questions").json()
    assert len(bank["questions"]) >= 30

    result = client.post("/api/careers/assessment", headers=headers, json={
        "assessment_type": "class11_12_career", "responses": {"answers": CODER},
    }).json()
    assert len(result["results"]) == len(careers)
    assert result["results"][0]["rank"] == 1 and result["results"][0]["fit_label"] == "Best match"
    assert result["results"][0]["reasons"]
    assert result["highlights"]

    detail = client.get(f"/api/careers/key/{result['results'][0]['career_key']}").json()
    assert detail["details"]["earnings"]["entry"]


def test_a_skipped_question_is_neutral_not_a_zero():
    answered = eng.dimension_levels({"int_maths": "love"})
    assert answered["physics"] == eng.NEUTRAL, "physics was never answered"
