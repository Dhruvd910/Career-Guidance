"""Recording facts and reading the current value of each (docs/design/06-college-provenance.md).

Recording:
- A new value from the same source for the same attribute and academic year **supersedes** the
  old one (kept, linked). The same value again just re-confirms it: its checked time moves on.
- Values from different sources stand side by side. If checked values from official sources
  (tiers 1–4), or from two non-official ones of the same tier, disagree, that's a **conflict**, shown to the
  student as both values with their sources (spec §33) until a reviewer picks one.
- A fact with flags waits for review and isn't shown.

Facts arrive here only from the OKF bundle's loader (app/okf/loader.py).

Reading (`current`): per attribute, the latest academic year; a real value beats "not available";
then the best tier, then the most recently checked. Each comes back as a FactView — the value
with its source, the words it was read from, and its freshness label.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.facts import freshness
from app.models.facts import OFFICIAL_TIERS, SHOWN, TIERS, Fact, FactConflict, Source, SourceDocument


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- sources and documents ----------------

def source(db: Session, key: str, name: str, tier: int, base_url: str | None = None, notes: str | None = None) -> Source:
    if tier not in TIERS:
        raise ValueError(f"tier must be 1–6, not {tier}")
    row = db.execute(select(Source).where(Source.key == key)).scalar_one_or_none()
    if row is None:
        row = Source(key=key, name=name, tier=tier, base_url=base_url, notes=notes)
        db.add(row)
    else:
        row.name, row.tier = name, tier
        row.base_url = base_url or row.base_url
        row.notes = notes or row.notes
    db.flush()
    return row


def document(db: Session, src: Source, url: str, title: str, retrieved_at: datetime | None = None, *,
             sha256: str | None = None, storage_path: str | None = None, mime: str | None = None,
             http_status: int | None = None, size_bytes: int | None = None, academic_year: str | None = None,
             effective_date: date | None = None, parse_status: str = "reference",
             entity_refs: Iterable[str] = ()) -> SourceDocument:
    """One fetch of one URL. The same content again returns the existing document; changed
    content is a new document that supersedes the last one."""
    latest = db.execute(select(SourceDocument).where(
        SourceDocument.source_id == src.id, SourceDocument.url == url, SourceDocument.superseded_by.is_(None),
    ).order_by(SourceDocument.id.desc())).scalars().first()
    if latest is not None and (latest.sha256 == sha256 or (sha256 is None and latest.parse_status == "reference")):
        latest.entity_refs = sorted(set(latest.entity_refs or []) | set(entity_refs))
        return latest
    doc = SourceDocument(source_id=src.id, url=url, title=title[:500], retrieved_at=retrieved_at or _now(),
                         sha256=sha256, storage_path=storage_path, mime=mime, http_status=http_status,
                         size_bytes=size_bytes, academic_year=academic_year, effective_date=effective_date,
                         parse_status=parse_status, entity_refs=sorted(set(entity_refs)))
    db.add(doc)
    db.flush()
    if latest is not None:
        latest.superseded_by = doc.id
    return doc


# ---------------- recording ----------------

def _comparable(value):
    if isinstance(value, dict) and "amount" in value:
        return ("amount", value.get("amount"), value.get("per"), value.get("applies_to"))
    if isinstance(value, dict) and "name" in value:
        return ("name", str(value["name"]).strip().lower())
    if isinstance(value, str):
        return " ".join(value.lower().split())
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def same_value(a, b) -> bool:
    return _comparable(a) == _comparable(b)


def _key_filter(entity_type: str, entity_id: int, attribute: str, academic_year: str | None):
    year = Fact.academic_year.is_(None) if academic_year is None else Fact.academic_year == academic_year
    return (Fact.entity_type == entity_type, Fact.entity_id == entity_id, Fact.attribute == attribute, year,
            Fact.superseded_by.is_(None))


def record(db: Session, entity_type: str, entity_id: int, attribute: str, value, *, document: SourceDocument,
           academic_year: str | None = None, unit: str | None = None, locator: str | None = None,
           quote: str | None = None, verified_by: str = "auto", status: str | None = None,
           confidence: float | None = None, flags: Iterable[str] = (), now: datetime | None = None) -> Fact:
    now = now or _now()
    flags = list(flags)
    wanted = "flagged" if flags else ("not_available" if value is None else (status or "verified"))
    existing = db.execute(select(Fact).where(*_key_filter(entity_type, entity_id, attribute, academic_year),
                                             Fact.status != "withdrawn")).scalars().all()
    for old in existing:
        if old.document.source_id != document.source_id:
            continue
        if old.value == value and old.status == wanted:  # exactly the same: re-confirmed
            old.verified_at = now if wanted in ("verified", "not_available") else old.verified_at
            old.retrieved_at = document.retrieved_at
            old.source_document_id, old.locator = document.id, locator or old.locator
            old.quote = quote or old.quote
            db.flush()
            reconcile(db, entity_type, entity_id, attribute, academic_year)
            return old
    fact = Fact(entity_type=entity_type, entity_id=entity_id, attribute=attribute, value=value, unit=unit,
                academic_year=academic_year, source_document_id=document.id, locator=locator, quote=quote,
                retrieved_at=document.retrieved_at, verified_at=now if wanted in ("verified", "not_available") else None,
                verified_by=verified_by, status=wanted, confidence=confidence, flags=flags)
    db.add(fact)
    db.flush()
    for old in existing:
        if old.document.source_id == document.source_id:
            old.superseded_by = fact.id
    db.flush()
    reconcile(db, entity_type, entity_id, attribute, academic_year)
    return fact


def _disagree(a: Fact, b: Fact) -> bool:
    ta, tb = a.document.source.tier, b.document.source.tier
    comparable = (ta in OFFICIAL_TIERS and tb in OFFICIAL_TIERS) or ta == tb
    return comparable and not same_value(a.value, b.value)


def reconcile(db: Session, entity_type: str, entity_id: int, attribute: str, academic_year: str | None) -> None:
    """Keeps one unresolved conflict per attribute and year, over the current facts that disagree."""
    # Only checked values can disagree: an unchecked one (a shared template, an unfetched citation)
    # just ranks below whatever has been checked.
    live = [f for f in db.execute(select(Fact).where(*_key_filter(entity_type, entity_id, attribute, academic_year),
                                                     Fact.status == "verified")).scalars()]
    involved = sorted({f.id for a in live for b in live if a.id < b.id and _disagree(a, b) for f in (a, b)})
    year = FactConflict.academic_year.is_(None) if academic_year is None else FactConflict.academic_year == academic_year
    open_ = db.execute(select(FactConflict).where(
        FactConflict.entity_type == entity_type, FactConflict.entity_id == entity_id,
        FactConflict.attribute == attribute, year, FactConflict.resolution == "unresolved")).scalars().first()
    if involved and open_ is None:
        db.add(FactConflict(entity_type=entity_type, entity_id=entity_id, attribute=attribute,
                            academic_year=academic_year, fact_ids=involved))
    elif involved:
        open_.fact_ids = involved
    elif open_ is not None:
        open_.resolution, open_.note = "agreed", "the sources now agree"
    db.flush()


def not_available(db: Session, entity_type: str, entity_id: int, attribute: str, *, document: SourceDocument,
                  academic_year: str | None = None, now: datetime | None = None) -> Fact:
    """We looked in `document` and it isn't there — stored, so it's said, never filled in."""
    return record(db, entity_type, entity_id, attribute, None, document=document, academic_year=academic_year, now=now)


# ---------------- reading ----------------

def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat()


def view(fact: Fact, today: date, conflict: list[Fact] | None = None) -> dict:
    src, doc = fact.document.source, fact.document
    label = freshness.label(fact.status, fact.attribute, fact.verified_at, fact.academic_year, today)
    status = "conflicted" if conflict else ("stale" if label["state"] == "stale" else fact.status)
    return {
        "fact_id": fact.id, "attribute": fact.attribute, "value": fact.value, "unit": fact.unit,
        "academic_year": fact.academic_year, "status": status, "label": label,
        "verified_at": _iso(fact.verified_at), "retrieved_at": _iso(fact.retrieved_at), "verified_by": fact.verified_by,
        "source": {"name": src.name, "tier": src.tier, "kind": TIERS[src.tier], "official": src.tier in OFFICIAL_TIERS,
                   "document": doc.title, "url": doc.url, "locator": fact.locator},
        "quote": fact.quote,
        "conflict": [view(other, today) for other in conflict] if conflict else None,
    }


def _rank(fact: Fact) -> tuple:
    checked = fact.verified_at or fact.retrieved_at
    if checked is not None and checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return (fact.value is None, fact.status != "verified", fact.document.source.tier,
            -(checked.timestamp() if checked else 0), -fact.id)


def current(db: Session, entity_type: str, entity_id: int, attributes: Iterable[str] | None = None,
            prefix: str | None = None, today: date | None = None) -> dict[str, dict]:
    """The value to show for each attribute of one entity, as FactViews."""
    today = today or _now().date()
    query = select(Fact).where(Fact.entity_type == entity_type, Fact.entity_id == entity_id,
                               Fact.superseded_by.is_(None), Fact.status.in_(SHOWN))
    if attributes is not None:
        query = query.where(Fact.attribute.in_(list(attributes)))
    if prefix:
        query = query.where(Fact.attribute.startswith(prefix))
    by_attribute: dict[str, list[Fact]] = defaultdict(list)
    for fact in db.execute(query).scalars():
        by_attribute[fact.attribute].append(fact)
    conflicts = db.execute(select(FactConflict).where(
        FactConflict.entity_type == entity_type, FactConflict.entity_id == entity_id,
        FactConflict.resolution == "unresolved")).scalars().all()
    out = {}
    for attribute, facts in by_attribute.items():
        years = sorted({f.academic_year for f in facts if f.academic_year})
        year = years[-1] if years else None
        candidates = [f for f in facts if f.academic_year == year] or facts
        if any(f.value is not None for f in candidates):
            candidates = [f for f in candidates if f.value is not None]
        best = min(candidates, key=_rank)
        clash = next((c for c in conflicts if c.attribute == attribute and c.academic_year == year
                      and best.id in c.fact_ids), None)
        others = [f for f in candidates if clash and f.id in clash.fact_ids and f.id != best.id]
        out[attribute] = view(best, today, conflict=others or None)
    return out


def history(db: Session, entity_type: str, entity_id: int, attribute: str) -> list[Fact]:
    """Every value this attribute has had, newest first — superseded ones included."""
    return list(db.execute(select(Fact).where(
        Fact.entity_type == entity_type, Fact.entity_id == entity_id, Fact.attribute == attribute,
    ).order_by(Fact.id.desc())).scalars())


# ---------------- review ----------------

def waiting(db: Session) -> list[Fact]:
    """Flagged facts and facts in open conflicts — what a person should look at. Decisions are
    made in the OKF bundle (app/okf/review.py), then loaded."""
    flagged = list(db.execute(select(Fact).where(Fact.status == "flagged", Fact.superseded_by.is_(None))
                              .order_by(Fact.id)).scalars())
    in_conflict = [db.get(Fact, i) for c in db.execute(select(FactConflict).where(
        FactConflict.resolution == "unresolved")).scalars() for i in c.fact_ids]
    return flagged + [f for f in in_conflict if f is not None]
