"""The assessment API end to end, the answer interpreter, and the old quiz's way in."""

import json

import pytest

from app.models.assessment import AssessmentAttempt
from app.models.career import CareerAssessment
from app.models.student import StudentProfile
from app.routers import assessment as assessment_router
from app.seed.careers import seed_careers
from scripts.migrate_legacy_assessments import migrate
from tests.fakes import FakeLLM
from tests.test_conversation_ws import register


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def run_through(client, token, key, choose):
    view = client.post("/api/assessment/start", json={"instrument_key": key}, headers=auth(token)).json()
    while not view["complete"]:
        item = view["item"]
        picked = choose(item)
        view = client.post("/api/assessment/answer", headers=auth(token), json={
            "attempt_id": view["attempt_id"], "item_key": item["key"], "answer": picked, "skipped": picked is None,
        })
        assert view.status_code == 200, view.text
        view = view.json()
    return view


def test_take_an_assessment_and_see_the_directions(client, db_session):
    seed_careers(db_session)
    token = register(client)
    listed = client.get("/api/assessment/instruments", headers=auth(token)).json()
    assert [i["key"] for i in listed] == ["interests", "aptitude", "skills", "academic", "coding_check", "spatial"]
    assert listed[0]["title"] == {"en": "What you enjoy", "hi": "आपको क्या पसंद है"}

    done = run_through(client, token, "interests", lambda item: {"option": item["options"][0]["key"]})
    assert done["complete"] and done["result"]["scores"]
    again = client.get("/api/assessment/result", params={"attempt_id": done["attempt_id"]}, headers=auth(token)).json()
    assert again["scores"] == done["result"]["scores"]

    directions = client.get("/api/careers/directions", headers=auth(token))
    assert directions.status_code == 200, "not swallowed by /api/careers/{career_id}"
    assert directions.json()["ready"] and directions.json()["summary"]["strong"]
    one = client.get("/api/careers/directions/cse", headers=auth(token)).json()
    assert one["career_key"] == "cse" and one["band"] in ("strong", "potential", "explore", "weak")
    assert client.get("/api/careers/directions/astronaut", headers=auth(token)).status_code == 404
    assert client.get("/api/careers/key/cse").status_code == 200, "the career guides still answer"


def test_back_history_and_delete(client):
    token = register(client)
    view = client.post("/api/assessment/start", json={"instrument_key": "skills", "language": "hi"},
                       headers=auth(token)).json()
    assert view["language"] == "hi" and view["item"]["say"].startswith("अब आठ हुनर")
    client.post("/api/assessment/answer", headers=auth(token),
                json={"attempt_id": view["attempt_id"], "item_key": "programming", "answer": {"option": "l1"}})
    back = client.post("/api/assessment/back", json={"attempt_id": view["attempt_id"]}, headers=auth(token)).json()
    assert back["item"]["key"] == "programming" and back["item"]["answer"] == {"option": "l1"}
    assert client.get("/api/assessment/result", params={"attempt_id": view["attempt_id"]},
                      headers=auth(token)).status_code == 400, "not finished yet"

    run_through(client, token, "skills", lambda item: {"option": "l2"})
    history = client.get("/api/assessment/history", params={"instrument_key": "skills"}, headers=auth(token)).json()
    assert len(history["attempts"]) == 1
    gone = client.delete(f"/api/assessment/attempts/{view['attempt_id']}", headers=auth(token))
    assert gone.status_code == 204
    assert client.get("/api/assessment/history", params={"instrument_key": "skills"},
                      headers=auth(token)).json()["attempts"] == []


def test_bad_requests_say_what_is_wrong(client):
    token, other = register(client), register(client, "other@example.com")
    view = client.post("/api/assessment/start", json={"instrument_key": "interests"}, headers=auth(token)).json()
    wrong = client.post("/api/assessment/answer", headers=auth(token),
                        json={"attempt_id": view["attempt_id"], "item_key": "int_maths", "answer": {"option": "adore"}})
    assert wrong.status_code == 400 and "isn't one of the answers" in wrong.json()["detail"]
    theirs = client.post("/api/assessment/answer", headers=auth(other),
                         json={"attempt_id": view["attempt_id"], "item_key": "int_maths", "answer": {"option": "love"}})
    assert theirs.status_code == 404
    assert client.post("/api/assessment/start", json={"instrument_key": "astrology"},
                       headers=auth(token)).status_code == 404
    assert client.get("/api/assessment/instruments").status_code == 401


