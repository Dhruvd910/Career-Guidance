"""Consent for MAYA's memory: off until given, a guardian for minors, and withdrawal deletes."""

from datetime import datetime, timezone

import pytest

from app.memory import consent
from app.models.memory import DataRequest, MemoryItem, SessionSummary, StudentEvent, TurnAnalysis
from app.models.chat import Conversation, Message
from app.models.student import StudentProfile

GUARDIAN = {"name": "Sunita Sharma", "relationship": "mother", "contact": "98xxxxxx10"}


def signup(client, email="c@example.com", birth_year=None):
    token = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "Asha", "class_level": 10,
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    if birth_year:
        client.put("/api/student/profile", json={"birth_year": birth_year}, headers=headers)
    return headers


def test_memory_is_off_until_someone_says_yes(client):
    body = client.get("/api/consent", headers=signup(client)).json()
    assert body["long_term_memory"] == {"granted": False, "granted_by": None, "verification": None, "decided_at": None}
    assert body["emotion_signals"]["granted"] is False
    assert body["is_minor"] is True, "no birth year: a guardian decides"
    assert body["notice"]["en"].startswith("MAYA can remember") and "MAYA" in body["notice"]["hi"]


def test_a_minor_cannot_consent_alone(client):
    headers = signup(client)
    r = client.post("/api/consent", json={"kind": "long_term_memory", "granted": True}, headers=headers)
    assert r.status_code == 422 and "parent or guardian" in r.json()["detail"]
    r = client.post("/api/consent", json={"kind": "long_term_memory", "granted": True,
                                          "guardian": {**GUARDIAN, "contact": " "}}, headers=headers)
    assert r.status_code == 422 and "contact" in r.json()["detail"]


def test_a_guardian_consents_and_it_is_recorded_as_declared(client):
    headers = signup(client)
    r = client.post("/api/consent", json={"kind": "long_term_memory", "granted": True, "guardian": GUARDIAN},
                    headers=headers)
    state = r.json()["state"]
    assert state["granted"] is True and state["granted_by"] == "guardian" and state["verification"] == "declared"
    assert client.get("/api/consent", headers=headers).json()["long_term_memory"]["granted"] is True


def test_an_adult_consents_for_themselves(client):
    headers = signup(client, birth_year=datetime.now(timezone.utc).year - 20)
    r = client.post("/api/consent", json={"kind": "emotion_signals", "granted": True}, headers=headers)
    assert r.status_code == 200 and r.json()["state"]["granted_by"] == "student"


@pytest.mark.parametrize("age, minor", [(10, True), (17, True), (18, True), (19, False), (30, False)])
def test_who_counts_as_a_minor(age, minor):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    profile = StudentProfile(name="x", class_level=12, birth_year=now.year - age)
    assert consent.is_minor(profile, today=now) is minor, "the year someone turns 18 still needs a guardian"


def test_withdrawing_deletes_what_it_covered(client, db_session):
    headers = signup(client)
    client.post("/api/consent", json={"kind": "long_term_memory", "granted": True, "guardian": GUARDIAN}, headers=headers)
    client.post("/api/consent", json={"kind": "emotion_signals", "granted": True, "guardian": GUARDIAN}, headers=headers)
    profile = db_session.query(StudentProfile).one()
    conversation = Conversation(student_profile_id=profile.id)
    db_session.add(conversation)
    db_session.flush()
    message = Message(conversation_id=conversation.id, role="user", content="hi")
    db_session.add(message)
    db_session.flush()
    first = MemoryItem(student_profile_id=profile.id, kind="fact", text="likes robots")
    db_session.add(first)
    db_session.flush()
    db_session.add_all([
        MemoryItem(student_profile_id=profile.id, kind="fact", text="likes robots a lot", superseded_by=None),
        SessionSummary(conversation_id=conversation.id, student_profile_id=profile.id, summary="talked"),
        StudentEvent(student_profile_id=profile.id, event_type="COUNSELLING_SESSION"),
        TurnAnalysis(message_id=message.id, student_profile_id=profile.id, intent="career_decision"),
    ])
    first.superseded_by = first.id  # a chain the delete has to untangle
    db_session.commit()

    r = client.post("/api/consent", json={"kind": "long_term_memory", "granted": False}, headers=headers)
    assert r.status_code == 200, "anyone can switch memory off"
    deleted = r.json()["deleted"]
    assert deleted["memory_items"] == 2 and deleted["session_summaries"] == 1 and deleted["student_events"] == 1
    assert db_session.query(MemoryItem).count() == 0 and db_session.query(SessionSummary).count() == 0
    assert db_session.query(TurnAnalysis).count() == 1, "emotion signals have their own permission"
    assert db_session.query(Message).count() == 1, "the conversation itself isn't long-term memory"

    client.post("/api/consent", json={"kind": "emotion_signals", "granted": False}, headers=headers)
    assert db_session.query(TurnAnalysis).count() == 0
    requests = db_session.query(DataRequest).order_by(DataRequest.id).all()
    assert [r.kind for r in requests] == ["delete_long_term_memory", "delete_emotion_signals"]


def test_consent_is_per_student(client):
    a = signup(client, "a@example.com")
    b = signup(client, "b@example.com")
    client.post("/api/consent", json={"kind": "long_term_memory", "granted": True, "guardian": GUARDIAN}, headers=a)
    assert client.get("/api/consent", headers=b).json()["long_term_memory"]["granted"] is False


def test_unknown_kinds_are_refused(client):
    r = client.post("/api/consent", json={"kind": "selling_data", "granted": True, "guardian": GUARDIAN},
                    headers=signup(client))
    assert r.status_code == 422
