"""Searching a student's memories by meaning — runs on SQLite and, with
MAYA_TEST_DATABASE_URL set, on PostgreSQL's pgvector."""

import pytest

from app.memory.store import search_memories
from app.models.memory import MemoryItem
from app.models.student import StudentProfile
from app.models.user import User
from tests.fakes import FakeEmbedding

EMBED = FakeEmbedding()


def student(db, name):
    user = User(email=f"{name}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    profile = StudentProfile(user_id=user.id, name=name, class_level=10)
    db.add(profile)
    db.flush()
    return profile


def remember(db, profile, text, **kw):
    item = MemoryItem(student_profile_id=profile.id, kind="fact", text=text,
                      embedding=EMBED.embed([text], "passage")[0], embed_model=EMBED.model_id, **kw)
    db.add(item)
    db.flush()
    return item


def find(db, profile, query, **kw):
    return [(item.text, round(sim, 3)) for item, sim in search_memories(db, profile.id, EMBED.embed([query], "query")[0], **kw)]


def test_the_closest_memories_come_first(db_session):
    asha = student(db_session, "asha")
    remember(db_session, asha, "likes python programming and robots")
    remember(db_session, asha, "plays cricket for the school team")
    remember(db_session, asha, "parents prefer biology and medicine")
    found = find(db_session, asha, "how is my python programming going", k=2)
    assert found[0][0] == "likes python programming and robots"
    assert found[0][1] > found[1][1]
    assert len(found) == 2


def test_one_student_never_finds_anothers_memories(db_session):
    asha, ravi = student(db_session, "asha"), student(db_session, "ravi")
    remember(db_session, ravi, "likes python programming")
    assert find(db_session, asha, "python programming") == []


def test_superseded_and_retracted_memories_are_not_found(db_session):
    asha = student(db_session, "asha")
    remember(db_session, asha, "wants to study medicine", status="superseded")
    remember(db_session, asha, "wants to study medicine maybe", status="retracted")
    assert find(db_session, asha, "study medicine") == []


def test_sensitive_memories_only_when_asked_for(db_session):
    asha = student(db_session, "asha")
    remember(db_session, asha, "family cannot afford private college fees", sensitivity="sensitive")
    assert find(db_session, asha, "college fees") == []
    assert find(db_session, asha, "college fees", include_sensitive=True)[0][0].startswith("family cannot")


def test_no_memories_yet(db_session):
    assert find(db_session, student(db_session, "new"), "anything") == []
