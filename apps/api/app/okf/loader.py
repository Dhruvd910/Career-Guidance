"""OKF bundle → the facts tables (the bundle is canonical; this keeps the database in step).

Loading is idempotent: the same bundle loaded twice changes nothing. A value the bundle no longer
says (a reviewer rejected it, a newer read dropped it, the file was deleted) is withdrawn — kept
for history, not shown. After loading, each college's cached coordinates and website follow its
current facts. Each load is recorded with the bundle commit it read, so the next one only reads
the files changed since.

    python -m app.okf.loader [--all]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.facts import store
from app.models.college import College
from app.models.exam import Exam
from app.models.facts import Fact, OkfLoad
from app.okf import bundle
from app.okf.facts import in_scope, verifications, when


def bundle_root() -> Path:
    return Path(get_settings().okf_bundle_path)


def _entity_id(db: Session, entity: dict) -> int | None:
    if entity.get("type") == "college":
        rows = db.execute(select(College.id, College.state).where(College.canonical_name == entity.get("name"))).all()
        if len(rows) > 1 and entity.get("state"):
            rows = [r for r in rows if r.state == entity["state"]]
        return rows[0].id if len(rows) == 1 else None
    if entity.get("type") == "exam":
        row = db.execute(select(Exam.id).where((Exam.name == entity.get("name")) | (Exam.code == entity.get("name")))).first()
        return row.id if row else None
    return None


def _withdraw(db: Session, entity_type: str, entity_id: int, cid: str, keep: set[tuple]) -> int:
    gone = 0
    for fact in db.execute(select(Fact).where(Fact.entity_type == entity_type, Fact.entity_id == entity_id,
                                              Fact.superseded_by.is_(None), Fact.status != "withdrawn")).scalars():
        if in_scope(cid, fact.attribute, fact.academic_year) and \
                (fact.attribute, fact.academic_year, fact.document.source_id) not in keep:
            fact.status = "withdrawn"
            gone += 1
            store.reconcile(db, entity_type, entity_id, fact.attribute, fact.academic_year)
    return gone


def load_concept(db: Session, concept: bundle.Concept, problems: list[str]) -> tuple[int, tuple[str, int] | None]:
    """Loads one concept file; returns (values loaded, the entity it was about)."""
    maya = concept.meta.get("maya") or {}
    entity = maya.get("entity")
    if not entity:
        return 0, None  # a concept MAYA didn't write: tolerated, as OKF requires
    entity_id = _entity_id(db, entity)
    if entity_id is None:
        problems.append(f"{concept.id}: no {entity.get('type')} called {entity.get('name')!r}")
        return 0, None
    sources = {s["id"]: s for s in concept.meta.get("sources") or []}
    keep: set[tuple] = set()
    loaded = 0
    for f in maya.get("facts") or []:
        s = sources.get(f.get("source"))
        if s is None:
            problems.append(f"{concept.id}: {f.get('attribute')} cites a source that isn't listed ({f.get('source')})")
            continue
        try:
            publisher = str(s.get("author", "")).removeprefix("org:") or s["resource"]
            src = store.source(db, publisher, s.get("publisher") or publisher, int(s["tier"]))
            doc = store.document(db, src, s["resource"], s.get("title") or s["resource"], when(s.get("retrieved_at")),
                                 sha256=s.get("sha256"), parse_status=s.get("parse", "reference"),
                                 entity_refs=[f"{entity['type']}:{entity_id}"])
            checks = verifications(f)
            human = any(str(v["by"]).startswith("human:") for v in checks)
            migrated = any(str(v["by"]).startswith("process:maya-migration") for v in checks)
            latest = max((when(v["at"]) for v in checks), default=None)
            store.record(db, entity["type"], entity_id, f["attribute"], f.get("value"), document=doc,
                         academic_year=f.get("academic_year"), unit=f.get("unit"), locator=f.get("locator"),
                         quote=f.get("quote"), verified_by="human" if human else ("migration" if migrated else "auto"),
                         status=f.get("status", "verified"),
                         flags=f.get("flags") or (["waiting for review"] if f.get("status") == "flagged" else []),
                         now=latest or doc.retrieved_at)
            keep.add((f["attribute"], f.get("academic_year"), src.id))
            loaded += 1
        except (KeyError, ValueError, TypeError) as e:
            problems.append(f"{concept.id}: {f.get('attribute')}: {e}")
    _withdraw(db, entity["type"], entity_id, concept.id, keep)
    if entity["type"] == "college" and concept.type == "College":
        db.get(College, entity_id).aliases = list(entity.get("aliases") or [])
    return loaded, (entity["type"], entity_id)


def _cache(db: Session, college_id: int) -> None:
    college = db.get(College, college_id)
    now = store.current(db, "college", college_id, attributes=["location.coordinates", "location.website"])
    point = (now.get("location.coordinates") or {}).get("value") or {}
    college.latitude, college.longitude = point.get("lat"), point.get("lng")
    site = (now.get("location.website") or {}).get("value") or {}
    college.official_website = site.get("url") if isinstance(site, dict) else None


def _old_entity(root: Path, since: str, cid: str) -> dict | None:
    shown = subprocess.run(["git", "show", f"{since}:{cid}.md"], cwd=root, capture_output=True, text=True, check=False)
    if shown.returncode != 0:
        return None
    return (bundle.parse(shown.stdout, cid).meta.get("maya") or {}).get("entity")


def load(db: Session, root: Path | None = None, everything: bool = False) -> OkfLoad:
    root = root or bundle_root()
    problems = bundle.check(root) if root.exists() else []
    last = db.execute(select(OkfLoad).order_by(OkfLoad.id.desc())).scalars().first()
    since = None if everything or last is None else last.commit
    changed = bundle.changed_since(root, since) if since else None
    if changed is None:
        concepts = list(bundle.concepts(root)) if root.exists() else []
        deleted: list[str] = []
    else:
        concepts = [c for c in (bundle.read(root, cid) for cid in changed) if c is not None]
        deleted = [cid for cid in changed if not bundle.path_of(root, cid).exists()]
    total, colleges = 0, set()
    for concept in concepts:
        n, who = load_concept(db, concept, problems)
        total += n
        if who and who[0] == "college":
            colleges.add(who[1])
    for cid in deleted:
        entity = _old_entity(root, since, cid)
        entity_id = _entity_id(db, entity) if entity else None
        if entity_id is not None:
            _withdraw(db, entity["type"], entity_id, cid, set())
            if entity["type"] == "college":
                colleges.add(entity_id)
    for college_id in colleges:
        _cache(db, college_id)
    run = OkfLoad(commit=bundle.head(root) if root.exists() else None, concepts=len(concepts) + len(deleted),
                  facts=total, problems=problems[:500])
    db.add(run)
    db.commit()
    return run


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        result = load(session, everything="--all" in sys.argv)
        print(f"loaded {result.facts} values from {result.concepts} concepts (bundle {result.commit or 'not a git repo'})")
        for p in result.problems[:50]:
            print("  problem:", p)
