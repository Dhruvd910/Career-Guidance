"""Loads the instrument files into the database — once per version, never silently changed.

Each file is validated (app/assessment/spec.py) and fingerprinted. A version that's already in
the database must have the same fingerprint: students' attempts point at it, so changing its
questions would change what their old answers meant. Change the content → bump the version
(and record it in instruments/lock.json, which a test checks). Older versions stay in the
database, retired, for the attempts that used them.

    python -m app.assessment.loader          # sync into the configured database
    python -m app.assessment.loader --lock   # after a deliberate version bump: re-record lock.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment.spec import Instrument
from app.models.assessment import AssessmentInstrument, AssessmentItem

INSTRUMENT_DIR = Path(__file__).parent / "instruments"
LOCK_FILE = INSTRUMENT_DIR / "lock.json"


class InstrumentChanged(RuntimeError):
    """A version already in use was edited in place."""


def fingerprint(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=1)
def instrument_files() -> dict[str, tuple[Instrument, str]]:
    """{key: (the latest version's spec, its fingerprint)} — one file per version, the newest wins."""
    latest: dict[str, tuple[Instrument, str]] = {}
    for path in sorted(INSTRUMENT_DIR.glob("*.v*.json")):
        raw = json.loads(path.read_text())
        spec = Instrument.model_validate(raw)
        if path.name != f"{spec.key}.v{spec.version}.json":
            raise ValueError(f"{path.name}: should be named {spec.key}.v{spec.version}.json")
        if spec.key not in latest or spec.version > latest[spec.key][0].version:
            latest[spec.key] = (spec, fingerprint(raw))
    return latest


def spec_for(key: str) -> Instrument:
    return instrument_files()[key][0]


def _insert(db: Session, spec: Instrument, sha: str) -> AssessmentInstrument:
    row = AssessmentInstrument(
        key=spec.key, version=spec.version, category=spec.category, title=spec.title.model_dump(),
        scoring_method=spec.scoring_method, est_minutes=spec.est_minutes, content_sha=sha,
    )
    row.items = [
        AssessmentItem(key=item.key, sort=n, item_type=item.type, form=item.form, difficulty=item.difficulty,
                       content=item.model_dump(exclude_none=True))
        for n, item in enumerate(spec.items)
    ]
    db.add(row)
    return row


def sync_instruments(db: Session) -> dict[str, AssessmentInstrument]:
    """Makes sure the current version of every instrument is in the database; returns
    {key: its row}. Cheap when nothing changed (one small query)."""
    rows = {(r.key, r.version): r for r in db.execute(select(AssessmentInstrument)).scalars()}
    current: dict[str, AssessmentInstrument] = {}
    changed = False
    for key, (spec, sha) in instrument_files().items():
        row = rows.get((key, spec.version))
        if row is None:
            row = _insert(db, spec, sha)
            changed = True
        elif row.content_sha != sha:
            raise InstrumentChanged(
                f"{spec.ref} is already in use but its file has changed — bump its version instead of editing it")
        current[key] = row
        for (other_key, version), other in rows.items():
            if other_key == key and version != spec.version and other.status != "retired":
                other.status = "retired"
                changed = True
    if changed:
        db.commit()
    return current


def write_lock() -> None:
    lock = {spec.ref: sha for spec, sha in instrument_files().values()}
    LOCK_FILE.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    if "--lock" in sys.argv:
        write_lock()
        print(f"Recorded {LOCK_FILE.name}.")
    else:
        from app.core.db import SessionLocal

        with SessionLocal() as session:
            synced = sync_instruments(session)
            print("Instruments: " + ", ".join(f"{k}@{r.version}" for k, r in synced.items()))
