def _register(client, email="student@example.com", password="password123"):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Test Student", "class_level": 11},
    )


def test_register_returns_token(client):
    response = _register(client)
    assert response.status_code == 201
    assert "access_token" in response.json()


def test_duplicate_email_rejected(client):
    _register(client)
    response = _register(client)
    assert response.status_code == 409


def test_login_success(client):
    _register(client, email="login@example.com", password="password123")
    response = client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": "password123"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_wrong_password_rejected(client):
    _register(client, email="wrongpw@example.com", password="password123")
    response = client.post(
        "/api/auth/login", json={"email": "wrongpw@example.com", "password": "not-the-password"}
    )
    assert response.status_code == 401


def test_profile_requires_auth(client):
    response = client.get("/api/student/profile")
    assert response.status_code == 401


def test_profile_accessible_with_token(client):
    token = _register(client, email="profile@example.com").json()["access_token"]
    response = client.get("/api/student/profile", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["name"] == "Test Student"


def test_class_6_to_college_can_sign_up(client):
    """Spec §15: classes 6-8 and college have their own roadmaps — they must be able to get in."""
    def register(email, class_level):
        return client.post("/api/auth/register", json={"email": email, "password": "password123", "name": "A",
                                                        "class_level": class_level})

    assert register("five@example.com", 5).status_code == 422
    token = register("seven@example.com", 7).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    basics = {"state": "Bihar", "domicile_state": "Bihar", "school_board": "CBSE"}
    client.put("/api/student/profile", json=basics, headers=auth)
    step = client.get("/api/student/onboarding/next-step", headers=auth).json()
    assert step["step"] == "memory_permission" and "parent or guardian" in step["prompt"], "asked once, right after the basics"
    client.post("/api/consent", json={"kind": "long_term_memory", "granted": False}, headers=auth)  # "Not now"
    assert client.get("/api/student/onboarding/next-step", headers=auth).json()["step"] == "career_exploration_assessment"

    token = register("college@example.com", 12).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.put("/api/student/profile", json={"education_stage": "ug_y9"}, headers=auth).status_code == 422
    saved = client.put("/api/student/profile", json={"education_stage": "ug_y2", "state": "Bihar", "domicile_state": "Bihar"},
                       headers=auth)
    assert saved.status_code == 200
    client.post("/api/consent", json={"kind": "long_term_memory", "granted": True,
                                      "guardian": {"name": "S", "relationship": "mother", "contact": "x"}}, headers=auth)
    step = client.get("/api/student/onboarding/next-step", headers=auth).json()
    assert step["step"] == "skills_assessment", "no school board needed at college"
