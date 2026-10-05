"""The nightly refresh (docs/design/15-phase6-plan.md, P6-4, P6-9): look again at what's due, and
at the colleges someone asked about. Run by the maya-refresh systemd user timer; never inside a
student's request.

In order:
1. colleges where someone tapped "Check for updates" (their website, then their documents);
2. the national documents and admission dates, once a week (within the same budget);
3. colleges whose fee facts are due (60 days), a few a night, longest-unvisited first — a college
   just looked at waits (14 days if nothing could be read), so failures aren't paid for nightly;
4. NIRF ranks and nearby places, when theirs are due.
Reading with the model stops at the nightly budget (REFRESH_BUDGET_USD, default $0.10), and a document
unchanged since it was last read isn't paid for again (app/ingest/read.py).

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
from app.models.facts import Fact, RefreshAttempt, RefreshRequest, Source, SourceDocument

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


# A read that found nothing (a site down, a layout the reader couldn't use) is tried again after this;
# one that found values waits for the topic's own refresh interval.
RETRY_EMPTY_AFTER = timedelta(days=14)


def _last_attempt(db: Session, college: College, prefix: str) -> RefreshAttempt | None:
    return db.execute(select(RefreshAttempt).where(RefreshAttempt.college_id == college.id, RefreshAttempt.topic == prefix)
                      .order_by(RefreshAttempt.attempted_at.desc()).limit(1)).scalar_one_or_none()


def _resting(attempt: RefreshAttempt | None, prefix: str, now: datetime) -> bool:
    """Looked at recently enough that tonight would only pay to read the same pages again."""
    if attempt is None:
        return False
    at = attempt.attempted_at if attempt.attempted_at.tzinfo else attempt.attempted_at.replace(tzinfo=timezone.utc)
    wait = timedelta(days=freshness.policy_for(prefix).refresh_days) if attempt.found else RETRY_EMPTY_AFTER
    return now - at < wait


def run(db: Session, fetcher: Fetcher, root=None, budget: float = 0.10, per_night: int = 8, progress=print) -> dict:
    now = datetime.now(timezone.utc)
    today = now.date()
    report: dict = {"asked": 0, "documents": None, "dates": None, "fees": 0, "nirf": None, "places": None, "cost": 0.0}
    spent = reading.Usage()

    def reader(*args, **kwargs):  # every model call counts against tonight's budget
        if spent.cost >= budget:
            raise RuntimeError("tonight's reading budget is spent")
        usage = args[5]
        before, reused = usage.cost, usage.reused
        out = reading.read(*args, **kwargs)
        spent.cost += usage.cost - before
        spent.reused += usage.reused - reused
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
        report["dates"] = admissions.run(db, fetcher, root=root, usage=spent, budget=budget)["dates"]  # within tonight's budget

    # 3. Fees that are due, a few colleges a night: the longest-unvisited first, and none looked at
    #    too recently (see RefreshAttempt).
    due = []
    for c in db.execute(select(College).order_by(College.id)).scalars():
        if c.college_type in locations.NATIONAL and college_facts.site_of(db, c) and _due(db, c, "fee.", today):
            last = _last_attempt(db, c, "fee.")
            if not _resting(last, "fee.", now):
                due.append((last.attempted_at if last else None, c))
    due.sort(key=lambda pair: (pair[0] is not None, pair[0] or now))
    for _, college in due[:per_night]:
        if spent.cost >= budget:
            break
        before = spent.cost
        try:
            values, _ = college_facts.values_for(db, fetcher, college, reading.Usage(), reader=reader)
        except RuntimeError:
            break
        if not values and spent.cost >= budget:
            break  # cut off by the budget, not a real look: it stays due for tomorrow
        db.add(RefreshAttempt(college_id=college.id, topic="fee.", attempted_at=datetime.now(timezone.utc),
                              found=len(values), cost=round(spent.cost - before, 5)))
        db.commit()
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
    report["reused"] = spent.reused  # documents unchanged since they were last read: not paid for again
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