@pytest.mark.parametrize("item_key, model_says, expected", [
    ("int_maths", {"option": "love"}, {"answer": {"option": "love"}, "skip": False}),
    ("int_maths", {"option": "adore"}, {"answer": None, "skip": False}),  # never an answer that doesn't exist
    ("int_maths", {"option": None}, {"answer": None, "skip": False}),
    ("int_maths", {"skip": True}, {"answer": None, "skip": True}),
])
def test_unclear_spoken_answers_are_interpreted_but_never_invented(client, monkeypatch, item_key, model_says, expected):
    token = register(client)
    llm = FakeLLM(json.dumps(model_says))
    monkeypatch.setattr(assessment_router, "get_llm_provider", lambda: llm)
    view = client.post("/api/assessment/start", json={"instrument_key": "interests"}, headers=auth(token)).json()
    out = client.post("/api/assessment/interpret", headers=auth(token), json={
        "attempt_id": view["attempt_id"], "item_key": item_key, "transcript": "maths toh meri jaan hai yaar"}).json()
    assert out == expected
    prompt = llm.seen[0][1]["content"]
    assert 'key "love"' in prompt and "maths toh meri jaan hai yaar" in prompt


def test_measured_answers_are_never_left_to_a_model(client, monkeypatch):
    """Marks and problems are matched on the Pi or tapped: a model misreading "sattasi" (87) as 37,
    or leaning towards the right answer, would quietly change a score."""
    token = register(client)
    llm = FakeLLM('{"option": "b"}')
    monkeypatch.setattr(assessment_router, "get_llm_provider", lambda: llm)
    for key in ("academic", "aptitude"):
        view = client.post("/api/assessment/start", json={"instrument_key": key}, headers=auth(token)).json()
        out = client.post("/api/assessment/interpret", headers=auth(token), json={
            "attempt_id": view["attempt_id"], "item_key": view["item"]["key"], "transcript": "sattasi"}).json()
        assert out == {"answer": None, "skip": False}
    assert llm.seen == []


def test_the_old_quiz_still_works_and_lands_in_the_new_tables(client, db_session):
    seed_careers(db_session)
    token = register(client)
    answers = {"int_maths": "love", "maths_style": "logic", "int_computer": "love", "hospital": "avoid"}
    old = client.post("/api/careers/assessment", headers=auth(token),
                      json={"assessment_type": "class11_12_career", "responses": {"answers": answers}})
    assert old.status_code == 201 and old.json()["results"]
    attempt = db_session.query(AssessmentAttempt).one()
    assert attempt.status == "completed" and attempt.legacy_assessment_id == old.json()["id"]
    assert attempt.path == ["int_maths", "maths_style", "hospital", "int_computer"]


def test_old_assessments_are_brought_over_once(db_session):
    from tests.test_assessment_service import student

    seed_careers(db_session)
    asha = student(db_session)
    db_session.add(CareerAssessment(student_profile_id=asha.id, assessment_type="class11_12_career",
                                    responses={"answers": {"int_maths": "hard", "int_biology": "love"}}, results=[]))
    db_session.add(CareerAssessment(student_profile_id=asha.id, assessment_type="class10_stream",
                                    responses={"subject_interest": {"maths": 8}}, results=[]))  # the slider form
    db_session.commit()
    assert migrate(db_session) == (1, 1)
    assert migrate(db_session) == (0, 2)
    attempt = db_session.query(AssessmentAttempt).one()
    assert attempt.completed_at is not None and db_session.get(StudentProfile, asha.id) is not None
    scores = {s.dimension_key: s.score for s in attempt.scores}
    assert scores["maths"] == 0.0 and scores["biology"] == 1.0
