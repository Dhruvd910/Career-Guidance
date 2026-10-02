"""Every college's identity, short names and admission route, from the official tables MAYA
already keeps (JoSAA 2026 round 5, MCC NEET-UG 2026 rounds 1–2; tier 3).

Each college gets its identity concept in the OKF bundle (official name, place, type, short
names) and an `admission.route` fact — which counselling and exam lead there and how many
programmes — quoting that college's first row in the official file.

    python -m app.ingest.official_tables
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingest.publish import college_entity, publish
from app.models.college import College, CollegeCourse
from app.models.exam import Exam
from app.okf.facts import Document, Value
from app.seed.josaa import SOURCE_URL as JOSAA_URL
from app.seed.mcc import SOURCE_URL as MCC_URL

DATA = Path(__file__).resolve().parent.parent / "seed" / "data"
TABLES = {
    "josaa": ("josaa_2026_round5.csv", JOSAA_URL, "JoSAA", "JoSAA 2026 opening and closing ranks, round 5"),
    "mcc": ("mcc_neet_2026_round2.csv", MCC_URL, "Medical Counselling Committee (MCC)",
            "MCC NEET-UG 2026 allotments, rounds 1–2"),
}
ROUTES = {"JEE_ADVANCED": ("JoSAA 2026", "JEE (Advanced)", "josaa"), "JEE_MAIN": ("JoSAA 2026", "JEE (Main)", "josaa"),
          "NEET_UG": ("MCC 2026 All-India counselling", "NEET-UG", "mcc")}
ACADEMIC_YEAR = "2026-27"


def _document(key: str) -> tuple[Document, dict[str, tuple[int, str]]]:
    """The official file as a source document, and each institute's first row (number, words)."""
    name, url, publisher, title = TABLES[key]
    path = DATA / name
    raw = path.read_bytes()
    first: dict[str, tuple[int, str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            first.setdefault(row["institute"], (n, ", ".join(v for v in row.values() if v)))
    retrieved = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return Document(key, publisher, 3, url, f"{title} ({name})", retrieved, sha256=hashlib.sha256(raw).hexdigest(),
                    parse="text"), first


def values(db: Session) -> tuple[dict, list[str]]:
    docs = {key: _document(key) for key in TABLES}
    counts: dict[int, dict[str, int]] = defaultdict(dict)
    for college_id, code, n in db.execute(
            select(CollegeCourse.college_id, Exam.code, func.count()).join(Exam, Exam.id == CollegeCourse.exam_id)
            .group_by(CollegeCourse.college_id, Exam.code)):
        counts[college_id][code] = n
    out, missing = {}, []
    for college in db.execute(select(College).order_by(College.id)).scalars():
        vals = []
        for code, n in sorted(counts.get(college.id, {}).items()):
            if code not in ROUTES:
                continue
            route, exam, table = ROUTES[code]
            doc, first = docs[table]
            row = first.get(college.canonical_name)
            if row is None:
                missing.append(f"{college.canonical_name}: not found in {TABLES[table][0]}")
                continue
            vals.append(Value("admission.route", {"route": route, "exam": exam, "programmes": n}, doc,
                              academic_year=ACADEMIC_YEAR, locator=f"row {row[0]}", quote=row[1],
                              generated_by="maya-official-tables/1", at=doc.retrieved_at))
        # one route per exam: JEE (Main) and (Advanced) programmes are separate facts by exam
        out[college_entity(college)] = _one_per_exam(vals)
    return out, missing


def _one_per_exam(vals: list[Value]) -> list[Value]:
    if len(vals) <= 1:
        return vals
    merged = {"route": vals[0].value["route"], "exam": " and ".join(v.value["exam"] for v in vals),
              "programmes": sum(v.value["programmes"] for v in vals)}
    first = vals[0]
    return [Value(first.attribute, merged, first.document, first.academic_year, locator=first.locator, quote=first.quote,
                  generated_by=first.generated_by, at=first.at)]


def run(db: Session, root=None) -> dict:
    vals, missing = values(db)
    report = publish(db, vals, "Identities, short names and admission routes from the official JoSAA and MCC tables", root)
    report["missing"] = missing
    report["colleges"] = len(vals)
    return report


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        result = run(session)
    print({k: result[k] for k in ("colleges", "changes", "commit", "loaded")})
    print("not found in the official files:", len(result["missing"]), *result["missing"][:20], sep="\n  ")
    print("problems:", result["problems"][:20])
