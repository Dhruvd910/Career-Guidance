"""Loads JoSAA's official opening and closing ranks — every IIT, NIT, IIIT and GFTI.

Source: JoSAA 2026, round 5 (the final round), opening & closing ranks, downloaded from
https://josaa.admissions.nic.in and kept as app/seed/data/josaa_2026_round5.csv so the data
can be reloaded without going back to the site. Each year's table can be added the same way.

What the ranks mean (JoSAA's own note): for OPEN seats they're Common Rank List (overall)
ranks; for reserved categories (EWS, OBC-NCL, SC, ST) they're *category* ranks. IITs and IISc
admit on JEE Advanced ranks; everyone else on JEE Main ranks. PwD rows and preparatory-list
ranks ("P") are left out — MAYA doesn't ask about either yet.

This replaces the demo engineering colleges: once real JoSAA data is loaded, sample colleges
for JEE are removed so they can't be mistaken for real ones.

Run with:  python -m app.seed.josaa
"""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.db import Base, SessionLocal, engine
from app.models.college import Branch, College, CollegeCourse, Course
from app.models.cutoff import Cutoff
from app.models.exam import Exam
from app.models.facility import Facility
from app.models.fee import Fee
from app.models.hostel import Hostel
from app.models.nearby import NearbyPlace
from app.models.placement import Placement
from app.models.review import CollegeReview

DATA = Path(__file__).parent / "data"
TABLES = [
    # (csv file, year, round)
    ("josaa_2026_round5.csv", 2026, 5),
]
SOURCE = "JoSAA opening & closing ranks"
SOURCE_URL = "https://josaa.admissions.nic.in/Applicant/seatallotmentresult/currentorcr.aspx"

CATEGORIES = {"OPEN": "General", "OBC-NCL": "OBC", "EWS": "EWS", "SC": "SC", "ST": "ST"}
DEGREES = {
    "Bachelor of Technology": "B.Tech",
    "Bachelor and Master of Technology (Dual Degree)": "B.Tech + M.Tech (Dual Degree)",
    "Bachelor of Architecture": "B.Arch",
    "Bachelor of Science": "B.S.",
    "Bachelor of Planning": "B.Plan",
    "Bachelor of Design": "B.Des",
    "Integrated Master of Science": "Integrated M.Sc",
    "Bachelor of Science and Master of Science (Dual Degree)": "B.S. + M.S. (Dual Degree)",
    "Integrated B. Tech. and M. Tech.": "B.Tech + M.Tech (Integrated)",
    "Integrated Master of Technology": "B.Tech + M.Tech (Integrated)",
    "Integrated Masters in Technology": "B.Tech + M.Tech (Integrated)",
    "B.Tech. + M.Tech./MS (Dual Degree)": "B.Tech + M.Tech/MS (Dual Degree)",
    "Bachelor of Technology and MBA (Dual Degree)": "B.Tech + MBA (Dual Degree)",
    "Integrated B. Tech. and MBA": "B.Tech + MBA (Integrated)",
    "Integrated Bachelor of Science-Master of Science": "B.S. + M.S. (Integrated)",
    "Bachelor of Science and MBA (Dual Degree)": "B.S. + MBA (Dual Degree)",
    "B. Tech / B. Tech (Hons.)": "B.Tech",
}


def parse_program(program: str) -> tuple[str, float, str]:
    """"Computer Science and Engineering (4 Years, Bachelor of Technology)"
    -> ("Computer Science and Engineering", 4.0, "B.Tech")"""
    m = re.match(r"^(.*)\((\d+(?:\.\d+)?) Years?, (.*)\)\s*$", program)
    if not m:
        return program.strip(), 4.0, "B.Tech"
    branch, years, degree = m.group(1).strip(), float(m.group(2)), m.group(3).strip()
    return branch, years, DEGREES.get(degree, degree)


def parse_rank(value: str) -> int | None:
    value = value.strip()
    if not value or value.upper().endswith("P"):
        return None  # preparatory-course rank list
    try:
        return int(float(value))
    except ValueError:
        return None


