"""The nightly refresh (docs/design/15-phase6-plan.md, P6-4, P6-9): look again at what's due, and
at the colleges someone asked about. Run by the maya-refresh systemd user timer; never inside a
student's request.

In order:
1. colleges where someone tapped "Check for updates" (their website, then their documents);
2. the national documents and admission dates, once a week;
3. colleges whose fee facts are due (60 days), a few a night;
4. NIRF ranks and nearby places, when theirs are due.
Reading with the model stops at the nightly budget (REFRESH_BUDGET_USD, default $0.10).

    python -m app.ingest.refresh [--budget 0.10]
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.facts import freshness, store
from app.ingest import admissions, college_facts, documents, locations, nirf, read as reading, websites
from app.ingest.fetch import Fetcher
from app.models.college import College
from app.models.facts import Fact, RefreshRequest, Source, SourceDocument

WEEK = timedelta(days=7)


def _last_fetch(db: Session, publisher_keys: tuple[str, ...]) -> datetime | None:
    latest = db.execute(select(func.max(SourceDocument.retrieved_at)).join(Source)
                        .where(Source.key.in_(publisher_keys))).scalar()
    if latest is not None and latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return latest


def _due(db: Session, college: College, prefix: str, today) -> bool:
    facts = store.current(db, "college", college.id, prefix=prefix)
    return not facts or any(freshness.is_due(a, (v["verified_at"] and datetime.fromisoformat(v["verified_at"])), today)
                            for a, v in facts.items())


def run(db: Session, fetcher: Fetcher, root=None, budget: float = 0.10, per_night: int = 8, progress=print) -> dict:
    now = datetime.now(timezone.utc)
    today = now.date()
    report: dict = {"asked": 0, "documents": None, "dates": None, "fees": 0, "nirf": None, "places": None, "cost": 0.0}
    spent = reading.Usage()

    def reader(*args, **kwargs):  # every model call counts against tonight's budget
        if spent.cost >= budget:
            raise RuntimeError("tonight's reading budget is spent")
        usage = args[5]
        before = usage.cost
        out = reading.read(*args, **kwargs)
        spent.cost += usage.cost - before
        return out

    # 1. What people asked about.
    asked = db.execute(select(RefreshRequest).where(RefreshRequest.done_at.is_(None)).order_by(RefreshRequest.id)).scalars().all()
    for request in asked:
        college = db.get(College, request.college_id)
        websites_found, facts_report = None, None
        if not college_facts.site_of(db, college):
            value, why = websites.confirm(fetcher, college, (websites.candidates(db, college) or [""])[0]) \
                if websites.candidates(db, college) else (None, "no candidate address")
            if value:
                from app.ingest.publish import college_entity, publish

                publish(db, {college_entity(college): [value]}, f"Official website of {college.canonical_name} (asked for)", root)
            websites_found = why or "confirmed"
        if college_facts.site_of(db, college):
            values, problems = college_facts.values_for(db, fetcher, college, reading.Usage(), reader=reader)
            if values:
                from app.ingest.publish import college_entity, publish

                publish(db, {college_entity(college): values}, f"{college.canonical_name}, checked again (asked for)", root)
            facts_report = f"{sum(1 for v in values if v.value is not None)} values; {'; '.join(problems[:2])}"
        request.done_at, request.outcome = datetime.now(timezone.utc), (facts_report or websites_found or "nothing to check")[:300]
        report["asked"] += 1
    db.commit()

    # 2. National documents and admission dates, weekly.
    keys = tuple(p[0] for p in documents.PORTALS)
    last = _last_fetch(db, keys)
    if last is None or now - last >= WEEK:
        report["documents"] = documents.run(db, fetcher, root=root, embedder=_embedder())["documents"]
        report["dates"] = admissions.run(db, fetcher, root=root)["dates"]

    # 3. Fees that are due, a few colleges a night.
    due = [c for c in db.execute(select(College).order_by(College.id)).scalars()
           if c.college_type in locations.NATIONAL and college_facts.site_of(db, c) and _due(db, c, "fee.", today)]
    for college in due[:per_night]:
        try:
            values, _ = college_facts.values_for(db, fetcher, college, reading.Usage(), reader=reader)
        except RuntimeError:
            break
        if values:
            from app.ingest.publish import college_entity, publish

            publish(db, {college_entity(college): values}, f"{college.canonical_name}, fees checked again", root)
            report["fees"] += 1

    # 4. Rankings and nearby places, when due.
    rank = db.execute(select(func.max(Fact.verified_at)).where(Fact.attribute.startswith("ranking."))).scalar()
    if rank is None or freshness.is_due("ranking.nirf", rank, today):
        report["nirf"] = nirf.run(db, fetcher, root=root).get("ranked")
    report["places"] = locations.run(db, fetcher, root=root, limit=per_night, progress=lambda m: None)["placed"]
    report["cost"] = round(spent.cost, 4)
    progress(f"refresh: {report}")
    return report


def _embedder():
    from app.providers.registry import get_embedding_provider

    return get_embedding_provider()


if __name__ == "__main__":
    from app.core.config import get_settings
    from app.core.db import SessionLocal

    args = sys.argv[1:]
    budget = float(args[args.index("--budget") + 1]) if "--budget" in args else float(os.environ.get("REFRESH_BUDGET_USD", "0.10"))
    with SessionLocal() as session, Fetcher(get_settings().source_store_path, min_interval=4.0) as fetcher:
        run(session, fetcher, budget=budget, progress=lambda m: print(m, flush=True))
