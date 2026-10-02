"""Admission dates from the official bulletins (docs/design/15-phase6-plan.md, Step 7).

The "Important Dates" of each indexed bulletin — when applications open and close, the exam, the
result, counselling — are read by the extraction model from its first pages and checked like
every other value: the dates must be in the quoted words, and the quote in the document. They're
facts about the exam (`exams/<exam>/admissions-<year>.md` in the bundle).

The next cycle's dates are often not out yet. Then that's recorded too — "not announced yet",
with when the portal was checked — so MAYA can say so and give last year's dates as last year's.

    python -m app.ingest.admissions
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.facts import store
from app.ingest import read as reading
from app.ingest.documents import PORTALS
from app.ingest.fetch import Fetcher
from app.ingest.publish import publish
from app.ingest.text import Extracted, contains, extract
from app.models.exam import Exam
from app.models.facts import SourceDocument
from app.okf.facts import QUOTE_CHECK, Document, Entity, Value

DATES = ("admission.application_window", "admission.exam_date", "admission.result_date", "admission.counselling")
PROMPT = """You read an official Indian entrance-exam or counselling document and pull out its key dates.
Return JSON only: {"dates": [ ... ]}. Each:
  {"attribute": "admission.application_window" | "admission.exam_date" | "admission.result_date" | "admission.counselling",
   "label": a short name, e.g. "Online application, session 1" or "Round 1 choice filling",
   "from": "YYYY-MM-DD", "to": "YYYY-MM-DD" or null for a single day,
   "exam_year": the year of the exam or counselling these dates are for, e.g. 2026,
   "quote": the exact words of the document that give these dates — copied character for character,
   "page": the page number}
