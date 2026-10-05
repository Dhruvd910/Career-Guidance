"""One-off: encrypts what was written before students' words and MAYA's notes were encrypted
(app/core/crypto.py). Safe to run again — encrypted values are left alone. --decrypt turns them all
back into plain text (needed only before downgrading the migration that made room for them).

    python scripts/encrypt_existing.py [--decrypt]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.crypto import PREFIX, decrypt, encrypt  # noqa: E402

# table → (primary key, [(column, "text" | "json")])
ENCRYPTED = {
    "messages": ("id", [("content", "text"), ("generated_content", "text")]),
    "memory_items": ("id", [("text", "text")]),
    "student_constraints": ("id", [("detail", "text")]),
    "session_summaries": ("conversation_id", [("summary", "text")]),
    "turn_analyses": ("message_id", [("underlying_concerns", "json")]),
    "consents": ("id", [("guardian", "json")]),
}


def _converted(value, kind: str, undo: bool):
    """The new stored value, or None when this one needs no change."""
    if value is None:
        return None
    if kind == "text":
        if undo:
            return decrypt(value) if value.startswith(PREFIX) else None
        return None if value.startswith(PREFIX) else encrypt(value)
    data = json.loads(value) if isinstance(value, str) else value
    wrapped = isinstance(data, dict) and set(data) == {"enc1"}
    if undo:
        return json.dumps(json.loads(decrypt(data["enc1"])), ensure_ascii=False) if wrapped else None
    return None if wrapped else json.dumps({"enc1": encrypt(json.dumps(data, ensure_ascii=False))})


def run(db: Session, undo: bool = False) -> dict[str, int]:
    changed: dict[str, int] = {}
    for table, (key, columns) in ENCRYPTED.items():
        for column, kind in columns:
            n = 0
            for pk, value in db.execute(text(f"SELECT {key}, {column} FROM {table}")).all():
                new = _converted(value, kind, undo)
                if new is not None:
                    cast = "CAST(:v AS jsonb)" if kind == "json" and db.get_bind().dialect.name == "postgresql" else ":v"
                    db.execute(text(f"UPDATE {table} SET {column} = {cast} WHERE {key} = :k"), {"v": new, "k": pk})
                    n += 1
            changed[f"{table}.{column}"] = n
    db.commit()
    return changed


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        print(run(session, undo="--decrypt" in sys.argv))
