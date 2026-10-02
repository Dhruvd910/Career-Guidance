"""What MAYA already had, moved into the bundle honestly: every college's identity, short names
and admission route from the official tables; the hand-researched fees marked for verification,
and the secondary-source ones held for review."""

from app.facts import store
from app.ingest import official_tables, profiles
from app.models.college import College, CollegeCourse, Course
from app.models.exam import Exam
from app.okf import bundle
from app.services import college_service


def official(db, name, city, state, kind, exam_code, programmes):
    exam = db.query(Exam).filter_by(code=exam_code).one_or_none()
    if exam is None:
        exam = Exam(code=exam_code, name=exam_code, category="engineering")
        db.add(exam)
        db.flush()
    course = db.query(Course).first() or Course(name="B.Tech", level="UG", duration_years=4)
    db.add(course)
    db.flush()
    c = College(canonical_name=name, college_type=kind, ownership="government", state=state, city=city, is_demo_data=False)
    db.add(c)
    db.flush()
    for _ in range(programmes):
        db.add(CollegeCourse(college_id=c.id, course_id=course.id, exam_id=exam.id, source="JoSAA",
                             verification_status="verified"))
    db.flush()
    return c


def test_every_college_gets_its_identity_short_names_and_route(tmp_path, db_session):
    manit = official(db_session, "Maulana Azad National Institute of Technology Bhopal", "Bhopal", "Madhya Pradesh",
                     "NIT", "JEE_MAIN", 3)
    aiims = official(db_session, "AIIMS, New Delhi", "New Delhi", "Delhi", "AIIMS", "NEET_UG", 1)
    report = official_tables.run(db_session, root=tmp_path)
    assert report["missing"] == [] and report["problems"] == [] and report["colleges"] == 2
    route = store.current(db_session, "college", manit.id)["admission.route"]
    assert route["value"] == {"route": "JoSAA 2026", "exam": "JEE (Main)", "programmes": 3}
    assert route["source"]["tier"] == 3 and route["status"] == "verified" and route["source"]["locator"].startswith("row ")
    assert route["quote"].startswith("Maulana Azad National Institute of Technology Bhopal, ")
    assert store.current(db_session, "college", aiims.id)["admission.route"]["value"]["exam"] == "NEET-UG"
    assert manit.aliases == ["NIT Bhopal", "MANIT", "MANIT Bhopal"]
    assert [c.canonical_name for c in college_service.search_colleges(db_session, q="manit")] == [manit.canonical_name], \
        "Phase 4's note: MANIT is found by its short name"
    assert bundle.check(tmp_path) == []
    assert bundle.read(tmp_path, "colleges/aiims-new-delhi/college").meta["maya"]["entity"]["aliases"] == ["AIIMS New Delhi", "AIIMS Delhi"]


def test_the_researched_fees_are_marked_honestly(tmp_path, db_session):
    bombay = official(db_session, "Indian Institute of Technology Bombay", "Mumbai", "Maharashtra", "IIT", "JEE_ADVANCED", 1)
    aiims = official(db_session, "AIIMS, New Delhi", "New Delhi", "Delhi", "AIIMS", "NEET_UG", 1)
    report = profiles.run(db_session, root=tmp_path)
    assert report["problems"] == []
    fee = store.current(db_session, "college", bombay.id)["fee.tuition.annual"]
    assert fee["value"]["amount"] == 200000 and fee["status"] == "unverified" and fee["label"]["en"] == "Needs verification"
    assert fee["source"]["name"] == "IIT Roorkee" and "not checked for this college" in fee["source"]["locator"]
    assert "fee.tuition.annual" not in store.current(db_session, "college", aiims.id), "a secondary-source fee waits for review"
    held = store.waiting(db_session)
    assert [(f.attribute, f.flags) for f in held] == [("fee.tuition.annual", ["a fee from a secondary source (Careers360)"])]


def test_the_facts_reach_the_api_and_maya(tmp_path, client, db_session):
    from app.ai.tools import execute_tool
    from tests.test_assessment_service import student

    manit = official(db_session, "Maulana Azad National Institute of Technology Bhopal", "Bhopal", "Madhya Pradesh",
                     "NIT", "JEE_MAIN", 2)
    official_tables.run(db_session, root=tmp_path)
    body = client.get(f"/api/colleges/{manit.id}/facts", params={"topic": "admissions"}).json()
    route = body["facts"]["admission.route"]
    assert route["source"]["name"] == "JoSAA" and route["label"]["state"] in ("fresh", "stale")
    assert client.get(f"/api/colleges/{manit.id}/facts", params={"topic": "gossip"}).status_code == 400
    asha = student(db_session)
    said = execute_tool(db_session, asha, "college_facts", {"college_id": manit.id, "topic": "admissions"})
    assert said["facts"][0]["value"] == "JoSAA 2026 via JEE (Main) (2 programmes)" and said["facts"][0]["official"]
    none = execute_tool(db_session, asha, "college_facts", {"college_id": manit.id, "topic": "fees"})
    assert none["facts"] == [] and "say so plainly" in none["note"]


def test_an_exact_short_name_comes_first(tmp_path, db_session):
    bhu = official(db_session, "Indian Institute of Technology (BHU) Varanasi", "Varanasi", "Uttar Pradesh", "IIT", "JEE_ADVANCED", 1)
    official(db_session, "Indian Institute of Technology Bhubaneswar", "Bhubaneswar", "Odisha", "IIT", "JEE_ADVANCED", 1)
    official_tables.run(db_session, root=tmp_path)
    found = college_service.search_colleges(db_session, q="IIT BHU")
    assert found[0].canonical_name == bhu.canonical_name and len(found) == 2
