"""What students say and what MAYA notes about them reach the database only encrypted (spec §28,
§30); the app reads them as before, and rows written before encryption still read."""

from sqlalchemy import text

from app.core.crypto import PREFIX, decrypt, encrypt
from app.models.chat import Conversation, Message
from app.models.memory import Consent, MemoryItem, StudentConstraint
from scripts import encrypt_existing
from tests.test_memory_writer import student


def raw(db, sql):
    return db.execute(text(sql)).scalar()


def test_sensitive_columns_are_ciphertext_in_the_database(db_session):
    asha = student(db_session)  # with a guardian's consent: their contact is stored too
    talk = Conversation(student_profile_id=asha.id)
    db_session.add(talk)
    db_session.flush()
    db_session.add_all([
        Message(conversation_id=talk.id, role="user", content="Papa wants me to do PCB but we can't afford coaching"),
        MemoryItem(student_profile_id=asha.id, kind="concern", text="Family can't afford coaching", sensitivity="sensitive"),
        StudentConstraint(student_profile_id=asha.id, kind="financial", detail="Coaching fees are a worry", sensitivity="sensitive"),
    ])
    db_session.commit()
    for sql in ("SELECT content FROM messages", "SELECT text FROM memory_items", "SELECT detail FROM student_constraints"):
        stored = raw(db_session, sql)
        assert stored.startswith(PREFIX) and "coaching" not in stored.lower(), sql
    assert "Sunita" not in str(raw(db_session, "SELECT guardian FROM consents"))

    db_session.expire_all()
    assert db_session.query(Message).one().content.startswith("Papa wants me")
    assert db_session.query(MemoryItem).one().text == "Family can't afford coaching"
    assert db_session.query(Consent).first().guardian["name"] == "Sunita"


def test_old_plain_rows_still_read_and_the_script_encrypts_them_once(db_session):
    asha = student(db_session, memory=False)
    db_session.execute(text("INSERT INTO memory_items (student_profile_id, kind, text, salience, confidence, sensitivity, "
                            "status, evidence_message_ids, created_at, updated_at) VALUES (:p, 'fact', 'built a robot', 0.5, "
                            "0.8, 'normal', 'active', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"p": asha.id})
    db_session.commit()
    assert db_session.query(MemoryItem).one().text == "built a robot", "written before encryption: still readable"

    assert encrypt_existing.run(db_session)["memory_items.text"] == 1
    assert raw(db_session, "SELECT text FROM memory_items").startswith(PREFIX)
    assert encrypt_existing.run(db_session)["memory_items.text"] == 0, "already encrypted: left alone"
    db_session.expire_all()
    assert db_session.query(MemoryItem).one().text == "built a robot"

    encrypt_existing.run(db_session, undo=True)
    assert raw(db_session, "SELECT text FROM memory_items") == "built a robot"


def test_encrypting_twice_or_decrypting_plain_text_changes_nothing():
    once = encrypt("हिंदी में भी")
    assert encrypt(once) == once and decrypt(once) == "हिंदी में भी" and decrypt("plain") == "plain"
