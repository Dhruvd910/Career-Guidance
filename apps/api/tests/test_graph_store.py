"""What the career graph answers, on the real knowledge: learning paths, routes in, what a stream
keeps open, related careers, the domain tree, and colleges from official programmes."""

import pytest

from app.knowledge.graph_store import graph
from app.models.college import Branch, College, CollegeCourse, Course
from app.models.exam import Exam


@pytest.fixture()
def official(db_session):
    """Two real-looking programmes in Madhya Pradesh, one in Kerala."""
    exam = Exam(code="JEE_MAIN", name="JEE Main", category="engineering")
    btech = Course(name="B.Tech", level="UG", duration_years=4)
    db_session.add_all([exam, btech])
    db_session.flush()
    ai = Branch(course_id=btech.id, name="Artificial Intelligence and Data Science", code="AIDS")
    cse = Branch(course_id=btech.id, name="Computer Science and Engineering", code="CSE")
    nit = College(canonical_name="Maulana Azad National Institute of Technology Bhopal", college_type="NIT",
                  ownership="government", state="Madhya Pradesh", city="Bhopal", is_demo_data=False)
    iiit = College(canonical_name="IIIT Kottayam", college_type="IIIT", ownership="government", state="Kerala",
                   city="Kottayam", is_demo_data=False)
    db_session.add_all([ai, cse, nit, iiit])
    db_session.flush()
    for college, branch in ((nit, ai), (nit, cse), (iiit, cse)):
        db_session.add(CollegeCourse(college_id=college.id, course_id=btech.id, branch_id=branch.id, exam_id=exam.id,
                                     source="JoSAA opening & closing ranks", academic_year="2026-27",
                                     verification_status="verified"))
    db_session.commit()
    return {"nit": nit, "iiit": iiit}


@pytest.fixture()
def store(db_session, official):
    return graph(db_session)


def test_a_learning_path_puts_foundations_first(store):
    path = [s["key"] for s in store.prerequisite_path(["skill:machine_learning"])]
    assert path[-1] == "skill:machine_learning"
    for before, after in [("skill:logical_reasoning", "skill:programming_fundamentals"),
                          ("skill:programming_fundamentals", "skill:python"),
                          ("skill:python", "skill:data_analysis"),
                          ("skill:school_mathematics", "skill:probability_statistics"),
                          ("skill:linear_algebra", "skill:machine_learning")]:
        assert path.index(before) < path.index(after), (before, after)
    ml = next(s for s in store.prerequisite_path(["skill:machine_learning"]) if s["key"] == "skill:machine_learning")
    assert ml["depth"] == 0 and "skill:data_analysis" in ml["needs"]


def test_routes_into_ai_with_subjects_streams_exams_and_programmes(store):
    routes = store.pathways("career:ai_data")
    common = {r["degree"]["key"]: r for r in routes["common"]}
    btech = common["degree:btech_ai_ds"]
    assert [s["key"] for s in btech["subjects"]["mandatory"]] == ["subject:physics", "subject:chemistry", "subject:mathematics"]
    assert [s["key"] for s in btech["streams"]] == ["stream:pcm", "stream:pcmb"]
    assert {"exam:JEE_MAIN", "exam:JEE_ADVANCED"} <= {e["key"] for e in btech["exams"]}
    assert next(e for e in btech["exams"] if e["key"] == "exam:JEE_MAIN")["url"] == "https://jeemain.nta.nic.in"
    assert btech["colleges_on_record"] == 1 and btech["programmes_on_record"] == 1
    assert {"degree:bs_maths_stats", "degree:mtech_ms"} <= {r["degree"]["key"] for r in routes["alternative"]}
    assert btech["review"] == "unreviewed"


def test_civil_services_has_its_own_exam(store):
    assert [e["key"] for e in store.pathways("career:civil_services")["career_exams"]] == ["exam:UPSC_CSE"]


def bucket(result, career):
    for name in ("open", "if_you_add", "closed"):
        for row in result[name]:
            if row["career"]["key"] == career:
                return name, row
    raise AssertionError(career)


def test_what_pcb_keeps_open_and_what_it_closes(store):
    pcb = store.open_by_stream("stream:pcb")
    assert bucket(pcb, "career:mbbs")[0] == "open"
    assert bucket(pcb, "career:pharmacy")[0] == "open", "physics, chemistry and maths OR biology"
    assert bucket(pcb, "career:law")[0] == "open"
    status, cse = bucket(pcb, "career:cse")
    assert status == "open" and cse["via"]["key"] == "degree:bca", "still open through BCA"
    assert any(n["key"] == "subject:mathematics" for n in cse["notes"]), "…with the maths caveat"
    status, robotics = bucket(pcb, "career:robotics")
    assert status == "closed" and [m["key"] for m in robotics["missing"]] == ["subject:mathematics"]


def test_commerce_with_maths_opens_more(store):
    commerce = store.open_by_stream("stream:commerce")
    assert bucket(commerce, "career:ca")[0] == "open"
    status, ai = bucket(commerce, "career:ai_data")
    assert status == "if_you_add" and [m["key"] for m in ai["missing"]] == ["subject:mathematics"]
    assert bucket(commerce, "career:mbbs")[0] == "closed"


