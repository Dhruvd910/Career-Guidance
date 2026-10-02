"""Facts from each college's own official website (docs/design/15-phase6-plan.md, Step 5).

For every college with a confirmed website: crawl it for the pages and PDFs about fees, hostel
and mess, the health centre, admissions and the campus; read the most relevant ones (at most six)
with the extraction model, one at a time; keep the values that survive the checks in app/ingest/
read.py. Where the site says nothing about tuition, the hostel or a medical facility, that's
recorded too — "not available on the official website", with how many pages were looked at.

    python -m app.ingest.college_facts [--limit N] [--all]
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.facts import store
from app.ingest import read as reading
from app.ingest.crawl import crawl
from app.ingest.fetch import Fetcher
from app.ingest.locations import NATIONAL
from app.ingest.publish import college_entity, publish
from app.ingest.text import page_images
from app.models.college import College
from app.okf.facts import QUOTE_CHECK, Document, Value, slug

MUST_SAY = ("fee.tuition.annual", "fee.hostel.annual", "facility.medical")
READS = ("fee.", "facility.", "location.address", "placement.")  # what a site read produces (and replaces)
ACADEMIC_YEAR = "2026-27"


def site_of(db: Session, college: College) -> str | None:
    website = store.current(db, "college", college.id, attributes=["location.website"]).get("location.website")
    if website and website["status"] == "verified" and website["source"]["tier"] == 2:
        return website["value"]["url"]
    return None


def values_for(db: Session, fetcher: Fetcher, college: College, usage: reading.Usage, max_docs: int = 6,
               reader=reading.read) -> tuple[list[Value], list[str]]:
    home = site_of(db, college)
    if home is None:
        return [], ["no confirmed official website"]
    pages, problems = crawl(fetcher, home)
    model = get_settings().extraction_model
    publisher = (f"site-{slug(college.canonical_name)}", f"{college.canonical_name} (official website)", 2)
    place = ", ".join(x for x in (college.city, college.state) if x)
    chosen: dict[tuple, tuple[int, Value]] = {}
    for rank, page in enumerate(pages[:max_docs]):
        images = page_images(page.fetched.storage_path) if page.extracted.scanned and page.fetched.storage_path else None
        try:
            reads, _ = reader(college.canonical_name, place, page.extracted.title, page.url, page.extracted, usage, images)
        except Exception as e:  # one bad call shouldn't lose the rest of the college
            problems.append(f"{page.url}: couldn't be read ({type(e).__name__}: {str(e)[:120]})")
            continue
        doc = Document(*publisher, page.url, page.extracted.title or page.via or page.url, page.fetched.retrieved_at,
                       sha256=page.fetched.sha256, parse="scanned" if page.extracted.scanned else "text")
        for r in reads:
            value = Value(r.attribute, r.value, doc, r.academic_year, locator=f"page {r.page}" if r.page else page.via or None,
                          quote=r.quote, flags=r.flags, generated_by=f"maya-extractor/{model}", verified_by=QUOTE_CHECK,
                          at=page.fetched.retrieved_at)
            key = (r.attribute, r.academic_year)
            better = key not in chosen or (chosen[key][1].flags and not r.flags)
            if better:
                chosen[key] = (rank, value)
    values = [v for _, v in chosen.values()]
    said = {v.attribute for v in values}
    if pages:
        first = pages[0]
        home_doc = Document(*publisher, home, f"{college.canonical_name} official website", first.fetched.retrieved_at,
                            sha256=first.fetched.sha256, parse="text")
        for attribute in MUST_SAY:
            if attribute not in said:
                year = ACADEMIC_YEAR if attribute.startswith("fee.") else None
                values.append(Value(attribute, None, home_doc, year,
                                    locator=f"not found on the official website (looked at {len(pages)} relevant pages)",
                                    generated_by=f"maya-extractor/{model}", verified_by=QUOTE_CHECK,
                                    at=first.fetched.retrieved_at))
    else:
        problems.append("no relevant pages found on the site")
    return values, problems


def run(db: Session, fetcher: Fetcher, root=None, only_national: bool = True, limit: int | None = None,
        batch: int = 5, reader=reading.read, progress=print) -> dict:
    colleges = [c for c in db.execute(select(College).order_by(College.id)).scalars()
                if (not only_national or c.college_type in NATIONAL) and site_of(db, c)]
    colleges = colleges[:limit] if limit else colleges
    usage = reading.Usage()
    report = {"colleges": len(colleges), "with_values": 0, "values": 0, "held": 0, "problems": {}, "usage": usage}
    pending, retractions = {}, {}
    for n, college in enumerate(colleges, start=1):
        values, problems = values_for(db, fetcher, college, usage, reader=reader)
        if problems:
            report["problems"][college.canonical_name] = problems[:10]
        real = [v for v in values if v.value is not None]
        if real:
            report["with_values"] += 1
        report["values"] += len(real)
        report["held"] += sum(1 for v in real if v.flags)
        if values:
            entity = college_entity(college)
            pending[entity] = values
            # this read replaces the site's last one (only when the site was actually read)
            retractions[entity] = (f"site-{slug(college.canonical_name)}", READS, "not found when the site was read again")
        if len(pending) >= batch or (n == len(colleges) and pending):
            result = publish(db, pending, f"Facts read from {len(pending)} official websites "
                                          f"({datetime.now(timezone.utc):%Y-%m-%d})", root, retractions=retractions)
            retractions = {}
            report.setdefault("bundle_problems", []).extend(result["problems"])
            pending = {}
            progress(f"{n}/{len(colleges)}: {report['values']} values ({report['held']} held for review), "
                     f"{usage.calls} model calls, ${usage.cost:.3f}")
    return report


if __name__ == "__main__":
    from app.core.db import SessionLocal

    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    with SessionLocal() as session, Fetcher(get_settings().source_store_path) as fetcher:
        result = run(session, fetcher, only_national="--all" not in args, limit=limit, progress=lambda m: print(m, flush=True))
    u = result["usage"]
    print(f"colleges {result['colleges']}, with values {result['with_values']}, values {result['values']}, "
          f"held {result['held']}; {u.calls} calls, {u.prompt_tokens}+{u.completion_tokens} tokens, ${u.cost:.3f}")
    for name, problems in list(result["problems"].items())[:40]:
        print(f"  {name}: {problems[:3]}")
