"""What MAYA brings to mind before a reply."""

from datetime import datetime, timedelta, timezone

import pytest

from app.ai import orchestrator
from app.memory import consent, retrieval
from app.memory.retrieval import build_memory_context
from app.models.chat import Conversation
from app.models.memory import (
    CounsellingThread, MemoryItem, SessionSummary, StudentConstraint, StudentEvent, StudentGoal, StudentInterest,
)
from tests.fakes import FakeEmbedding, FakeLLM
from tests.test_memory_writer import student

EMBED = FakeEmbedding()
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def word_overlap_threshold(monkeypatch):
    # The fake embedder scores by shared words, on a different scale from the real model.
    monkeypatch.setattr(retrieval, "SENSITIVE_MIN_SIMILARITY", 0.5)


def remember(db, profile, text, **kw):
    db.add(MemoryItem(student_profile_id=profile.id, kind="fact", text=text,
                      embedding=EMBED.embed([text], "passage")[0], **kw))


def a_student_with_history(db, name="asha"):
    profile = student(db, name)
    conversation = Conversation(student_profile_id=profile.id)
    db.add(conversation)
    db.flush()
    db.add_all([
        CounsellingThread(student_profile_id=profile.id, topic_key="stream_choice", title="PCM vs PCB",
                          decision_status="leaning", current_position="Leaning PCM", open_questions=["Talk to father"],
                          next_step="Aptitude assessment", last_touched_at=NOW - timedelta(days=3)),
        CounsellingThread(student_profile_id=profile.id, topic_key="old", title="Old settled topic", status="resolved"),
        SessionSummary(conversation_id=conversation.id, student_profile_id=profile.id,
                       summary="Discussed PCM vs PCB.", next_steps=["Take the aptitude assessment"],
                       created_at=NOW - timedelta(days=3)),
        StudentInterest(student_profile_id=profile.id, label="Computers"),
        StudentInterest(student_profile_id=profile.id, label="Painting", status="removed"),
        StudentGoal(student_profile_id=profile.id, title="Finish the aptitude assessment"),
        StudentConstraint(student_profile_id=profile.id, kind="location", detail="does not want to move away from Indore"),
        StudentConstraint(student_profile_id=profile.id, kind="family_expectation", sensitivity="sensitive",
                          detail="father wants a medical career"),
        StudentEvent(student_profile_id=profile.id, event_type="CAREER_INTEREST_ADDED", payload={"label": "Computers"},
                     occurred_at=NOW - timedelta(days=3)),
    ])
    remember(db, profile, "built a line follower robot")
    remember(db, profile, "plays cricket for the school team")
    remember(db, profile, "scared that father will be angry about not choosing medicine", sensitivity="sensitive")
    db.commit()
    return profile


def test_the_counselling_state_and_last_session_are_always_there(db_session):
    asha = a_student_with_history(db_session)
    text = build_memory_context(db_session, asha, "hello", EMBED, now=NOW)
    assert "PCM vs PCB — leaning; Leaning PCM Open: Talk to father. Next step: Aptitude assessment." in text
    assert "(last discussed 3 days ago)" in text and "Last session (3 days ago): Discussed PCM vs PCB." in text
    assert "Old settled topic" not in text, "resolved topics aren't open"
    assert "Interests: Computers" in text and "Painting" not in text
    assert "Goals: Finish the aptitude assessment" in text
    assert "does not want to move away from Indore (location)" in text
    assert "career interest added (Computers) 3 days ago" in text


def test_memories_are_chosen_by_meaning(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "MEMORIES", 1)
    asha = a_student_with_history(db_session)
    text = build_memory_context(db_session, asha, "how is my robot project going", EMBED, now=NOW)
    assert "built a line follower robot" in text and "cricket" not in text


def test_private_things_only_when_the_question_is_about_them(db_session):
    asha = a_student_with_history(db_session)
    unrelated = build_memory_context(db_session, asha, "how is my robot project going", EMBED, now=NOW)
    assert "father wants a medical career" not in unrelated and "scared that father" not in unrelated
    about_family = build_memory_context(db_session, asha, "my father wants a medical career", EMBED, now=NOW)
    assert "father wants a medical career (family_expectation)" in about_family
    about_fear = build_memory_context(db_session, asha, "I am scared my father will be angry", EMBED, now=NOW)
    assert "scared that father will be angry" in about_fear


def test_nothing_without_permission_or_history(db_session):
    asha = a_student_with_history(db_session)
    consent.decide(db_session, asha, consent.LONG_TERM_MEMORY, False)  # withdrawal also deletes it all
    assert build_memory_context(db_session, asha, "hello", EMBED, now=NOW) is None
    fresh = student(db_session, "fresh")
    assert build_memory_context(db_session, fresh, "hello", EMBED, now=NOW) is None


def test_another_students_memory_never_appears(db_session):
    a_student_with_history(db_session, "asha")
    ravi = student(db_session, "ravi")
    assert build_memory_context(db_session, ravi, "robot PCM computers father", EMBED, now=NOW) is None


def test_it_fits_the_budget(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "BUDGET_CHARS", 400)
    asha = a_student_with_history(db_session)
    assert len(build_memory_context(db_session, asha, "hello", EMBED, now=NOW)) <= 400


def test_without_embeddings_the_most_important_memories_still_come(db_session):
    asha = a_student_with_history(db_session)
    text = build_memory_context(db_session, asha, "anything", None, now=NOW)
    assert "built a line follower robot" in text and "scared" not in text


def test_the_reply_sees_what_she_remembers(client, db_session, monkeypatch):
    token = client.post("/api/auth/register", json={"email": "r@example.com", "password": "password123",
                                                    "name": "Asha", "class_level": 10}).json()["access_token"]
    from app.models.student import StudentProfile
    profile = db_session.query(StudentProfile).one()
    consent.decide(db_session, profile, consent.LONG_TERM_MEMORY, True,
                   {"name": "Sunita", "relationship": "mother", "contact": "x"})
    db_session.add(StudentInterest(student_profile_id=profile.id, label="Robotics"))
    db_session.commit()
    llm = FakeLLM("Let's talk robots.")
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)
    monkeypatch.setattr(orchestrator, "get_embedding_provider", lambda: EMBED)
    client.post("/api/ai/chat", json={"message": "What should I study?"}, headers={"Authorization": f"Bearer {token}"})
    system = [m["content"] for m in llm.seen[0] if m["role"] == "system"]
    assert system[1].startswith(retrieval.HEADER) and "Interests: Robotics" in system[1]
