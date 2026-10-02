"""The end of every ingest job: values → the OKF bundle (canonical) → indexes, log, one git
commit → the database, loaded from the bundle. Also builds the bundle's entity for a college."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.college import College
from app.okf import bundle, loader
from app.okf.aliases import aliases_for
from app.okf.facts import Entity, Value, upsert

SECTIONS = {"colleges": "Colleges, one folder each", "exams": "Entrance exams", "documents": "Official documents"}


def college_entity(college: College) -> Entity:
    return Entity("college", college.canonical_name, college.state, college.city, college.college_type,
                  tuple(aliases_for(college.canonical_name, college.city)))


def publish(db: Session, values: dict[Entity, list[Value]], message: str, root: Path | None = None,
            now: datetime | None = None) -> dict:
    root = root or loader.bundle_root()
    now = now or datetime.now(timezone.utc)
    with bundle.locked(root):
        bundle.ensure_repo(root)
        log: list[str] = []
        for entity, vals in values.items():
            log += upsert(root, entity, vals, now=now)
        bundle.write_indexes(root, SECTIONS)
        bundle.append_log(root, log, now.date())
        problems = bundle.check(root)
        commit = bundle.commit(root, message)
        run = loader.load(db, root)
    return {"changes": len(log), "commit": commit, "loaded": run.facts, "problems": problems + list(run.problems)}
