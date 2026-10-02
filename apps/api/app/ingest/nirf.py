"""NIRF 2025 ranks from the Ministry of Education's own ranking pages (tier 1).

Each ranked row (institute id, name, city, state, score, rank) is matched to a college by its
name or short names, with the state as a tie-breaker; the row's own words are kept as the quote.
Rows that match nothing are reported, never guessed.

    python -m app.ingest.nirf
"""

from __future__ import annotations

import html
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.fetch import Fetched, Fetcher
from app.ingest.publish import college_entity, publish
from app.models.college import College
from app.okf.aliases import aliases_for
from app.okf.facts import Document, Value

YEAR = 2025
PAGES = {
    "engineering": f"https://www.nirfindia.org/Rankings/{YEAR}/EngineeringRanking.html",
    "medical": f"https://www.nirfindia.org/Rankings/{YEAR}/MedicalRanking.html",
}
PUBLISHER = ("nirf", "NIRF, Ministry of Education", 1)


@dataclass(frozen=True)
class Row:
    institute_id: str
    name: str
    city: str
    state: str
    score: float
    rank: int

    @property
    def quote(self) -> str:
        return f"{self.institute_id} {self.name} {self.city} {self.state} {self.score:g} {self.rank}"


def parse(page: str) -> list[Row]:
    text = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    tokens = [t.strip() for t in text.split("\n") if t.strip()]
    starts = [i for i, t in enumerate(tokens) if re.fullmatch(r"IR-[A-Z]-[A-Z]-\d+", t)]
    rows = []
    for n, i in enumerate(starts):
        segment = [t for t in tokens[i:(starts[n + 1] if n + 1 < len(starts) else len(tokens))]
                   if t not in ("More Details", "Close")]
        try:
            city, state, score, rank = segment[-4:]
            rows.append(Row(segment[0], " ".join(segment[1].split()), city, state, float(score), int(rank)))
        except ValueError:
            continue  # a row that isn't a ranked institute (a header, a broken cell)
    return rows


def _norm(text: str) -> str:
    text = text.lower().replace("&", " and ").replace("`", "").replace("'", "")
    text = re.sub(r"\bgovt\b", "government", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _keys(name: str, city: str | None) -> set[str]:
    return {_norm(name)} | {_norm(a) for a in aliases_for(name, city)}


def match(rows: list[Row], colleges: list[College]) -> tuple[dict[int, Row], list[Row]]:
    index: dict[str, list[College]] = {}
    for c in colleges:
        for key in _keys(c.canonical_name, c.city):
            index.setdefault(key, []).append(c)
    found: dict[int, Row] = {}
    missed: list[Row] = []
    for row in rows:
        hits = {c.id: c for key in _keys(row.name, row.city) for c in index.get(key, [])}
        if len(hits) > 1:
            hits = {i: c for i, c in hits.items() if _norm(c.state) == _norm(row.state)}
        if not hits:
            # "Christian Medical College" (Vellore) is "Christian Medical College, Vellore" in the
            # counselling list: the official name starts with NIRF's, and the city agrees.
            name, city = _norm(row.name), _norm(row.city)
            hits = {c.id: c for c in colleges
                    if (_norm(c.canonical_name).startswith(name) or name.startswith(_norm(c.canonical_name)))
                    and (city in _norm(c.canonical_name) or _norm(c.city) == city)}
        if len(hits) == 1:
            found[next(iter(hits))] = row
        else:
            missed.append(row)
    return found, missed


def values_for(category: str, page: Fetched, rows: list[Row], colleges: list[College]) -> tuple[dict, list[Row]]:
    found, missed = match(rows, colleges)
    doc = Document(PUBLISHER[0], PUBLISHER[1], PUBLISHER[2], page.final_url, f"NIRF {YEAR} {category.title()} ranking",
                   page.retrieved_at, sha256=page.sha256, parse="text")
    by_id = {c.id: c for c in colleges}
    values = {}
    for college_id, row in found.items():
        values[college_entity(by_id[college_id])] = [Value(
            f"ranking.nirf.{category}", {"rank": row.rank, "category": category.title(), "year": YEAR, "score": row.score},
            doc, locator=f"rank {row.rank}, institute {row.institute_id}", quote=row.quote,
            generated_by="maya-nirf/1", at=page.retrieved_at)]
    return values, missed


def run(db: Session, fetcher: Fetcher, root=None) -> dict:
    colleges = list(db.execute(select(College)).scalars())
    report: dict = {"ranked": {}, "unmatched": {}, "failed": {}}
    all_values: dict = {}
    for category, url in PAGES.items():
        page = fetcher.get(url)
        if not page.ok:
            report["failed"][category] = page.error
            continue
        rows = parse(page.text())
        values, missed = values_for(category, page, rows, colleges)
        for entity, vals in values.items():
            all_values.setdefault(entity, []).extend(vals)
        report["ranked"][category] = f"{len(values)} of {len(rows)} ranked institutes matched"
        report["unmatched"][category] = [f"{r.rank}. {r.name} ({r.city}, {r.state})" for r in missed]
    if all_values:
        report.update(publish(db, all_values, f"NIRF {YEAR} ranks ({datetime.now(timezone.utc):%Y-%m-%d})", root))
    return report


if __name__ == "__main__":
    from app.core.config import get_settings
    from app.core.db import SessionLocal

    with SessionLocal() as session, Fetcher(get_settings().source_store_path) as fetcher:
        result = run(session, fetcher)
    for key in ("ranked", "failed"):
        print(key, result[key])
    for category, names in result["unmatched"].items():
        print(f"unmatched {category}: {len(names)}", *names[:200], sep="\n  ")
    print({k: result.get(k) for k in ("changes", "commit", "loaded")}, "problems:", result.get("problems", [])[:10])
    sys.exit(0)
