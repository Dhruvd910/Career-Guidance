"""Researched college profiles: ranking, cost, placements and what's around the campus.

The profiles live in app/seed/data/college_profiles.json, keyed by the college's canonical
name, so they can be read and corrected without a database migration. Shared facts (the
common IIT and NIT fee structures, "medicine has no campus placements") are written once as
templates, and every figure points at a named source.

Cutoffs aren't part of a profile — they come from the real JoSAA and MCC tables — so
`admission_summary` sums those up alongside.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.college import CollegeCourse
from app.models.cutoff import Cutoff
from app.services.prediction_service import uses_paper_2

PROFILES = Path(__file__).resolve().parent.parent / "seed" / "data" / "college_profiles.json"

# The seat pool anyone in India can compete for, in the order to look for it: JoSAA's
# All-India (IITs) and Other-State (NITs etc.) quotas, MCC's All-India and open seats.
ALL_INDIA_QUOTAS = ("AI", "OS", "AIQ", "Open", "Deemed")


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(PROFILES.read_text())


def _source(ref: str | None) -> dict | None:
    if not ref:
        return None
    src = _load()["sources"].get(ref)
    return dict(src) if src else None


def _resolve(value):
    """A string names a template; a dict is used as written."""
    if isinstance(value, str):
        return dict(_load()["templates"][value])
    return dict(value) if value else None


def profile_for(name: str) -> dict | None:
    """The researched profile for a college (by canonical name), with templates filled in
    and source references turned into {name, url}. None if it hasn't been researched yet."""
    raw = _load()["colleges"].get(name)
    if raw is None:
        return None
    profile: dict = {"website": raw.get("website"), "established": raw.get("established"),
                     "hospital": raw.get("hospital"), "surroundings": raw.get("surroundings")}
    sources: list[dict] = []

    def cite(section: dict | None) -> dict | None:
        if section is None:
            return None
        src = _source(section.pop("source", None))
        if src:
            section["source"] = src
            if src not in sources:
                sources.append(src)
        return section

    profile["nirf"] = cite(dict(raw["nirf"]) if raw.get("nirf") else None)
    profile["fees"] = cite(_resolve(raw.get("fees")))
    profile["placements"] = cite(_resolve(raw.get("placements")))
    profile["sources"] = sources
    return profile


ABBREVIATIONS = {
    "iit": "indian institute of technology",
    "nit": "national institute of technology",
    "iiit": "indian institute of information technology",
    "iiest": "indian institute of engineering science and technology",
    "mamc": "maulana azad medical college",
    "vmmc": "vardhman mahavir medical college",
    "kgmu": "king george medical university",
    "trichy": "tiruchirappalli",
    "bengaluru": "bangalore",
}


def search_variants(q: str) -> list[str]:
    """"IIT Bombay" -> ["iit bombay", "indian institute of technology bombay"] (also with
    "technology, bombay", as some official names have a comma)."""
    raw = " ".join(q.lower().split())
    words = raw.split(" ")
    expanded = " ".join(ABBREVIATIONS.get(w, w) for w in words)
    variants = [raw, expanded]
    if expanded != raw:
        for i in range(1, len(words)):
            head = " ".join(ABBREVIATIONS.get(w, w) for w in words[:i])
            tail = " ".join(ABBREVIATIONS.get(w, w) for w in words[i:])
            variants.append(f"{head}, {tail}")
    return list(dict.fromkeys(variants))


def researched_names() -> list[str]:
    return list(_load()["colleges"])


def program_name(cc: CollegeCourse) -> str:
    if cc.branch is not None:
        return f"{cc.branch.name} ({cc.course.name})"
    return cc.course.name


def admission_summary(db: Session, college_id: int) -> dict | None:
    """How hard this college is to get into, from its latest real cutoffs: the closing rank of
    each program for an open (General), gender-neutral, all-India seat — the pool every
    student can compete for. Returns the toughest and easiest programs and a few in between."""
    rows = (
        db.query(Cutoff, CollegeCourse)
        .join(CollegeCourse, CollegeCourse.id == Cutoff.college_course_id)
        .filter(CollegeCourse.college_id == college_id, Cutoff.category == "General",
                Cutoff.seat_type == "Gender-Neutral", Cutoff.quota.in_(ALL_INDIA_QUOTAS))
        .all()
    )
    if not rows:
        return None
    latest = max(c.year for c, _ in rows)
    best: dict[int, tuple[int, Cutoff, CollegeCourse]] = {}
    for cutoff, cc in rows:
        if cutoff.year != latest or uses_paper_2(cc):
            continue
        priority = ALL_INDIA_QUOTAS.index(cutoff.quota)
        current = best.get(cc.id)
        if current is None or priority < current[0]:
            best[cc.id] = (priority, cutoff, cc)
    if not best:
        return None
    programs = sorted(
        ({"program": program_name(cc), "closing_rank": cutoff.closing_rank, "quota": cutoff.quota}
         for _, cutoff, cc in best.values()),
        key=lambda p: p["closing_rank"],
    )
    sample_cutoff, sample_cc = next(iter(best.values()))[1:]
    return {
        "exam_code": sample_cc.exam.code,
        "year": latest,
        "round": sample_cutoff.round,
        "source": sample_cutoff.source,
        "source_url": sample_cutoff.source_url,
        "program_count": len(programs),
        "toughest": programs[0],
        "easiest": programs[-1],
        "programs": programs[:6],
    }
