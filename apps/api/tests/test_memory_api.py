"""The student's own view of their memory: see it, delete it, follow their journey."""

import pytest

from app.memory import consent
from app.models.chat import Conversation
from app.models.memory import (
    CounsellingThread, DataRequest, MemoryItem, SessionSummary, StudentConstraint, StudentEvent, StudentInterest,
)
from app.models.student import StudentProfile

GUARDIAN = {"name": "Sunita", "relationship": "mother", "contact": "x"}


def signup(client, db, email="m@example.com"):
    token = client.post("/api/auth/register", json={"email": email, "password": "password123", "name": "Asha",
                                                    "class_level": 10}).json()["access_token"]
    profile = db.query(StudentProfile).filter(StudentProfile.user.has(email=email)).one()
    consent.decide(db, profile, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    return {"Authorization": f"Bearer {token}"}, profile


def fill(db, profile):
    conversation = Conversation(student_profile_id=profile.id, status="closed")
    db.add(conversation)
    db.flush()
    thread = CounsellingThread(student_profile_id=profile.id, topic_key="stream_choice", title="PCM vs PCB",
                               current_position="Leaning PCM", open_questions=["Talk to father"])
    db.add_all([
        thread,
        SessionSummary(conversation_id=conversation.id, student_profile_id=profile.id, summary="Discussed streams.",
                       next_steps=["Aptitude assessment"]),
        StudentInterest(student_profile_id=profile.id, label="Robotics"),
        StudentConstraint(student_profile_id=profile.id, kind="family_expectation", detail="Father wants medicine",
                          sensitivity="sensitive"),
        MemoryItem(student_profile_id=profile.id, kind="fact", text="Built a robot"),
        StudentEvent(student_profile_id=profile.id, event_type="CAREER_INTEREST_ADDED", payload={"label": "Robotics"}),
        StudentEvent(student_profile_id=profile.id, event_type="DECISION_MADE", payload={"title": "PCM vs PCB"},
                     reason="Chose PCM"),
    ])
    db.commit()
    return thread


def test_a_student_sees_everything_maya_remembers_private_items_included(client, db_session):
    headers, asha = signup(client, db_session)
    fill(db_session, asha)
    body = client.get("/api/student/memory", headers=headers).json()
    assert body["enabled"] is True
    assert [t["title"] for t in body["threads"]] == ["PCM vs PCB"]
    assert [i["text"] for i in body["interests"]] == ["Robotics"]
    assert body["constraints"] == [{**body["constraints"][0], "text": "Father wants medicine", "sensitive": True}]
    assert [m["text"] for m in body["memories"]] == ["Built a robot"]
    assert body["recent_sessions"][0]["summary"] == "Discussed streams."
    assert body["recent_sessions"][0]["happened"] == [], "what the modules recorded, beside the summary"


def test_one_item_can_be_deleted_but_not_someone_elses(client, db_session):
    headers, asha = signup(client, db_session)
    other_headers, ravi = signup(client, db_session, "ravi@example.com")
    fill(db_session, asha)
    memory_id = db_session.query(MemoryItem).one().id
    assert client.delete(f"/api/student/memory/memory/{memory_id}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/student/memory/memory/{memory_id}", headers=headers).json() == {"deleted": {"memory_items": 1}}
    assert db_session.query(MemoryItem).count() == 0
    assert db_session.query(DataRequest).filter_by(kind="delete_memory").one().detail == {"id": memory_id}
    assert client.delete("/api/student/memory/password/1", headers=headers).status_code == 404


def test_forgetting_everything_keeps_the_permission(client, db_session):
    headers, asha = signup(client, db_session)
    fill(db_session, asha)
    deleted = client.delete("/api/student/memory", headers=headers).json()["deleted"]
    assert deleted["memory_items"] == 1 and deleted["counselling_threads"] == 1 and deleted["student_events"] == 2
    body = client.get("/api/student/memory", headers=headers).json()
    assert body["enabled"] is True and body["threads"] == [] and body["memories"] == []


def test_the_journey_reads_as_sentences_newest_first(client, db_session):
    headers, asha = signup(client, db_session)
    fill(db_session, asha)
    events = client.get("/api/student/timeline", headers=headers).json()
    assert [e["description"] for e in events] == ["Decided: PCM vs PCB", "New interest: Robotics"]
    assert events[0]["reason"] == "Chose PCM"


def test_where_the_counselling_stands(client, db_session):
    headers, asha = signup(client, db_session)
    fill(db_session, asha)
    state = client.get("/api/counselling/current-state", headers=headers).json()
    assert state["current_counselling_topic"] == "PCM vs PCB" and state["open_questions"] == ["Talk to father"]
    assert client.get("/api/counselling/history", headers=headers).json()[0]["summary"] == "Discussed streams."


def test_without_permission_the_state_is_empty(client, db_session):
    headers, asha = signup(client, db_session)
    fill(db_session, asha)
    consent.decide(db_session, asha, consent.LONG_TERM_MEMORY, False)
    assert client.get("/api/counselling/current-state", headers=headers).json() == {}


def test_a_topic_can_be_parked_or_closed_by_its_owner_only(client, db_session):
    headers, asha = signup(client, db_session)
    other_headers, _ = signup(client, db_session, "ravi@example.com")
    thread = fill(db_session, asha)
    url = f"/api/counselling/threads/{thread.id}"
    assert client.patch(url, json={"status": "parked"}, headers=other_headers).status_code == 404
    assert client.patch(url, json={"status": "parked"}, headers=headers).json()["status"] == "parked"
    assert client.patch(url, json={"status": "deleted"}, headers=headers).status_code == 422
    assert [t["status"] for t in client.get("/api/counselling/threads", headers=headers).json()] == ["parked"]
