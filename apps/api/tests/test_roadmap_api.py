"""The roadmap and progress over HTTP."""

from app.seed.careers import seed_careers
from tests.test_assessment_api import auth, run_through
from tests.test_conversation_ws import register


def test_the_roadmap_endpoints(client, db_session):
    seed_careers(db_session)
    token = register(client)
    first = client.get("/api/roadmap", headers=auth(token)).json()
    assert first["version"] == 1 and first["focus"] is None
    assert first["stages"][0]["node_key"] == "stage:class_10" and first["next_step"]["node_key"] == "task:assessment:interests"

    focused = client.post("/api/roadmap/focus", json={"career": "doctor"}, headers=auth(token)).json()
    assert focused["changed"] and focused["version"] == 2
    assert client.post("/api/roadmap/focus", json={"career": "astronaut"}, headers=auth(token)).status_code == 400

    hard = client.post("/api/roadmap/recalculate", headers=auth(token),
                       json={"kind": "difficulty", "subject": "chemistry", "detail": "chemistry feels hard"}).json()
    assert any(c["node_key"] == "module:foundation:chemistry" for c in hard["changes"])
    assert client.post("/api/roadmap/recalculate", json={"kind": "time_budget"}, headers=auth(token)).status_code == 400
    assert client.post("/api/roadmap/recalculate", json={"kind": "teleport"}, headers=auth(token)).status_code == 400

    versions = client.get("/api/roadmap/versions", headers=auth(token)).json()
    assert [v["version"] for v in versions] == [1, 2, 3] and versions[2]["trigger"]["kind"] == "difficulty"
    old = client.get("/api/roadmap", params={"version": 1}, headers=auth(token)).json()
    assert old["version"] == 1 and old["latest_version"] == 3
    assert client.get("/api/roadmap", params={"version": 9}, headers=auth(token)).status_code == 404

    done = client.post("/api/progress/update", headers=auth(token),
                       json={"node_key": "task:assessment:interests", "status": "done", "note": "took it"}).json()
    assert done["next_step"]["node_key"] != "task:assessment:interests"
    assert client.post("/api/progress/update", headers=auth(token),
                       json={"node_key": "nope", "status": "done"}).status_code == 404

    run_through(client, token, "aptitude", lambda item: {"option": item["options"][0]["key"]})
    mine = client.get("/api/progress", headers=auth(token)).json()
    assert mine["assessments"]["kinds"] == ["aptitude"] and mine["skills"]
    assert mine["roadmap"]["focus"]["key"] == "mbbs" and "not a skill score" in mine["note"]["en"]
    assert client.get("/api/roadmap/next-step", headers=auth(token)).json()["next_step"]
    assert client.get("/api/roadmap").status_code == 401


def test_one_student_never_sees_anothers_roadmap(client, db_session):
    seed_careers(db_session)
    asha, ravi = register(client, "asha@example.com"), register(client, "ravi@example.com")
    client.post("/api/roadmap/focus", json={"career": "doctor"}, headers=auth(asha))
    client.post("/api/progress/update", json={"node_key": "task:assessment:interests", "status": "done"}, headers=auth(asha))

    his = client.get("/api/roadmap", headers=auth(ravi)).json()
    assert his["version"] == 1 and his["focus"] is None, "his own first roadmap, not her version 2"
    assert client.get("/api/roadmap", params={"version": 2}, headers=auth(ravi)).status_code == 404
    assert [v["version"] for v in client.get("/api/roadmap/versions", headers=auth(ravi)).json()] == [1]
    assert client.get("/api/roadmap/next-step", headers=auth(ravi)).json()["next_step"]["node_key"] == "task:assessment:interests"
    assert client.get("/api/progress", headers=auth(ravi)).json()["roadmap"]["focus"] is None
