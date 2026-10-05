"""The career engine over HTTP, and MAYA's career-graph tools."""

from app.ai.tools import TOOL_SPECS, execute_tool
from app.knowledge.graph_store import graph
from app.knowledge.tools import resolve_career
from app.models.student import StudentProfile
from app.seed.careers import seed_careers
from tests.test_assessment_api import auth, run_through
from tests.test_conversation_ws import register
from tests.test_graph_store import official  # noqa: F401 — fixture
from tests.test_career_directions import TECH


def test_the_endpoints(client, db_session, official):
    seed_careers(db_session)
    token = register(client)
    profile = db_session.query(StudentProfile).one()
    profile.state = "Madhya Pradesh"
    db_session.commit()
    run_through(client, token, "interests", lambda item: {"option": TECH.get(item["key"], item["options"][0]["key"])})

    options = client.get("/api/career/options", headers=auth(token)).json()
    assert options["ready"] and options["domains"][0]["domain"] == "domain:technology"
    ai = next(c for d in options["domains"] for c in d["careers"] if c["career_key"] == "ai_data")
    assert ai["colleges"] == {"total": 2, "in_state": 1, "state": "Madhya Pradesh"}

    one = client.get("/api/career/ai_data", headers=auth(token)).json()
    assert one["required_education"]["degree"]["key"] == "degree:btech_ai_ds" and one["learning_path"]
    assert client.get("/api/career/astronaut", headers=auth(token)).status_code == 404

    explore = client.get("/api/career/explore").json()
    assert explore["domains"][0]["key"] == "domain:technology", "routed before /{career_key}"

    pcb = client.get("/api/career/stream/PCB").json()
    assert "career:mbbs" in {r["career"]["key"] for r in pcb["open"]}
    assert client.get("/api/career/stream/astrology").status_code == 404

    colleges = client.get("/api/career/ai_data/colleges", params={"state": "Kerala"}).json()
    assert colleges["total"] == 1 and colleges["colleges"][0]["name"] == "IIIT Kottayam"

    path = client.get("/api/skills/machine_learning/path").json()
    assert path["path"][-1]["key"] == "skill:machine_learning" and path["path"][-1]["try"]
    assert client.get("/api/skills/telepathy/path").status_code == 404
    assert client.get("/api/career/options").status_code == 401


def test_maya_has_the_graph_tools():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert {"career_pathways", "career_skills", "related_careers", "what_stays_open", "colleges_offering"} <= names


def test_careers_are_found_by_the_names_people_use(db_session):
    store = graph(db_session)
    assert resolve_career(store, "ai_data") == "career:ai_data"
    assert resolve_career(store, "AI") == "career:ai_data"
    assert resolve_career(store, "I want to be a doctor") == "career:mbbs"
    assert resolve_career(store, "IAS") == "career:civil_services"
    assert resolve_career(store, "it") is None, "'it' isn't IT"
    assert resolve_career(store, "astronaut") is None


def test_the_tools_answer_from_the_graph(db_session, official):
    from tests.test_assessment_service import student

    seed_careers(db_session)
    asha = student(db_session)
    asha.state = "Madhya Pradesh"
    db_session.commit()

    routes = execute_tool(db_session, asha, "career_pathways", {"career": "AI"})
    first = routes["common_routes"][0]
    assert first["degree"] == "B.Tech in AI / Data Science"
    assert first["class_12_subjects"] == ["Physics", "Chemistry", "Mathematics"]
    assert "JEE Main [https://jeemain.nta.nic.in]" in first["entrance_exams"]
    assert "MAYA's curated knowledge" in routes["source"]

    pcb = execute_tool(db_session, asha, "what_stays_open", {"stream": "PCB"})
    assert "Doctor (MBBS)" in {r["career"] for r in pcb["stays_open"]}
    robotics = next(r for r in pcb["closes"] if r["career"] == "Robotics & Automation")
    assert robotics["needs"] == ["Mathematics"]

    near = execute_tool(db_session, asha, "colleges_offering", {"career": "ai_data"})
    assert near["state"] == "Madhya Pradesh" and near["total"] == 1
    assert near["colleges"][0]["admission_through"] == ["JEE_MAIN"] and "college_facts" in near["for_fees_hostels_distances"]

    skills = execute_tool(db_session, asha, "career_skills", {"career": "cse"})
    assert skills["gaps"] == [] and skills["learning_path"][0]["step"] == 1
    assert "never call it a weakness" in skills["note"]

    unknown = execute_tool(db_session, asha, "career_pathways", {"career": "astronaut"})
    assert "Known careers:" in unknown["error"] and "ai_data (Data Science & Artificial Intelligence)" in unknown["error"]
