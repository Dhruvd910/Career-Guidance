"""Reviewing what the checks held back (docs/design/15-phase6-plan.md, P6-2): values flagged for
review, and official sources that disagree. Decisions are made in the OKF bundle — recorded as
`human:<you>` in the value's `verified` list, or the value removed — then committed and loaded.

    python -m app.ingest.review                      # what's waiting
    python -m app.ingest.review approve N --by dhruv [--note "…"]
    python -m app.ingest.review reject N --by dhruv --note "that's the semester figure"
    python -m app.ingest.review edit N --by dhruv --value '{"amount": 5000, "per": "once", "applies_to": "general"}'
    python -m app.ingest.review pick N --by dhruv    # in a conflict: this one is right
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.facts import describe
from app.facts.store import same_value
from app.ingest.publish import SECTIONS
from app.models.facts import OFFICIAL_TIERS
from app.okf import bundle, loader
from app.okf.facts import decide


def waiting(root: Path) -> list[dict]:
    """Every value waiting for a person: flagged ones, and each side of a disagreement."""
    out = []
    for concept in bundle.concepts(root, "colleges") if (root / "colleges").exists() else []:
        facts = (concept.meta.get("maya") or {}).get("facts") or []
        sources = {s["id"]: s for s in concept.meta.get("sources") or []}
        name = concept.meta["maya"]["entity"]["name"]
        for f in facts:
            reason = None
            if f.get("status") == "flagged":
                reason = "; ".join(f.get("flags") or ["flagged"])
            elif f.get("status") == "verified" and sources.get(f["source"], {}).get("tier") in OFFICIAL_TIERS:
                rivals = [g for g in facts if g is not f and g["attribute"] == f["attribute"] and g.get("status") == "verified"
                          and g.get("academic_year") == f.get("academic_year")
                          and sources.get(g["source"], {}).get("tier") in OFFICIAL_TIERS and not same_value(f["value"], g["value"])]
                if rivals:
                    reason = "official sources disagree"
            if reason:
                s = sources.get(f["source"], {})
                out.append({"concept": concept.id, "college": name, "attribute": f["attribute"],
                            "academic_year": f.get("academic_year"), "source_id": f["source"],
                            "value": describe.value_text(f["attribute"], f.get("value")), "why": reason,
                            "from": f"{s.get('publisher')} — {s.get('title')} ({s.get('resource')})",
                            "quote": f.get("quote"), "where": f.get("locator")})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review values held back by MAYA's checks.")
    parser.add_argument("decision", nargs="?", choices=["approve", "reject", "edit", "pick"])
    parser.add_argument("number", nargs="?", type=int)
    parser.add_argument("--by", default=None)
    parser.add_argument("--note", default=None)
    parser.add_argument("--value", default=None)
    args = parser.parse_args(argv)
    root = loader.bundle_root()
    items = waiting(root)
    if not args.decision:
        if not items:
            print("Nothing is waiting for review.")
        for n, item in enumerate(items, start=1):
            print(f"{n}. {item['college']} — {describe.name(item['attribute'])} {item['academic_year'] or ''}: "
                  f"{item['value']}\n   why: {item['why']}\n   from: {item['from']}"
                  + (f", {item['where']}" if item["where"] else "") + (f"\n   quote: “{item['quote']}”" if item["quote"] else ""))
        return 0
    if not args.by or not args.number or not 1 <= args.number <= len(items):
        parser.error("say which item (its number from the list) and who you are (--by)")
    item = items[args.number - 1]
    value = json.loads(args.value) if args.value else None
    from app.core.db import SessionLocal

    with bundle.locked(root), SessionLocal() as db:
        log = decide(root, item["concept"], item["attribute"], item["academic_year"], item["source_id"], args.decision,
                     args.by, note=args.note, value=value)
        bundle.write_indexes(root, SECTIONS)
        bundle.append_log(root, log, datetime.now(timezone.utc).date())
        bundle.commit(root, f"Review: {args.decision} {item['college']} {item['attribute']} (human:{args.by})")
        loader.load(db, root)
    print(*log, sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
