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
