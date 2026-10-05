import json

from app.models.college import College
from app.services import college_profiles
from app.services.college_profiles import PROFILES, admission_summary, profile_for, search_variants


def test_every_profile_reference_resolves_and_cites_a_source():
    data = json.loads(PROFILES.read_text())
    for name, raw in data["colleges"].items():
        profile = profile_for(name)
        assert profile["surroundings"], f"{name}: no surroundings"
        for section in ("nirf", "fees", "placements"):
            ref = raw.get(section)
            if isinstance(ref, str):
                assert ref in data["templates"], f"{name}: unknown template {ref}"
            if isinstance(ref, dict) and "source" in ref:
                assert ref["source"] in data["sources"], f"{name}: unknown source {ref['source']}"
        if profile["nirf"]:
            assert profile["nirf"]["source"]["url"].startswith("https://")


def test_templates_are_filled_in_and_not_shared_between_calls():
    iit = profile_for("Indian Institute of Technology Bombay")
    assert iit["fees"]["tuition_per_year"] == 200_000
    assert iit["fees"]["source"]["url"].startswith("https://")
    assert iit["placements"]["median_lpa"] == 19.61
    iit["fees"]["summary"] = "changed"
    assert profile_for("Indian Institute of Technology Delhi")["fees"]["summary"] != "changed"


def test_medical_colleges_explain_there_are_no_campus_placements():
    aiims = profile_for("AIIMS, New Delhi")
    assert "NEET-PG" in aiims["placements"]["note"]
    assert aiims["nirf"]["rank"] == 1


def test_unresearched_college_has_no_profile():
    assert profile_for("Test Institute of Technology") is None


def test_students_can_search_by_short_names():
    assert "indian institute of technology bombay" in search_variants("IIT Bombay")
    assert "national institute of technology, tiruchirappalli" in search_variants("NIT  Trichy")


def test_admission_summary_uses_open_all_india_seats(db_session, seeded_jee):
    summary = admission_summary(db_session, seeded_jee["college"].id)
    assert summary["exam_code"] == "JEE_MAIN"
    assert summary["year"] == 2025  # the latest year loaded
    assert summary["toughest"] == {"program": "Computer Science and Engineering (B.Tech)",
                                   "closing_rank": 1000, "quota": "AI"}


def test_compare_includes_profile_and_admission(client, db_session, seeded_jee):
    other = College(canonical_name="AIIMS, New Delhi", college_type="AIIMS", ownership="government",
                    state="Delhi", city="New Delhi", is_demo_data=False)
    db_session.add(other)
    db_session.commit()
    response = client.post("/api/colleges/compare", json={"college_ids": [seeded_jee["college"].id, other.id]})
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert rows[0]["admission"]["toughest"]["closing_rank"] == 1000 and rows[0]["profile"] is None
    assert rows[1]["profile"]["nirf"]["rank"] == 1
    assert rows[1]["approximate_annual_cost"] == 4228  # researched tuition when no fee rows exist


def test_search_puts_researched_colleges_first(client, db_session, seeded_jee):
    db_session.add(College(canonical_name="AIIMS, New Delhi", college_type="AIIMS", ownership="government",
                           state="Delhi", city="New Delhi", is_demo_data=False))
    db_session.commit()
    names = [c["canonical_name"] for c in client.get("/api/colleges").json()]
    assert names[0] == "AIIMS, New Delhi"
    assert college_profiles.researched_names()


def test_a_colleges_programmes_and_admissions_have_their_own_routes(client, seeded_jee):
    """Spec §25: GET /colleges/{id}/programs and /colleges/{id}/admissions."""
    college = seeded_jee["college"]
    programmes = client.get(f"/api/colleges/{college.id}/programs").json()
    assert programmes and programmes[0]["exam_code"] == "JEE_MAIN" and "source" in programmes[0]["provenance"]
    admissions = client.get(f"/api/colleges/{college.id}/admissions").json()
    assert set(admissions) == {"college_id", "routes", "facts"}
    assert client.get("/api/colleges/999999/programs").status_code == 404


def test_a_counselling_session_starts_like_a_conversation(client):
    token = client.post("/api/auth/register", json={"email": "s@example.com", "password": "password123", "name": "S",
                                                     "class_level": 10}).json()["access_token"]
    started = client.post("/api/counselling/session", json={"channel": "text"}, headers={"Authorization": f"Bearer {token}"})
    assert started.status_code == 200 and started.json()["session_id"]
