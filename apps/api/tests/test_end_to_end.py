"""One full golden-path integration test: register -> profile -> exam profile ->
prediction -> college detail, all through the real HTTP API (spec §55/§62)."""


def test_full_student_journey(client, seeded_jee):
    register = client.post(
        "/api/auth/register",
        json={"email": "journey@example.com", "password": "password123", "name": "Journey Student", "class_level": 12},
    )
    assert register.status_code == 201
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    profile_update = client.put(
        "/api/student/profile",
        json={"state": "TestState", "domicile_state": "TestState", "school_board": "CBSE"},
        headers=headers,
    )
    assert profile_update.status_code == 200
    assert profile_update.json()["state"] == "TestState"

    exam_profile = client.post(
        "/api/exams/profile",
        json={"exam_code": "JEE_MAIN", "status": "qualified", "rank": 800, "category": "General"},
        headers=headers,
    )
    assert exam_profile.status_code == 200
    assert exam_profile.json()["rank"] == 800

    prediction = client.post(
        "/api/predict/jee", json={"exam_code": "JEE_MAIN", "rank": 800, "category": "General"}
    )
    assert prediction.status_code == 200
    results = prediction.json()["results"]
    assert len(results) == 1
    assert results[0]["college_name"] == "Test Institute of Technology"
    assert results[0]["is_demo_data"] is True

    college_id = results[0]["college_id"]
    detail = client.get(f"/api/colleges/{college_id}")
    assert detail.status_code == 200
    assert detail.json()["canonical_name"] == "Test Institute of Technology"

    cutoffs = client.get(f"/api/colleges/{college_id}/cutoffs")
    assert cutoffs.status_code == 200
    assert len(cutoffs.json()) == 3  # 2023, 2024, 2025
    assert all(c["provenance"]["verification_status"] == "unverified_demo" for c in cutoffs.json())

    search = client.get("/api/colleges", params={"q": "Test Institute"})
    assert search.status_code == 200
    assert any(c["id"] == college_id for c in search.json())

    roadmap = client.get("/api/roadmap", headers=headers)
    assert roadmap.status_code == 200
    assert len(roadmap.json()["steps"]) > 0


# ---------------- study plans ----------------

from app.services.roadmap_service import build_study_plan  # noqa: E402


def test_neet_plan_covers_biology_not_maths():
    plan = build_study_plan("NEET_UG", 11)
    names = [s["name"] for s in plan["subjects"]]
    assert names == ["Physics", "Chemistry", "Biology"]
    assert plan["subjects"][0]["classes"][0]["focus"].startswith("Now — Class 11")


def test_jee_plan_covers_maths_and_points_to_the_exact_chapter():
    plan = build_study_plan("JEE_MAIN", 12)
    maths = next(s for s in plan["subjects"] if s["name"] == "Maths")
    now = maths["classes"][0]
    assert now["class_level"] == 12
    integrals = next(c for c in now["chapters"] if c["name"] == "Integrals")
    assert integrals["where"] == "NCERT Mathematics Part 2 (Class 12), Chapter 7"
    assert integrals["weight"] == "high"


def test_every_subject_has_free_resources_and_the_plan_names_its_sources():
    plan = build_study_plan("JEE_ADVANCED", 11)
    assert all(s["resources"] for s in plan["subjects"])
    assert any("ncert" in src["url"] for src in plan["sources"])


def test_no_exam_goal_means_no_chapter_plan():
    assert build_study_plan(None, 11) is None
    assert build_study_plan("careers", 11) is None
