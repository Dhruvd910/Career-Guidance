"""Career directions: bands with reasons from the student's own results — never one answer."""

import json

from app.assessment import alignment
from app.models.assessment import CareerAlignmentSnapshot
from app.seed.careers import seed_careers
from tests.test_assessment_service import right, student, take

TECH = {"int_maths": "love", "maths_style": "logic", "int_physics": "like", "physics_side": "numericals",
        "build_things": "maybe", "int_chemistry": "meh", "int_biology": "hard", "hospital": "avoid",
        "int_computer": "love", "computer_side": "ai", "int_commerce": "no", "int_arts": "no", "int_language": "no",
        "int_society": "no", "saturday": "read", "group_role": "research", "compliment": "smart", "people": "alone",
        "speaking": "nervous", "broken": "why", "rules": "own", "workplace": "desk", "adventure": "routine",
        "matters": "money", "sector": "private", "years": "long", "pressure": "fine"}
HEALER = {**TECH, "int_maths": "meh", "int_computer": "meh", "int_biology": "love", "biology_side": "body",
          "biology_role": "treat", "int_chemistry": "like", "chemistry_side": "medicines", "hospital": "avoid",
          "saturday": "friends", "group_role": "together", "compliment": "kind", "people": "people",
          "matters": "helping", "workplace": "lab"}


def answers(choices):
    return lambda item: {"option": choices.get(item["key"], item["options"][0]["key"])}


def career(directions, key):
    return next(c for d in directions["domains"] for c in d["careers"] if c["career_key"] == key)


def test_no_directions_before_the_interests_check(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "skills")
    out = alignment.directions(db_session, asha)
    assert out["ready"] is False and out["missing"] == ["interests"] and out["domains"] == []


def test_several_directions_in_bands_and_never_one_answer(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    out = alignment.directions(db_session, asha)
    assert {"cse", "ai_data"} <= set(out["summary"]["strong"])
    assert "mbbs" in out["summary"]["weak"], "shown last, but still shown"
    assert sum(len(d["careers"]) for d in out["domains"]) == 27
    assert out["domains"][0]["domain"] == "Engineering & Technology"
    text = json.dumps(out).lower()
    for banned in ("best match", "closest match", '"rank"', "fit_score", "your career is"):
        assert banned not in text, banned


def test_why_it_fits_comes_from_their_own_answers(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    cse = career(alignment.directions(db_session, asha), "cse")
    assert cse["band"] == "strong" and cse["band_label"]["en"] == "Strong alignment"
    whys = [w["en"] for w in cse["why"]]
    assert "You enjoy maths" in whys and "You enjoy computers and coding" in whys
    assert all(w["hi"] for w in cse["why"])
    assert cse["components"]["interest"] > 0.65 and cse["components"]["aptitude:logical"] is None
    unmeasured = [q["en"] for q in cse["questions"]]
    assert "Logical reasoning isn't measured yet — the 'Thinking skills' check would show it." in unmeasured
    assert cse["questions"][-2:] == alignment.career_needs()["careers"]["cse"]["ask_yourself"]


def test_a_low_must_have_becomes_a_question_not_a_penalty(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(HEALER))
    mbbs = career(alignment.directions(db_session, asha), "mbbs")
    assert mbbs["band"] == "explore"
    assert mbbs["questions"][0]["en"].startswith("This work means seeing blood and injuries every day.")


def test_measured_ability_shows_strengths_and_gaps_with_next_steps(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    wrong_logic = {"a_log_1", "a_log_2", "a_log_3", "a_log_4", "a_log_5"}
    view, _ = take(db_session, asha, "aptitude", choose=lambda i: right(i, wrong=wrong_logic))
    cse = career(alignment.directions(db_session, asha), "cse")
    assert cse["band"] == "potential", "loves it, but the central reasoning need came out low today"
    assert cse["components"]["aptitude:logical"] == 0.0 and cse["components"]["aptitude:numerical"] == 1.0
    assert {"en": "Working with numbers: 5 of 5 right", "hi": "संख्याओं के साथ काम: 5 में से 5 सही"} in cse["strengths"]
    gap = cse["development_areas"][0]
    assert gap["text"]["en"] == "Logical reasoning: 0 of 5 right"
    assert gap["next_step"]["en"].startswith("Solve a few logic puzzles")
    assert {"dimension": "aptitude:logical", "measured_as": "aptitude:logical", "instrument": "aptitude",
            "attempt_id": view["attempt_id"]} in cse["evidence"]


def test_trying_something_you_like_but_havent_done(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    take(db_session, asha, "skills", choose=lambda item: {"option": "l0"})
    cse = career(alignment.directions(db_session, asha), "cse")
    assert any(q["en"].startswith("You enjoy computers and coding, but haven't done much coding yet") for q in cse["questions"])
    assert cse["components"]["skill:programming"] == 0.0


def test_the_coding_check_counts_over_a_self_rating(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    take(db_session, asha, "skills", choose=lambda item: {"option": "l3"})
    take(db_session, asha, "coding_check", choose=lambda i: right(i, wrong={"c6", "c7", "c8"}))
    cse = career(alignment.directions(db_session, asha), "cse")
    assert cse["components"]["skill:programming"] == 0.625
    assert {"en": "Reading code: 5 of 8 right", "hi": "कोड पढ़ना: 8 में से 5 सही"} not in cse["strengths"]


def test_directions_are_kept_and_reused_until_something_changes(db_session):
    seed_careers(db_session)
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    first = alignment.directions(db_session, asha)
    again = alignment.directions(db_session, asha)
    assert first == again and db_session.query(CareerAlignmentSnapshot).count() == 1
    take(db_session, asha, "skills")
    assert db_session.query(CareerAlignmentSnapshot).count() == 2
    assert alignment.directions(db_session, asha)["inputs"].keys() == {"interests", "skills"}


def test_the_same_answers_give_the_same_directions(db_session):
    seed_careers(db_session)
    asha, ravi = student(db_session), student(db_session, "ravi")
    take(db_session, asha, "interests", answers(TECH))
    take(db_session, ravi, "interests", answers(TECH))
    a, r = alignment.compute(db_session, asha), alignment.compute(db_session, ravi)
    strip = lambda d: json.dumps([[c | {"evidence": None} for c in dom["careers"]] for dom in d["domains"]])  # noqa: E731
    assert strip(a) == strip(r)