def test_humanities_keeps_civil_services_and_law_open(store):
    humanities = store.open_by_stream("stream:humanities")
    assert bucket(humanities, "career:civil_services")[0] == "open"
    assert bucket(humanities, "career:law")[0] == "open"
    status, mbbs = bucket(humanities, "career:mbbs")
    assert status == "closed" and {m["key"] for m in mbbs["missing"]} == {"subject:physics", "subject:chemistry", "subject:biology"}


def test_defence_is_open_to_all_with_a_note_for_the_air_force_and_navy(store):
    status, defence = bucket(store.open_by_stream("stream:commerce"), "career:defence")
    assert status == "open" and any("Air Force" in n["note"] for n in defence["notes"])


def test_related_careers_named_and_by_shared_skills(store):
    cse = {r["key"]: r for r in store.related("career:cse", limit=8)}
    assert cse["career:ai_data"]["via"] == "related"
    assert "skill:programming_fundamentals" in {s["key"] for s in cse["career:cybersecurity"]["shared_skills"]}
    robotics = {r["key"]: r for r in store.related("career:robotics", limit=8)}
    assert robotics["career:aerospace"]["via"] == "shared skills", "not named anywhere, found by what they share"
    assert list(robotics).index("career:aerospace") > list(robotics).index("career:ece"), "named ones first"


def test_the_domain_tree(store):
    tree = {d["key"]: d for d in store.domain_tree()}
    assert list(tree)[0] == "domain:technology"
    tech = {c["key"]: c for c in tree["domain:technology"]["careers"]}
    assert set(tech) == {"career:cse", "career:ai_data", "career:cybersecurity", "career:robotics", "career:design"}
    assert tech["career:design"]["primary"] is False and tech["career:cse"]["primary"] is True
    assert store.domain_of("career:design")["key"] == "domain:design"


def test_colleges_from_official_programmes_by_state(store, official):
    everywhere = store.colleges_for("career:ai_data")
    assert everywhere["total"] == 2 and everywhere["colleges"][0]["type"] == "NIT", "NITs listed before IIITs"
    mp = store.colleges_for("career:ai_data", state="madhya pradesh")
    assert [c["college_id"] for c in mp["colleges"]] == [official["nit"].id]
    branches = {p["branch"] for p in mp["colleges"][0]["programmes"]}
    assert branches == {"Artificial Intelligence and Data Science", "Computer Science and Engineering"}
    assert mp["colleges"][0]["sources"] == [{"ref": "JoSAA opening & closing ranks", "academic_year": "2026-27"}]
    assert "fees" in mp["not_included"]


def test_which_careers_need_a_subject_a_skill_or_an_exam(store, db_session):
    """Spec §10's questions the other way round — "which careers need strong maths?" — answered from
    the graph, not the model's memory (which once listed medicine)."""
    maths = {r["key"]: r for r in store.careers_needing("subject:mathematics")}
    assert maths["career:ai_data"]["needed_on"] == "every common route" and maths["career:ai_data"]["draws_on"] == 1.0
    assert "career:mbbs" not in maths, "MBBS goes through PCB: maths isn't needed"
    biology = {r["key"] for r in store.careers_needing("subject:biology")}
    assert {"career:mbbs", "career:bds"} <= biology and "career:cse" not in biology
    python = [r["key"] for r in store.careers_needing("skill:python")]
    assert python[0] == "career:ai_data"
    neet = {r["key"]: r for r in store.careers_needing("exam:NEET_UG")}
    assert neet["career:mbbs"]["needed_on"] == "a common route" and "career:cse" not in neet
    assert store.careers_needing("subject:nothing") == []

    from app.knowledge.tools import careers_needing

    said = careers_needing(db_session, None, {"thing": "ganit"})
    assert said["for"] == "Mathematics" and said["careers"][0]["required"] == "every common route"
    assert careers_needing(db_session, None, {"thing": "NEET"})["for"] == "NEET-UG"
    assert "error" in careers_needing(db_session, None, {"thing": "juggling"})


def test_specialisations_come_from_the_official_programme_names(store, db_session):
    """Spec §10's specialisations layer, read from JoSAA/MCC names — never made up."""
    from app.knowledge.graph_store import _specialisation_in

    assert _specialisation_in("Computer Science and Engineering (Cyber Security)") == "Cyber Security"
    assert _specialisation_in("Mechanical Engineering with specialization in Design and Manufacturing") == "Design and Manufacturing"
    assert _specialisation_in("Computer Science Engineering (Artificial lntelligence)") == "Artificial Intelligence"
    for plain in ("Computer Science and Engineering", "Information Technology (IT)", "B.Tech. (Computer Science and Engineering) - MBA",
                  "B. Tech. and M. Tech. in Engineering Physics (Dual Degree)"):
        assert _specialisation_in(plain) is None, plain
    found = store.specialisations("degree:btech_ai_ds")
    assert found["general"] == 1 and found["specialisations"] == [], "the fixture's MANIT programme is a plain one"