Only dates the document states. Never guess or calculate. An empty list is a good answer."""
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _date_in(quote: str, d: date) -> bool:
    """Whether the quoted words show this date, in any of the usual ways (02.11.2025, 2 November 2025…)."""
    q = quote.lower()
    numeric = [f"{d.day:02d}.{d.month:02d}.{d.year}", f"{d.day}.{d.month}.{d.year}", f"{d.day:02d}/{d.month:02d}/{d.year}",
               f"{d.day:02d}-{d.month:02d}-{d.year}", f"{d.year}-{d.month:02d}-{d.day:02d}", f"{d.day:02d}.{d.month:02d}.{str(d.year)[2:]}"]
    if any(n in q for n in numeric):
        return True
    month = [m for m, i in MONTHS.items() if i == d.month][0]
    return bool(re.search(rf"\b0?{d.day}(st|nd|rd|th)?\s*(of\s+)?{month}[a-z]*\.?,?\s*({d.year})?", q)) or \
        bool(re.search(rf"\b{month}[a-z]*\.?\s+0?{d.day}(st|nd|rd|th)?\b", q))


def check(raw: dict, doc: Extracted) -> reading.Read | None:
    attribute, quote = raw.get("attribute"), str(raw.get("quote") or "").strip()
    if attribute not in DATES or not contains(doc.text, quote):
        return None
    try:
        start = date.fromisoformat(str(raw.get("from")))
        end = date.fromisoformat(str(raw["to"])) if raw.get("to") else None
    except ValueError:
        return None
    if not _date_in(quote, start) or (end and not _date_in(quote, end)) or (end and end < start):
        return None  # the dates aren't in the quoted words
    year = raw.get("exam_year") if isinstance(raw.get("exam_year"), int) else start.year
    value = {"from": start.isoformat(), "to": end.isoformat() if end else None, "label": str(raw.get("label") or "")[:120]}
    return reading.Read(attribute, value, f"{year}-{str(year + 1)[2:]}", quote, raw.get("page") if isinstance(raw.get("page"), int) else None)


def read_dates(doc: Extracted, title: str, url: str, usage: reading.Usage, pages: int = 15) -> list[reading.Read]:
    first = Extracted(doc.kind, doc.pages[:pages], doc.scanned, doc.title)
    messages = [{"role": "system", "content": PROMPT},
                {"role": "user", "content": f"Document: {title}\nAddress: {url}\n\n" + "\n\n".join(
                    f"--- page {n} ---\n{p}" for n, p in enumerate(first.pages, start=1))[:120_000]}]
    answer = reading.ask(messages, usage)
    reads = [r for r in (check(d, first) for d in answer.get("dates", []) if isinstance(d, dict)) if r]
    # Several windows for one attribute (sessions, rounds): keep each as its own value, by label.
    return reads


def run(db: Session, fetcher: Fetcher, root=None, next_cycle: int | None = None, reader=read_dates) -> dict:
    """Dates from every indexed bulletin; and, for the next cycle, whether its bulletin is out yet."""
    today = datetime.now(timezone.utc).date()
    next_cycle = next_cycle or (today.year + 1 if today.month >= 7 else today.year)
    exams = {f"exam:{e.code}": e for e in db.execute(select(Exam)).scalars()}
    usage, values, report = reading.Usage(), {}, {"dates": 0, "documents": 0, "next_cycle": next_cycle, "problems": []}
    for row in db.execute(select(SourceDocument).where(SourceDocument.superseded_by.is_(None))).scalars():
        about = [exams[a] for a in (row.entity_refs or []) if a in exams]
        if not about or row.source.tier != 3 or not row.sha256:
            continue
        raw = next(iter(sorted((fetcher.store / row.sha256[:2]).glob(f"{row.sha256}.*"))), None)
        if raw is None:
            continue
        doc = extract(raw.read_bytes(), row.url, "application/pdf" if raw.suffix == ".pdf" else "text/html", str(raw))
        try:
            reads = reader(doc, row.title, row.url, usage)
        except Exception as e:
            report["problems"].append(f"{row.title}: {type(e).__name__}: {str(e)[:100]}")
            continue
        report["documents"] += 1
        source = Document(row.source.key, row.source.name, row.source.tier, row.url, row.title, row.retrieved_at,
                          sha256=row.sha256, parse="text")
        for exam in about:
            entity = Entity("exam", exam.code)
            for r in reads:
                attribute = r.attribute if not r.value.get("label") else f"{r.attribute}.{_key(r.value['label'])}"
                values.setdefault(entity, []).append(Value(
                    attribute, r.value, source, r.academic_year, locator=f"page {r.page}" if r.page else None,
                    quote=r.quote, generated_by=f"maya-dates/{reading.get_settings().extraction_model}",
                    verified_by=QUOTE_CHECK, at=row.retrieved_at))
                report["dates"] += 1
    year = f"{next_cycle}-{str(next_cycle + 1)[2:]}"
    for key, publisher, tier, start, _words, about in PORTALS:
        for ref in about:
            exam = exams.get(ref)
            if exam is None or any(v.academic_year == year and v.value is not None
                                   for v in values.get(Entity("exam", exam.code), [])):
                continue
            home = fetcher.get(start)
            if not home.ok:
                continue
            values.setdefault(Entity("exam", exam.code), []).append(Value(
                "admission.application_window", None,
                Document(key, publisher, tier, home.final_url, f"{publisher} — home page", home.retrieved_at,
                         sha256=home.sha256, parse="text"),
                year, locator=f"no {next_cycle} dates on the official portal yet (checked {home.retrieved_at:%-d %b %Y})",
                generated_by="maya-dates/1", verified_by=QUOTE_CHECK, at=home.retrieved_at))
    if values:
        result = publish(db, values, f"Admission dates from the official bulletins ({report['dates']})", root)
        report["bundle_problems"] = result.pop("problems")
        report.update(result)
    report["usage"] = usage
    return report


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "date"


if __name__ == "__main__":
    from app.core.config import get_settings
    from app.core.db import SessionLocal

    with SessionLocal() as session, Fetcher(get_settings().source_store_path) as fetcher:
        result = run(session, fetcher)
    u = result["usage"]
    print(f"dates {result['dates']} from {result['documents']} documents; next cycle {result['next_cycle']}; "
          f"{u.calls} calls ${u.cost:.3f}; commit {result.get('commit')}")
    print("problems:", *result["problems"], *result.get("bundle_problems", [])[:10], sep="\n  ")
    sys.exit(0)
