"""MAYA's facts as OKF concepts (docs/design/15-phase6-plan.md, "The OKF bundle").

One concept file per entity per topic — `colleges/<slug>/fees-2026-27.md`, `campus.md`,
`location.md` — so each file's `stale_after` means one thing. A file carries the OKF v0.2
families (sources, generated, verified, status, stale_after) and, in the `maya` extension key,
the entity it's about and each value with its own source, page, quote, status and checks. The
body is a readable table, every value footnoted to its source, with any conflict listed.

`upsert` merges newly read values into the bundle: the same attribute and year from the same
publisher replaces the old entry (git keeps the history); another publisher's value sits beside
it. `decide` applies a reviewer's decision. Nothing here touches the database: the loader does.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from app.facts import describe, freshness
from app.models.facts import OFFICIAL_TIERS
from app.okf import bundle
from app.okf.bundle import Concept

QUOTE_CHECK = "process:maya-quote-check"


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


@dataclass(frozen=True)
class Family:
    prefixes: tuple[str, ...]
    stem: str
    type: str
    topic: str
    by_year: bool = False
    exclude: tuple[str, ...] = ()


FAMILIES = (
    Family(("academic.", "location.website"), "college", "College", "about"),
    Family(("location.", "near."), "location", "Location", "location and what's nearby", exclude=("location.website",)),
    Family(("fee.",), "fees", "Fee Structure", "fees", by_year=True),
    Family(("facility.",), "campus", "Campus", "campus facilities"),
    Family(("admission.",), "admissions", "Admissions", "admissions", by_year=True),
    Family(("ranking.",), "rankings", "Ranking", "rankings"),
    Family(("placement.",), "placements", "Placement Record", "placements", by_year=True),
)


def family_of(attribute: str) -> Family:
    for fam in FAMILIES:
        if attribute.startswith(fam.prefixes) and not attribute.startswith(fam.exclude or ("\0",)):
            return fam
    raise ValueError(f"no OKF concept for attribute {attribute!r}")


def in_scope(concept_id: str, attribute: str, academic_year: str | None) -> bool:
    """Whether a value belongs to this concept file (used to withdraw what a file no longer says)."""
    try:
        fam = family_of(attribute)
    except ValueError:
        return False
    stem = concept_id.rsplit("/", 1)[-1]
    if fam.by_year:
        return stem == (f"{fam.stem}-{academic_year}" if academic_year else fam.stem)
    return stem == fam.stem


@dataclass(frozen=True)
class Entity:
    type: str  # college | exam
    name: str  # the official name — what the loader resolves
    state: str | None = None
    city: str | None = None
    kind: str | None = None  # IIT, NIT, Government Medical College…
    aliases: tuple[str, ...] = ()

    @property
    def folder(self) -> str:
        return f"{self.type}s/{slug(self.name)}"

    def meta(self) -> dict:
        out = {"type": self.type, "name": self.name}
        out.update({k: v for k, v in (("state", self.state), ("city", self.city), ("kind", self.kind)) if v})
        if self.aliases:
            out["aliases"] = list(self.aliases)
        return out


@dataclass(frozen=True)
class Document:
    """Where a value was read: the publisher (with its tier) and the exact document."""

    publisher_key: str  # "nirf", "josaa", "osm", "college-manit-bhopal"…
    publisher: str
    tier: int
    url: str
    title: str
    retrieved_at: datetime
    sha256: str | None = None
    parse: str = "reference"  # text | scanned | reference (cited, not fetched by us)


@dataclass
class Value:
    attribute: str
    value: object
    document: Document
    academic_year: str | None = None
    unit: str | None = None
    locator: str | None = None
    quote: str | None = None
    status: str = "verified"  # verified | unverified | not_available | flagged
    flags: list[str] = field(default_factory=list)
    generated_by: str = "maya-extractor/unknown"
    verified_by: str | None = QUOTE_CHECK
    at: datetime | None = None


def _iso(moment) -> str | None:
    if moment is None:
        return None
    if isinstance(moment, str):
        return moment
    if isinstance(moment, datetime):
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return moment.isoformat()


def when(text) -> datetime | None:
    if text is None or isinstance(text, datetime):
        return text if text is None or text.tzinfo else text.replace(tzinfo=timezone.utc)
    if isinstance(text, date):
        return datetime(text.year, text.month, text.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def verifications(entry: dict) -> list[dict]:
    """OKF §5.2: a bare `verified` mapping is a one-element list."""
    v = entry.get("verified")
    return [] if not v else ([v] if isinstance(v, dict) else list(v))


def _family_of_concept(cid: str) -> Family:
    stem = cid.rsplit("/", 1)[-1]
    return next(f for f in FAMILIES if stem == f.stem or (f.by_year and stem.startswith(f"{f.stem}-")))


def concept_id(entity: Entity, attribute: str, academic_year: str | None) -> str:
    fam = family_of(attribute)
    stem = f"{fam.stem}-{academic_year}" if fam.by_year and academic_year else fam.stem
    return f"{entity.folder}/{stem}"


# ---------------- writing ----------------

def _source_entry(doc: Document, sid: str) -> dict:
    entry = {"id": sid, "resource": doc.url, "title": doc.title, "author": f"org:{doc.publisher_key}",
             "publisher": doc.publisher, "tier": doc.tier, "retrieved_at": _iso(doc.retrieved_at)}
    if doc.sha256:
        entry["sha256"] = doc.sha256
    if doc.parse != "reference":
        entry["parse"] = doc.parse
    return entry


def _source_id(sources: list[dict], doc: Document) -> str:
    for s in sources:
        if s["resource"] == doc.url and s.get("sha256") == doc.sha256 and s["author"] == f"org:{doc.publisher_key}":
            return s["id"]
    used = {s["id"] for s in sources}
    n = 1
    while f"s{n}" in used:
        n += 1
    sources.append(_source_entry(doc, f"s{n}"))
    return f"s{n}"


def _entry(v: Value, sid: str) -> dict:
    at = v.at or datetime.now(timezone.utc)
    status = "flagged" if v.flags else ("not_available" if v.value is None else v.status)
    entry = {"attribute": v.attribute, "value": v.value}
    if v.unit:
        entry["unit"] = v.unit
    if v.academic_year:
        entry["academic_year"] = v.academic_year
    entry["source"] = sid
    if v.locator:
        entry["locator"] = v.locator
    if v.quote:
        entry["quote"] = v.quote
    entry["status"] = status
    entry["generated"] = {"by": v.generated_by, "at": _iso(at)}
    if v.verified_by and status in ("verified", "not_available"):
        entry["verified"] = [{"by": v.verified_by, "at": _iso(at)}]
    if v.flags:
        entry["flags"] = list(v.flags)
    return entry


def _publisher(sources: list[dict], sid: str) -> str:
    return next((s["author"] for s in sources if s["id"] == sid), sid)


def _new_concept(cid: str, entity: Entity, attribute: str, academic_year: str | None) -> Concept:
    fam = family_of(attribute)
    year = f" {academic_year}" if fam.by_year and academic_year else ""
    title = entity.name if fam.stem == "college" else f"{entity.name} — {fam.topic}{year}"
    return Concept(cid, {"type": fam.type, "title": title, "maya": {"entity": entity.meta(), "facts": []}, "sources": []})


def _refresh(concept: Concept, entity: Entity) -> None:
    """Recomputes everything derived from the facts: the OKF families and the readable body."""
    meta, facts = concept.meta, concept.meta["maya"]["facts"]
    meta["maya"]["entity"] = entity.meta() if entity else meta["maya"]["entity"]
    sources = meta.get("sources", [])
    used = {f["source"] for f in facts}
    meta["sources"] = [s for s in sources if s["id"] in used]
    fam = _family_of_concept(concept.id)
    shown = [f for f in facts if f["status"] != "flagged"]
    meta["status"] = "stable" if shown or not facts else "draft"
    generated = [f["generated"] for f in facts if f.get("generated")]
    if generated:
        latest = max(generated, key=lambda g: when(g["at"]))
        meta["generated"] = {"by": latest["by"], "at": latest["at"]}
    checks: dict[str, str] = {}
    for f in facts:
        for v in verifications(f):
            if v["by"] not in checks or when(v["at"]) > when(checks[v["by"]]):
                checks[v["by"]] = _iso(v["at"])
    if checks:
        meta["verified"] = [{"by": by, "at": at} for by, at in sorted(checks.items())]
    else:
        meta.pop("verified", None)
    stale = [freshness.stale_at(f["attribute"], when(max((v["at"] for v in verifications(f)), key=when)),
                                f.get("academic_year")) for f in shown if verifications(f)]
    stale = [s for s in stale if s]
    if stale:
        meta["stale_after"] = _iso(min(stale))
    else:
        meta.pop("stale_after", None)
    if meta["sources"]:
        main = max(meta["sources"], key=lambda s: sum(1 for f in facts if f["source"] == s["id"]))
        meta["resource"] = main["resource"]
    who = meta["maya"]["entity"]
    place = ", ".join(x for x in (who.get("city"), who.get("state")) if x)
    if fam.stem == "college":
        meta["description"] = (f"{who.get('kind') or 'College'} in {place}." if place else f"{who.get('kind') or 'College'}.")
        website = next((f.get("value") for f in shown if f["attribute"] == "location.website"), None)
        if isinstance(website, dict) and website.get("url"):
            meta["resource"] = website["url"]
    else:
        meta["description"] = f"{fam.topic.capitalize()} of {who['name']}, each value with its source and when it was checked."
    meta["tags"] = sorted({fam.stem, *(t for t in (who.get("kind"), who.get("state")) if t)})
    concept.body = _body(meta, facts)


def _body(meta: dict, facts: list[dict]) -> str:
    sources = {s["id"]: s for s in meta.get("sources", [])}
    lines = [f"# {meta.get('title', '')}", "", "| What | Value | Year | Status | Source |", "|---|---|---|---|---|"]
    for f in sorted(facts, key=lambda f: (f["attribute"], f.get("academic_year") or "", f["source"])):
        value = describe.value_text(f["attribute"], f.get("value"))
        status = {"verified": "checked", "unverified": "needs verification", "not_available": "not available",
                  "flagged": "waiting for review"}.get(f["status"], f["status"])
        lines.append(f"| {describe.name(f['attribute'])} | {value.replace('|', '/')} | {f.get('academic_year') or ''} "
                     f"| {status} | [^{f['source']}] |")
    clashes = _clashes(facts, sources)
    if clashes:
        lines += ["", "# Conflicts", ""]
        for attribute, year, group in clashes:
            said = "; ".join(f"[^{f['source']}] says {describe.value_text(attribute, f.get('value'))}" for f in group)
            lines.append(f"* {describe.name(attribute)}{f' ({year})' if year else ''}: {said}. These couldn't be reconciled.")
    lines.append("")
    for sid, s in sorted(sources.items(), key=lambda kv: int(kv[0][1:]) if kv[0][1:].isdigit() else 0):
        where = f", {s.get('publisher')}" if s.get("publisher") else ""
        lines.append(f"[^{sid}]: {s['title']}{where} (retrieved {str(s.get('retrieved_at', ''))[:10]})")
    return "\n".join(lines) + "\n"


def _clashes(facts: list[dict], sources: dict) -> list[tuple]:
    from app.facts.store import same_value

    groups: dict[tuple, list[dict]] = {}
    for f in facts:
        if f["status"] in ("verified", "unverified") and f.get("value") is not None:
            groups.setdefault((f["attribute"], f.get("academic_year")), []).append(f)
    out = []
    for (attribute, year), group in groups.items():
        official = [f for f in group if sources.get(f["source"], {}).get("tier") in OFFICIAL_TIERS]
        if len(official) > 1 and any(not same_value(official[0]["value"], f["value"]) for f in official[1:]):
            out.append((attribute, year, official))
    return out


def upsert(root: Path, entity: Entity, values: list[Value], now: datetime | None = None) -> list[str]:
    """Merges values into the bundle; returns log lines for what changed."""
    now = now or datetime.now(timezone.utc)
    log: list[str] = []
    identity = bundle.read(root, f"{entity.folder}/college") if entity.type == "college" else None
    if entity.type == "college" and identity is None:
        identity = Concept(f"{entity.folder}/college", {"type": "College", "title": entity.name,
                                                        "maya": {"entity": entity.meta(), "facts": []}, "sources": []})
        _refresh(identity, entity)
        bundle.write(root, identity)
        log.append(f"**Creation**: [{entity.name}](/{identity.id}.md)")
    by_concept: dict[str, list[Value]] = {}
    for v in values:
        by_concept.setdefault(concept_id(entity, v.attribute, v.academic_year), []).append(v)
    for cid, group in by_concept.items():
        concept = bundle.read(root, cid) or _new_concept(cid, entity, group[0].attribute, group[0].academic_year)
        concept.meta.setdefault("maya", {"entity": entity.meta(), "facts": []}).setdefault("facts", [])
        concept.meta.setdefault("sources", [])
        facts = concept.meta["maya"]["facts"]
        for v in group:
            v.at = v.at or now
            sid = _source_id(concept.meta["sources"], v.document)
            new = _entry(v, sid)
            publisher = f"org:{v.document.publisher_key}"
            old = next((f for f in facts if f["attribute"] == v.attribute and f.get("academic_year") == v.academic_year
                        and _publisher(concept.meta["sources"], f["source"]) == publisher), None)
            if old is None:
                facts.append(new)
                log.append(f"**Update**: {describe.name(v.attribute)} for [{entity.name}](/{cid}.md): "
                           f"{describe.value_text(v.attribute, v.value)} ({new['status']}, from {v.document.title})")
            elif old.get("value") != new.get("value") or old["status"] != new["status"]:
                facts[facts.index(old)] = new
                log.append(f"**Update**: {describe.name(v.attribute)} for [{entity.name}](/{cid}.md) changed from "
                           f"{describe.value_text(v.attribute, old.get('value'))} to "
                           f"{describe.value_text(v.attribute, v.value)} ({new['status']}, from {v.document.title})")
            else:
                old["source"], old["generated"] = sid, old.get("generated") or new["generated"]
                if new.get("verified"):
                    old["verified"] = [x for x in verifications(old) if x["by"] != v.verified_by] + new["verified"]
                for key in ("locator", "quote"):
                    if new.get(key):
                        old[key] = new[key]
        _refresh(concept, entity)
        bundle.write(root, concept)
    return log


# ---------------- review ----------------

def find(concept: Concept, attribute: str, academic_year: str | None, source_id: str) -> dict:
    for f in concept.meta.get("maya", {}).get("facts", []):
        if f["attribute"] == attribute and f.get("academic_year") == academic_year and f["source"] == source_id:
            return f
    raise LookupError(f"{concept.id} has no {attribute} {academic_year or ''} from {source_id}")


def decide(root: Path, cid: str, attribute: str, academic_year: str | None, source_id: str, decision: str,
           reviewer: str, note: str | None = None, value=None, now: datetime | None = None) -> list[str]:
    """A reviewer's decision, made in the bundle: approve (shown, human-reviewed), reject (removed),
    edit (the corrected value, human-reviewed) or pick (in a conflict, this one; the others go)."""
    now = now or datetime.now(timezone.utc)
    actor = reviewer if reviewer.startswith("human:") else f"human:{reviewer}"
    concept = bundle.read(root, cid)
    if concept is None:
        raise LookupError(f"no concept {cid}")
    facts = concept.meta["maya"]["facts"]
    fact = find(concept, attribute, academic_year, source_id)
    entity = concept.meta["maya"]["entity"]
    why = f" — {note}" if note else ""
    label = f"{describe.name(attribute)} for [{entity['name']}](/{cid}.md)"
    if decision == "approve":
        fact["status"] = "verified" if fact.get("value") is not None else "not_available"
        fact.pop("flags", None)
        fact["verified"] = verifications(fact) + [{"by": actor, "at": _iso(now)}]
        log = [f"**Review**: {actor} approved {label}{why}"]
    elif decision == "reject":
        facts.remove(fact)
        log = [f"**Review**: {actor} rejected {label} ({describe.value_text(attribute, fact.get('value'))}){why}"]
    elif decision == "edit":
        fact["value"], fact["status"] = value, "verified"
        fact.pop("flags", None)
        fact["verified"] = [{"by": actor, "at": _iso(now)}]
        log = [f"**Review**: {actor} corrected {label} to {describe.value_text(attribute, value)}{why}"]
    elif decision == "pick":
        rivals = [f for f in facts if f is not fact and f["attribute"] == attribute
                  and f.get("academic_year") == academic_year]
        for r in rivals:
            facts.remove(r)
        fact["verified"] = verifications(fact) + [{"by": actor, "at": _iso(now)}]
        log = [f"**Review**: {actor} settled a conflict on {label}: kept {describe.value_text(attribute, fact.get('value'))}{why}"]
    else:
        raise ValueError("decision must be approve, reject, edit or pick")
    _refresh(concept, Entity(**{k: (tuple(v) if k == "aliases" else v) for k, v in entity.items()}))
    bundle.write(root, concept)
    return log
