"""Writing a finished session into memory — and refusing anything the transcript doesn't support."""

import asyncio
import json

import pytest

from app.memory import consent
from app.memory.writer import write_session_memory
from app.models.chat import Conversation, Message
from app.models.memory import (
    CounsellingThread, MemoryItem, SessionSummary, StudentConstraint, StudentEvent, StudentGoal, StudentInterest,
    TurnAnalysis,
)
from app.models.student import StudentProfile
from app.models.user import User
from tests.fakes import FakeEmbedding, FakeLLM

GUARDIAN = {"name": "Sunita", "relationship": "mother", "contact": "98xxxxxx10"}


def student(db, name="asha", memory=True, signals=False):
    user = User(email=f"{name}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    profile = StudentProfile(user_id=user.id, name=name, class_level=10)
    db.add(profile)
    db.flush()
    if memory:
        consent.decide(db, profile, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    if signals:
        consent.decide(db, profile, consent.EMOTION_SIGNALS, True, GUARDIAN)
    return profile


def session(db, profile, *turns):
    """turns: (role, text) pairs. Returns the conversation and its message ids, in order."""
    conversation = Conversation(student_profile_id=profile.id)
    db.add(conversation)
    db.flush()
    ids = []
    for role, text in turns:
        message = Message(conversation_id=conversation.id, role=role, content=text)
        db.add(message)
        db.flush()
        ids.append(message.id)
    db.commit()
    return conversation, ids


TRANSCRIPT = (
    ("user", "Mujhe samajh nahi aa raha PCM lu ya PCB"),
    ("assistant", "Tumhe kaunse subjects pasand hain?"),
    ("user", "Computer bahut pasand hai, maine ek line follower robot banaya tha"),
    ("assistant", "Wah! Aur ghar pe kya sochte hain?"),
    ("user", "Papa chahte hain main doctor banu"),
)


def notes(ids, **overrides):
    """The model's notes on TRANSCRIPT; a test replaces any part with keyword arguments."""
    defaults = {
        "summary": lambda: "Discussed PCM vs PCB; likes computers; father prefers medicine.",
        "important_context": lambda: ["Class 10"],
        "decisions": lambda: [],
        "unresolved_questions": lambda: ["PCM or PCB"],
        "next_steps": lambda: ["Take the aptitude assessment"],
        "threads": lambda: [{"thread_id": None, "topic_key": "stream_choice", "title": "PCM vs PCB",
                             "decision_status": "undecided", "current_position": "Leaning PCM, father prefers PCB",
                             "open_questions": ["How to talk to father"], "next_step": "Aptitude assessment",
                             "evidence": {"messages": [ids[0]], "quote": "PCM lu ya PCB"}}],
        "interests": lambda: [{"label": "Computers / robotics", "change": "added", "strength": 0.8,
                               "evidence": {"messages": [ids[2]], "quote": "Computer bahut pasand hai"}}],
        "goals": lambda: [],
        "constraints": lambda: [{"kind": "family_expectation", "detail": "Father wants a medical career",
                                 "sensitive": True,
                                 "evidence": {"messages": [ids[4]], "quote": "Papa chahte hain main doctor banu"}}],
        "memories": lambda: [{"kind": "fact", "text": "Built a line follower robot",
                              "evidence": {"messages": [ids[2]], "quote": "maine ek line follower robot banaya tha"}}],
        "profile": lambda: None,
    }
    return json.dumps({key: overrides[key] if key in overrides else make() for key, make in defaults.items()})


def write(db, conversation, llm, embedder=FakeEmbedding()):
    return asyncio.run(write_session_memory(db, conversation.id, llm, embedder))


def test_a_session_becomes_a_summary_a_thread_an_interest_and_a_memory(db_session):
    asha = student(db_session)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    summary = write(db_session, conversation, FakeLLM(notes(ids)))

    assert summary.summary.startswith("Discussed PCM vs PCB") and summary.unresolved_questions == ["PCM or PCB"]
    thread = db_session.query(CounsellingThread).one()
    assert (thread.title, thread.decision_status, thread.opened_session_id) == ("PCM vs PCB", "undecided", conversation.id)
    assert summary.threads_touched == [thread.id]
    assert db_session.query(StudentInterest).one().label == "Computers / robotics"
    constraint = db_session.query(StudentConstraint).one()
    assert constraint.sensitivity == "sensitive", "family expectations are private"
    memory = db_session.query(MemoryItem).one()
    assert memory.text == "Built a line follower robot" and len(memory.embedding) == 384
    assert memory.evidence_message_ids == [ids[2]]
    events = [e.event_type for e in db_session.query(StudentEvent).order_by(StudentEvent.id)]
    assert events == ["CAREER_INTEREST_ADDED", "COUNSELLING_SESSION"]
    assert db_session.get(Conversation, conversation.id).status == "closed"


def test_a_quote_that_isnt_in_the_transcript_is_dropped(db_session):
    asha = student(db_session)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    made_up = [{"kind": "fact", "text": "Wants to study at IIT Bombay",
                "evidence": {"messages": [ids[2]], "quote": "I want IIT Bombay"}},
               {"kind": "fact", "text": "Built a line follower robot",
                "evidence": {"messages": [ids[2]], "quote": "line follower robot banaya"}}]
    write(db_session, conversation, FakeLLM(notes(ids, memories=made_up)))
    assert [m.text for m in db_session.query(MemoryItem)] == ["Built a line follower robot"]


def test_facts_about_the_student_must_quote_the_student(db_session):
    asha = student(db_session)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    from_maya = {"city": "Pune", "evidence": {"messages": [ids[1]], "quote": "kaunse subjects pasand"}}
    write(db_session, conversation, FakeLLM(notes(ids, profile=from_maya)))
    assert db_session.get(StudentProfile, asha.id).city is None


def test_a_stated_profile_change_is_applied_and_logged(db_session):
    asha = student(db_session)
    conversation, ids = session(db_session, asha, ("user", "I live in Pune and study about 10 hours a week"))
    stated = {"city": "Pune", "study_hours_per_week": 10, "evidence": {"messages": [ids[0]], "quote": "I live in Pune"}}
    write(db_session, conversation, FakeLLM(notes(ids, threads=[], interests=[], constraints=[], memories=[],
                                                  profile=stated)))
    profile = db_session.get(StudentProfile, asha.id)
    assert (profile.city, profile.study_hours_per_week) == ("Pune", 10)
    event = db_session.query(StudentEvent).filter_by(event_type="PROFILE_UPDATED").one()
    assert event.payload == {"city": "Pune", "study_hours_per_week": 10}


def test_without_consent_nothing_is_written_and_the_model_isnt_asked(db_session):
    asha = student(db_session, memory=False)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    llm = FakeLLM(notes(ids))
    assert write(db_session, conversation, llm) is None
    assert llm.seen == [] and db_session.query(SessionSummary).count() == 0


def test_writing_the_same_session_twice_writes_it_once(db_session):
    asha = student(db_session)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    llm = FakeLLM(notes(ids), notes(ids))
    first = write(db_session, conversation, llm)
    second = write(db_session, conversation, llm)
    assert first.conversation_id == second.conversation_id and len(llm.seen) == 1
    assert db_session.query(MemoryItem).count() == 1


def test_a_later_session_continues_the_thread_and_records_the_decision(db_session):
    asha = student(db_session)
    first, ids = session(db_session, asha, *TRANSCRIPT)
    write(db_session, first, FakeLLM(notes(ids)))
    thread = db_session.query(CounsellingThread).one()

    second, ids2 = session(db_session, asha, ("user", "Maine decide kar liya, main PCM hi lunga"))
    decided = [{"thread_id": thread.id, "topic_key": "stream_choice", "title": "PCM vs PCB",
                "status": "resolved", "decision_status": "decided", "current_position": "Chose PCM",
                "evidence": {"messages": [ids2[0]], "quote": "main PCM hi lunga"}}]
    llm = FakeLLM(notes(ids2, threads=decided, interests=[], constraints=[], memories=[]))
    write(db_session, second, llm)

    assert db_session.query(CounsellingThread).count() == 1, "continued, not duplicated"
    thread = db_session.get(CounsellingThread, thread.id)
    assert (thread.decision_status, thread.status, thread.last_session_id) == ("decided", "resolved", second.id)
    assert thread.resolved_at is not None
    assert db_session.query(StudentEvent).filter_by(event_type="DECISION_MADE").count() == 1
    assert f"thread_id {thread.id}: PCM vs PCB" in llm.seen[0][1]["content"], "the model was shown the open thread"


def test_another_students_thread_or_memory_cannot_be_touched(db_session):
    asha, ravi = student(db_session, "asha"), student(db_session, "ravi")
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    write(db_session, conversation, FakeLLM(notes(ids)))
    ashas_thread = db_session.query(CounsellingThread).one()
    ashas_memory = db_session.query(MemoryItem).one()

    other, ids2 = session(db_session, ravi, ("user", "Mujhe law mein interest hai"))
    hijack = notes(ids2, threads=[{"thread_id": ashas_thread.id, "topic_key": "x", "title": "Law",
                                   "evidence": {"messages": [ids2[0]], "quote": "law mein interest"}}],
                   memories=[{"kind": "fact", "text": "Interested in law", "supersedes": [ashas_memory.id],
                              "evidence": {"messages": [ids2[0]], "quote": "law mein interest"}}],
                   interests=[], constraints=[])
    write(db_session, other, FakeLLM(hijack))
    assert db_session.get(CounsellingThread, ashas_thread.id).title == "PCM vs PCB"
    assert db_session.get(MemoryItem, ashas_memory.id).status == "active"
    assert db_session.query(CounsellingThread).filter_by(student_profile_id=ravi.id).one().title == "Law"


def test_a_contradiction_supersedes_the_old_memory(db_session):
    asha = student(db_session)
    first, ids = session(db_session, asha, ("user", "Mujhe AI mein career banana hai"))
    write(db_session, first, FakeLLM(notes(ids, threads=[], interests=[], constraints=[], memories=[
        {"kind": "aspiration", "text": "Wants a career in AI", "evidence": {"messages": [ids[0]], "quote": "AI mein career"}}])))
    old = db_session.query(MemoryItem).one()

    second, ids2 = session(db_session, asha, ("user", "Ab AI nahi, cybersecurity karna hai"))
    write(db_session, second, FakeLLM(notes(ids2, threads=[], interests=[
        {"label": "AI", "change": "removed", "evidence": {"messages": [ids2[0]], "quote": "Ab AI nahi"}}],
        constraints=[], memories=[
        {"kind": "aspiration", "text": "Wants a career in cybersecurity instead of AI", "supersedes": [old.id],
         "evidence": {"messages": [ids2[0]], "quote": "cybersecurity karna hai"}}])))
    old = db_session.get(MemoryItem, old.id)
    new = db_session.query(MemoryItem).filter_by(status="active").one()
    assert old.status == "superseded" and old.superseded_by == new.id
    assert "cybersecurity" in new.text


def test_saying_the_same_thing_again_strengthens_the_memory_instead_of_copying_it(db_session):
    asha = student(db_session)
    for text in ("maine ek line follower robot banaya tha", "haan maine ek line follower robot banaya tha"):
        conversation, ids = session(db_session, asha, ("user", text))
        write(db_session, conversation, FakeLLM(notes(ids, threads=[], interests=[], constraints=[], memories=[
            {"kind": "fact", "text": "Built a line follower robot",
             "evidence": {"messages": [ids[0]], "quote": "line follower robot banaya"}}])))
    memory = db_session.query(MemoryItem).one()
    assert memory.salience > 0.5 and len(memory.evidence_message_ids) == 2


def test_notes_that_never_fit_the_shape_write_nothing(db_session):
    asha = student(db_session)
    conversation, _ids = session(db_session, asha, *TRANSCRIPT)
    llm = FakeLLM("Sure! Here are the notes: ...", '{"summary": "x", "threads": {"thread_id": null}}')
    assert write(db_session, conversation, llm) is None
    assert db_session.query(SessionSummary).count() == 0
    assert len(llm.seen) == 2, "one chance to correct itself, no more"
    assert "doesn't match the required shape" in llm.seen[1][-1]["content"]


def test_notes_corrected_on_the_second_try_are_written(db_session):
    asha = student(db_session)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    assert write(db_session, conversation, FakeLLM('{"summary": 5}', notes(ids))) is not None
    assert db_session.query(MemoryItem).count() == 1


def test_how_the_student_seemed_needs_its_own_permission(db_session):
    for name, signals in (("with", True), ("without", False)):
        profile = student(db_session, name, signals=signals)
        conversation, ids = session(db_session, profile, *TRANSCRIPT)
        db_session.add(TurnAnalysis(message_id=ids[0], student_profile_id=profile.id, emotion_signals=[
            {"signal": "confusion", "confidence": 0.8}, {"signal": "frustration", "confidence": 0.3}]))
        db_session.commit()
        summary = write(db_session, conversation, FakeLLM(notes(ids)))
        expected = [{"signal": "confusion", "confidence": 0.8}] if signals else []
        assert summary.student_state == expected, "weak readings are dropped; none without permission"
