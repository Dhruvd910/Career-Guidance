"""College discovery and the college APIs: filters that never guess (what isn't known is counted,
not assumed), sorting by what the student chooses, facts grouped with their sources, and
comparison cells that carry freshness and conflicts."""

from datetime import datetime, timezone

from app import geo
from app.facts import store
from app.models.college import College, CollegeCourse, Course
from app.models.exam import Exam

T0 = datetime(2026, 10, 2, tzinfo=timezone.utc)


def college(db, name, town, state, exam):
    place = geo.find(town, state)
    e = db.query(Exam).filter_by(code=exam).one_or_none() or Exam(code=exam, name=exam, category="x")
    course = db.query(Course).first() or Course(name="B.Tech", level="UG", duration_years=4)
    db.add_all([e, course])
    db.flush()
    c = College(canonical_name=name, college_type="NIT", ownership="government", state=state, city=town,
                is_demo_data=False, latitude=place.lat if place else None, longitude=place.lng if place else None)
    db.add(c)
    db.flush()
    db.add(CollegeCourse(college_id=c.id, course_id=course.id, exam_id=e.id, source="JoSAA", verification_status="verified"))
    db.flush()
    return c


def fact(db, c, attribute, value, year=None, publisher="site", tier=2):
    src = store.source(db, f"{publisher}-{c.id}", f"{c.canonical_name} (official website)", tier)
    doc = store.document(db, src, f"https://{publisher}{c.id}.ac.in/fees.pdf", "Fee notice 2026-27", T0, sha256=f"{c.id:064d}"[-64:])
    return store.record(db, "college", c.id, attribute, value, document=doc, academic_year=year, quote="…", now=T0)


def setup(db):
    bhopal = college(db, "Maulana Azad National Institute of Technology Bhopal", "Bhopal", "Madhya Pradesh", "JEE_MAIN")
    indore = college(db, "Indian Institute of Technology Indore", "Indore", "Madhya Pradesh", "JEE_ADVANCED")
    trichy = college(db, "National Institute of Technology, Tiruchirappalli", "Tiruchirappalli", "Tamil Nadu", "JEE_MAIN")
    nowhere = college(db, "Imaginary Institute of Technology", "Nowhere Town", "Madhya Pradesh", "JEE_MAIN")
    fact(db, bhopal, "fee.tuition.annual", {"amount": 62500, "per": "semester", "applies_to": "general"}, "2026-27")
    fact(db, bhopal, "facility.hostel", {"text": "Hostels for boys and girls"})
    fact(db, indore, "fee.tuition.annual", {"amount": 200000, "per": "year", "applies_to": "general"}, "2026-27")
    fact(db, trichy, "facility.hostel", {"text": "Hostels for all first-year students"})
    db.commit()
    return bhopal, indore, trichy, nowhere


def test_discovery_filters_without_guessing(client, db_session):
    bhopal, indore, trichy, nowhere = setup(db_session)
    near = client.get("/api/colleges/discover", params={"home": "Indore", "radius_km": 300, "sort": "distance"}).json()
    assert [c["name"] for c in near["colleges"]] == [indore.canonical_name, bhopal.canonical_name]
    assert near["colleges"][0]["distance_km"] < 30 and near["home"] == {"town": "Indore", "state": "Madhya Pradesh"}
    assert near["left_out"] == {"no known location": 1}, "a college with no known location is counted, not guessed"
    cheap = client.get("/api/colleges/discover", params={"budget_max": 150000, "sort": "fee"}).json()
    assert [c["name"] for c in cheap["colleges"]] == [bhopal.canonical_name], "₹62,500 a semester is ₹1,25,000 a year"
    assert cheap["left_out"] == {"no tuition fee on record": 2}
    hostel = client.get("/api/colleges/discover", params={"hostel": True, "exam": "JEE_MAIN"}).json()
    assert {c["name"] for c in hostel["colleges"]} == {bhopal.canonical_name, trichy.canonical_name}
    assert hostel["left_out"] == {"hostel not known": 1} and "No overall score" in hostel["note"]
    row = next(c for c in hostel["colleges"] if c["name"] == bhopal.canonical_name)
    assert row["tuition"]["value"] == "₹62,500 a semester" and row["tuition"]["source"].endswith("(official website)")
    assert client.get("/api/colleges/discover", params={"sort": "best"}).status_code == 400, "there is no 'best'"


def test_a_colleges_facts_sources_and_comparison(client, db_session):
    bhopal, indore, *_ = setup(db_session)
    other = store.source(db_session, "josaa-brochure", "JoSAA", 3)
    doc = store.document(db_session, other, "https://josaa.nic.in/manit.pdf", "JoSAA institute profile", T0, sha256="f" * 64)
    store.record(db_session, "college", bhopal.id, "fee.tuition.annual", {"amount": 60000, "per": "semester", "applies_to": "general"},
                 document=doc, academic_year="2026-27", quote="…", now=T0)
    db_session.commit()
    detail = client.get(f"/api/colleges/{bhopal.id}").json()
    tuition = detail["facts"]["Financial"]["fee.tuition.annual"]
    assert tuition["status"] == "conflicted" and tuition["conflict"][0]["value"]["amount"] == 60000
    assert set(detail["facts"]) == {"Academic", "Financial", "Campus", "Location", "Admissions"}
    sources = client.get(f"/api/colleges/{bhopal.id}/sources").json()
    assert [(s["publisher"], s["tier"]) for s in sources] == [(f"{bhopal.canonical_name} (official website)", 2),
                                                              ("JoSAA", 3)], "best tier first, a conflict's source too"
    rows = client.post("/api/colleges/compare", json={"college_ids": [bhopal.id, indore.id]}).json()["rows"]
    cell = rows[0]["facts"]["fee.tuition.annual"]
    assert cell["value"] == "₹62,500 a semester" and cell["conflict"] == ["₹60,000 a semester (JoSAA)"]
    assert rows[1]["facts"]["facility.hostel"] is None, "unknown stays unknown"
    assert rows[0]["hostel_available"] is True and rows[1]["hostel_available"] is None


def test_by_kind_and_what_was_left_out(client, db_session):
    bhopal, indore, trichy, nowhere = setup(db_session)
    nits = client.get("/api/colleges/discover", params={"kind": "NIT", "home": "Indore", "radius_km": 300}).json()
    assert {c["name"] for c in nits["colleges"]} == {bhopal.canonical_name, indore.canonical_name}, "the test colleges are all typed NIT"
    assert nits["left_out_say"] == "1 left out: no known location — they may also fit, but MAYA can't tell yet."
