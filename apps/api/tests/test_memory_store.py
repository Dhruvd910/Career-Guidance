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


def test_recent_and_important_memories_win_among_the_equally_relevant(db_session):
    """Spec §7: relevance + recency + importance. Two memories about the same thing: the newer one, or
    the one said more than once, comes first — but never ahead of a clearly more relevant one."""
    from datetime import datetime, timedelta, timezone

    asha = student(db_session, "asha")
    now = datetime.now(timezone.utc)
    old = remember(db_session, asha, "wants to study medicine", created_at=now - timedelta(days=400))
    new = remember(db_session, asha, "wants to study medicine", created_at=now - timedelta(days=2))
    remember(db_session, asha, "plays cricket for the school team", created_at=now, salience=1.0)
    found = [m for m, _ in search_memories(db_session, asha.id, EMBED.embed(["study medicine"], "query")[0], k=3, now=now)]
    assert found[:2] == [new, old], "same meaning: the recent one first"
    assert found[2].text.startswith("plays cricket"), "recent and important, but not about this: still last"

    new.created_at = old.created_at
    old.salience = 0.9  # said again, more than once
    found = [m for m, _ in search_memories(db_session, asha.id, EMBED.embed(["study medicine"], "query")[0], k=2, now=now)]
    assert found == [old, new], "same meaning and age: the one that matters more first"
