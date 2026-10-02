"""Apply today's checks to what's already in the OKF bundle (after a check is tightened): a
facility or other text value read from a college's site whose quote is a bare menu word
("Hospital") isn't evidence, so it's taken out — the loader then withdraws it.

    python -m app.ingest.recheck
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ingest.publish import SECTIONS
from app.ingest.read import TEXT
from app.okf import bundle, loader
from app.okf.facts import Entity, _refresh


def weak(f: dict) -> bool:
    quote = (f.get("quote") or "").strip()
    return f["attribute"] in TEXT and (len(quote) < 12 or len(quote.split()) < 2)


def run(db: Session, root=None) -> dict:
    root = root or loader.bundle_root()
    log, removed = [], 0
    with bundle.locked(root):
        for concept in list(bundle.concepts(root, "colleges")):
            facts = (concept.meta.get("maya") or {}).get("facts") or []
            sources = {s["id"]: s for s in concept.meta.get("sources") or []}
            gone = [f for f in facts if weak(f) and str(sources.get(f["source"], {}).get("author", "")).startswith("org:site-")]
            if not gone:
                continue
            for f in gone:
                facts.remove(f)
                log.append(f"**Withdrawn**: {f['attribute']} for [{concept.meta['maya']['entity']['name']}](/{concept.id}.md) — "
                           f"its quote ({f.get('quote')!r}) is a menu word, not evidence")
            removed += len(gone)
            entity = concept.meta["maya"]["entity"]
            _refresh(concept, Entity(**{k: (tuple(v) if k == "aliases" else v) for k, v in entity.items()}))
            bundle.write(root, concept)
        if removed:
            bundle.write_indexes(root, SECTIONS)
            bundle.append_log(root, log, datetime.now(timezone.utc).date())
            bundle.commit(root, f"Recheck: {removed} values withdrawn under today's checks")
            loader.load(db, root)
    return {"withdrawn": removed}


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        print(run(session))
