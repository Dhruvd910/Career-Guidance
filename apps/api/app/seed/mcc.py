"""Loads NEET-UG All-India counselling cutoffs from MCC (mcc.nic.in).

Source: MCC's "Final Allotment Result for Round 1" (24.08.2026) and "Final Result UG Round 2
Counselling 2026" (12.09.2026). Every allotted candidate's All-India Rank is listed per
institute, course, quota and seat category; the opening and closing ranks here are the best
and worst ranks allotted to each seat group across both rounds. They're kept in
app/seed/data/mcc_neet_2026_round2.csv (built from the PDFs; see that folder's README).

2026 counselling is still in progress (Round 3 results are due on 30 September 2026), so
these closing ranks will loosen further in later rounds — predictions from them lean
cautious, and say so.

MCC allots every category by All-India Rank (unlike JoSAA, which uses category ranks), so
NEET predictions compare the student's AIR with every seat category they're eligible for.

This covers the All-India (MCC) seats only: the 15% All-India quota of government colleges,
AIIMS, JIPMER, central and deemed universities. The other 85% of government seats go
through each state's own counselling, which isn't included yet.

Run with:  python -m app.seed.mcc
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.db import Base, SessionLocal, engine
from app.models.college import College, CollegeCourse, Course
from app.models.cutoff import Cutoff
from app.models.exam import Exam
from app.seed.josaa import _remove_demo_colleges

DATA = Path(__file__).parent / "data"
TABLE = ("mcc_neet_2026_round2.csv", 2026, 2)
SOURCE = "MCC NEET-UG allotments (rounds 1–2)"
SOURCE_URL = "https://mcc.nic.in/ug-medical-counselling/"
COURSES = {"MBBS": ("MBBS", 5.5), "BDS": ("BDS", 5.0), "B.Sc. Nursing": ("B.Sc Nursing", 4.0)}


def normalise_quota(raw: str) -> str | None:
    """MCC's quota names (as wrapped in the PDF) -> the few a student needs to know about.
    Returns None for quotas only a narrow group can use (ESI, NRI, minority, armed-forces
    wards, foreign nationals, university-internal) — those aren't predicted."""
    q = " ".join(raw.lower().split())
    if "children/wid" in q or "cw" in q.split() or "cw quota" in q:
        return None
    if q in ("all india", "b.sc nursing all india"):
        return "AIQ"
    if q == "open seat quota":
        return "Open"
    if q == "self-financed merit seat":
        return "Deemed"
    if q in ("delhi university quota", "ip university quota", "b.sc nursing delhi ncr"):
        return "Delhi"
    if q.startswith("internal") and "puducherry" in q:
        return "Puducherry"
    return None


# Which normalised quotas a student can compete for, given their domicile.
def quota_open_to(quota: str, domicile_state: str | None) -> bool:
    if quota in ("AIQ", "Open", "Deemed"):
        return True
    if quota == "Delhi":
        return domicile_state == "Delhi"
    if quota == "Puducherry":
        return domicile_state == "Puducherry"
    return False


def _college_type(name: str, quotas: set[str]) -> tuple[str, str]:
    upper = name.upper()
    if "AIIMS" in upper:
        return "AIIMS", "government"
    if "JIPMER" in upper:
        return "JIPMER", "government"
    if "ESIC" in upper or "ESI " in upper:
        return "ESIC", "government"
    if "Deemed" in quotas and not quotas & {"AIQ", "Open"}:
        return "Deemed University", "deemed"
    return "Government Medical College", "government"


def seed_mcc(db: Session) -> dict:
    neet = db.query(Exam).filter(Exam.code == "NEET_UG").one()
    now = datetime.now(UTC)
    removed = _remove_demo_colleges(db, [neet.id])
    filename, year, round_no = TABLE

    rows = []
    quotas_by_college: dict[str, set[str]] = {}
    with open(DATA / filename, newline="") as f:
        for row in csv.DictReader(f):
            quota = normalise_quota(row["quota"])
            if quota is None or row["course"] not in COURSES:
                continue
            rows.append((row, quota))
            quotas_by_college.setdefault(row["institute"], set()).add(quota)

    db.query(Cutoff).filter(Cutoff.source == SOURCE, Cutoff.year == year).delete(synchronize_session=False)
    colleges = {c.canonical_name: c for c in db.query(College).all()}
    courses = {(c.name, c.duration_years): c for c in db.query(Course).all()}
    college_courses = {(cc.college_id, cc.course_id): cc for cc in
                       db.query(CollegeCourse).filter(CollegeCourse.exam_id == neet.id).all()}
    seen: dict[tuple, Cutoff] = {}
    for row, quota in rows:
        name = row["institute"]
        college = colleges.get(name)
        if college is None:
            kind, ownership = _college_type(name, quotas_by_college[name])
            college = College(
                canonical_name=name, college_type=kind, ownership=ownership,
                state=row["state"] or "India", city=row["city"] or "", is_demo_data=False,
            )
            db.add(college)
            db.flush()
            colleges[name] = college
        course_name, years = COURSES[row["course"]]
        course = courses.get((course_name, years))
        if course is None:
            course = Course(name=course_name, level="UG", duration_years=years)
            db.add(course)
            db.flush()
            courses[(course_name, years)] = course
        cc = college_courses.get((college.id, course.id))
        if cc is None:
            cc = CollegeCourse(
                college_id=college.id, course_id=course.id, branch_id=None, exam_id=neet.id,
                source=SOURCE, source_url=SOURCE_URL, academic_year=f"{year}-{str(year + 1)[-2:]}",
                last_verified=now, verification_status="verified",
            )
            db.add(cc)
            db.flush()
            college_courses[(college.id, course.id)] = cc

        opening, closing = int(row["opening_rank"]), int(row["closing_rank"])
        key = (cc.id, quota, row["category"])
        existing = seen.get(key)
        if existing is not None:  # two raw quota spellings that normalise to the same seat group
            existing.opening_rank = min(existing.opening_rank, opening)
            existing.closing_rank = max(existing.closing_rank, closing)
            continue
        cutoff = Cutoff(
            college_course_id=cc.id, year=year, round=round_no, category=row["category"], quota=quota,
            seat_type="Gender-Neutral", opening_rank=opening, closing_rank=closing,
            source=SOURCE, source_url=SOURCE_URL, academic_year=f"{year}-{str(year + 1)[-2:]}",
            last_verified=now, verification_status="verified",
        )
        db.add(cutoff)
        seen[key] = cutoff
    db.commit()
    return {"seat_groups": len(seen), "colleges": len(quotas_by_college), "demo_colleges_removed": removed}


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("MCC NEET data loaded:", seed_mcc(db))
    finally:
        db.close()


if __name__ == "__main__":
    run()
