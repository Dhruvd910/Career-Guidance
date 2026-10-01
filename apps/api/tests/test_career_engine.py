"""The career engine: Phase 3's directions explained with the graph — education, pathways, skill
gaps only where measured, a learning path, related careers, colleges, and what MAYA remembers."""

import json

import pytest

from app.knowledge import engine
from app.memory import consent
from app.models.memory import StudentInterest
from app.seed.careers import seed_careers
from tests.test_assessment_service import right, student, take
from tests.test_career_directions import TECH, answers
from tests.test_graph_store import official  # noqa: F401 — fixture

GUARDIAN = {"name": "Sunita", "relationship": "mother", "contact": "x"}


@pytest.fixture()
def library(db_session):
    seed_careers(db_session)


def career(out, key):
    return next(c for d in out["domains"] for c in d["careers"] if c["career_key"] == key)


def remember(db, profile, *labels):
    consent.decide(db, profile, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    for label in labels:
        db.add(StudentInterest(student_profile_id=profile.id, label=label))
    db.commit()


def test_before_any_assessment_the_tree_and_what_she_remembers(db_session, library):
    asha = student(db_session)
    remember(db_session, asha, "robotics", "cricket")
    out = engine.options(db_session, asha, embedder=None)
    assert out["ready"] is False and out["tree"][0]["key"] == "domain:technology"
    robotics = next(c for c in out["from_memory"] if c["career_key"] == "robotics")
    assert robotics["band"] is None and robotics["from_memory"][0]["en"] == "You told MAYA you're interested in robotics"
    assert robotics["required_education"]["degree"]["key"] == "degree:btech_robotics"
    assert db_session.query(StudentInterest).filter_by(label="robotics").one().node_key == "career:robotics"
    assert db_session.query(StudentInterest).filter_by(label="cricket").one().node_key is None


def test_without_the_memory_permission_nothing_remembered_is_used(db_session, library):
    asha = student(db_session)
    db_session.add(StudentInterest(student_profile_id=asha.id, label="robotics"))
    db_session.commit()
    assert engine.options(db_session, asha, embedder=None)["from_memory"] == []


def test_every_direction_explained_with_the_graph(db_session, library):
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    out = engine.options(db_session, asha, embedder=None)
    assert out["domains"][0]["domain"] == "domain:technology"
    tech = {c["career_key"] for c in out["domains"][0]["careers"]}
    assert {"cse", "ai_data", "cybersecurity", "robotics"} <= tech
    cse = career(out, "cse")
    assert cse["band"] == "strong" and cse["domain"]["key"] == "domain:technology"
    education = cse["required_education"]
    assert education["degree"]["key"] == "degree:btech_cse"
    assert [s["key"] for s in education["streams"]] == ["stream:pcm", "stream:pcmb"]
    assert [step["kind"] for step in cse["typical_pathway"]] == ["stream", "exam", "degree", "roles"]
    assert "degree:bca" in {p["degree"]["key"] for p in cse["alternative_pathways"]}
    assert cse["skills"][0]["key"] == "skill:programming_fundamentals" and cse["skills"][0]["status"] == "not_measured"
    assert cse["skill_gaps"] == [], "nothing measured, so no gaps are claimed"
    text = json.dumps(out).lower()
    assert "best match" not in text and '"rank"' not in text


def test_a_measured_gap_and_the_foundations_it_holds_back(db_session, library):
    asha = student(db_session)
    take(db_session, asha, "interests", answers(TECH))
    take(db_session, asha, "coding_check", choose=lambda i: right(i, wrong={"c3", "c4", "c5", "c6", "c7", "c8"}))
    cse = career(engine.options(db_session, asha, embedder=None), "cse")
    gap = next(s for s in cse["skill_gaps"] if s["key"] == "skill:programming_fundamentals")
    assert gap["measured_as"] == "check:programming" and gap["says"]["en"] == "2 of 8 right"
    assert {"key": "skill:data_structures_algorithms", "name": {"en": "Data structures and algorithms",
            "hi": "डेटा स्ट्रक्चर और एल्गोरिदम"}} in [g["needed_for"] for g in cse["foundation_gaps"]]


def test_one_career_in_full(db_session, library, official):
    asha = student(db_session)
    asha.state = "Madhya Pradesh"
    db_session.commit()
    take(db_session, asha, "interests", answers(TECH))
    take(db_session, asha, "aptitude", choose=right)
    ai = engine.explain(db_session, asha, "ai_data", embedder=None)
    path = [s["key"] for s in ai["learning_path"]]
    assert path.index("skill:programming_fundamentals") < path.index("skill:python") < path.index("skill:machine_learning")
    assert "skill:logical_reasoning" not in path, "5 of 5 right: already a strength, so not on the path"
    python = next(s for s in ai["learning_path"] if s["key"] == "skill:python")
    assert python["try"] and all(t["name"]["en"] for t in python["try"])
    assert ai["colleges"] == {"total": 2, "in_state": 1, "state": "Madhya Pradesh"}
    assert ai["colleges_in_state"]["colleges"][0]["name"].startswith("Maulana Azad")
    assert {r["key"] for r in ai["related"]} >= {"career:cse"}
    assert ai["sources"]["unreviewed_links"] > 0 and "not yet reviewed" in ai["sources"]["note"]["en"]


def test_a_career_guide_works_without_assessments(db_session, library):
    asha = student(db_session)
    law = engine.explain(db_session, asha, "law", embedder=None)
    assert law["band"] is None and law["required_education"]["degree"]["key"] == "degree:ba_llb"
    assert {e["key"] for e in law["required_education"]["exams"]} == {"exam:CLAT", "exam:AILET"}
    assert law["questions"][0]["en"].startswith("Do you enjoy arguing")
    assert engine.explain(db_session, asha, "astronaut", embedder=None) is None