def _remove_demo_colleges(db: Session, exam_ids: list[int]) -> int:
    """Sample colleges for these exams go once real data is in."""
    demo_ids = {
        cc.college_id
        for cc in db.query(CollegeCourse).filter(CollegeCourse.exam_id.in_(exam_ids)).all()
        if cc.college.is_demo_data
    }
    if not demo_ids:
        return 0
    cc_ids = [cc.id for cc in db.query(CollegeCourse).filter(CollegeCourse.college_id.in_(demo_ids)).all()]
    if cc_ids:
        db.query(Cutoff).filter(Cutoff.college_course_id.in_(cc_ids)).delete(synchronize_session=False)
        db.query(Fee).filter(Fee.college_course_id.in_(cc_ids)).delete(synchronize_session=False)
        db.query(CollegeCourse).filter(CollegeCourse.id.in_(cc_ids)).delete(synchronize_session=False)
    for model in (Hostel, Facility, Placement, NearbyPlace, CollegeReview):
        db.query(model).filter(model.college_id.in_(demo_ids)).delete(synchronize_session=False)
    db.query(College).filter(College.id.in_(demo_ids)).delete(synchronize_session=False)
    return len(demo_ids)


def seed_josaa(db: Session) -> dict:
    institutes = json.loads((DATA / "josaa_institutes.json").read_text())["institutes"]
    exams = {e.code: e for e in db.query(Exam).all()}
    jee_main, jee_adv = exams["JEE_MAIN"], exams["JEE_ADVANCED"]
    now = datetime.now(UTC)

    removed = _remove_demo_colleges(db, [jee_main.id, jee_adv.id])

    colleges = {c.canonical_name: c for c in db.query(College).all()}
    courses = {(c.name, c.duration_years): c for c in db.query(Course).all()}
    branches = {(b.course_id, b.name): b for b in db.query(Branch).all()}
    college_courses = {(cc.college_id, cc.course_id, cc.branch_id): cc for cc in db.query(CollegeCourse).all()}
    counts = {"rows": 0, "skipped": 0, "demo_colleges_removed": removed}

    for filename, year, round_no in TABLES:
        db.query(Cutoff).filter(Cutoff.source == SOURCE, Cutoff.year == year).delete(synchronize_session=False)
        with open(DATA / filename, newline="") as f:
            for row in csv.DictReader(f):
                category = CATEGORIES.get(row["seat_type"])
                opening, closing = parse_rank(row["opening_rank"]), parse_rank(row["closing_rank"])
                if category is None or closing is None:
                    counts["skipped"] += 1  # PwD seats and preparatory ranks
                    continue

                kind, city, state = institutes[row["institute"]]
                college = colleges.get(row["institute"])
                if college is None:
                    college = College(
                        canonical_name=row["institute"], college_type=kind, ownership="government",
                        state=state, city=city, is_demo_data=False,
                    )
                    db.add(college)
                    db.flush()
                    colleges[row["institute"]] = college

                branch_name, years, degree = parse_program(row["program"])
                course = courses.get((degree, years))
                if course is None:
                    course = Course(name=degree, level="UG", duration_years=years)
                    db.add(course)
                    db.flush()
                    courses[(degree, years)] = course
                branch = branches.get((course.id, branch_name))
                if branch is None:
                    code = re.sub(r"[^A-Z]", "", branch_name.title())[:12] or "GEN"
                    branch = Branch(course_id=course.id, name=branch_name, code=code)
                    db.add(branch)
                    db.flush()
                    branches[(course.id, branch_name)] = branch

                exam = jee_adv if kind in ("IIT", "IISc") else jee_main
                key = (college.id, course.id, branch.id)
                cc = college_courses.get(key)
                if cc is None:
                    cc = CollegeCourse(
                        college_id=college.id, course_id=course.id, branch_id=branch.id, exam_id=exam.id,
                        source=SOURCE, source_url=SOURCE_URL, academic_year=f"{year}-{str(year + 1)[-2:]}",
                        last_verified=now, verification_status="verified",
                    )
                    db.add(cc)
                    db.flush()
                    college_courses[key] = cc

                db.add(Cutoff(
                    college_course_id=cc.id, year=year, round=round_no, category=category,
                    quota=row["quota"], seat_type=row["gender"], opening_rank=opening, closing_rank=closing,
                    source=SOURCE, source_url=SOURCE_URL, academic_year=f"{year}-{str(year + 1)[-2:]}",
                    last_verified=now, verification_status="verified",
                ))
                counts["rows"] += 1
    db.commit()
    counts["colleges"] = sum(1 for c in colleges.values() if not c.is_demo_data)
    return counts


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("JoSAA data loaded:", seed_josaa(db))
    finally:
        db.close()


if __name__ == "__main__":
    run()
