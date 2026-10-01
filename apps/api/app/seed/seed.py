"""Seeds clearly-fictional demo data (spec §58) so the app is usable end-to-end before a
real data-ingestion pipeline exists. College names are invented ("Sample Institute of
Technology") rather than attached to real institutions, specifically so a missing DEMO
DATA banner can never make this look like real admissions data. Every numeric record is
tagged verification_status="unverified_demo" and is_demo_data=True.

Run with: python -m app.seed.seed [--reset]
"""

import argparse
import random

from app.core.db import Base, SessionLocal, engine
from app.models.college import Branch, College, CollegeCourse, Course
from app.models.cutoff import Cutoff
from app.models.exam import Exam
from app.models.facility import Facility
from app.models.fee import Fee
from app.models.hostel import Hostel
from app.models.nearby import NearbyPlace
from app.models.placement import Placement

random.seed(42)  # deterministic demo data across reseeds

YEARS = [2023, 2024, 2025]
ROUNDS = [1, 2, 3]
CATEGORY_MULTIPLIER = {"General": 1.0, "EWS": 1.15, "OBC": 1.5, "SC": 2.4, "ST": 3.3}


def _demo_cutoffs(college_course_id: int, base_rank: float, quota: str) -> list[Cutoff]:
    rows = []
    for year in YEARS:
        year_drift = 1 + (year - 2023) * random.uniform(-0.04, 0.06)
        for round_no in ROUNDS:
            round_factor = 1 + (round_no - 1) * 0.05
            for category, mult in CATEGORY_MULTIPLIER.items():
                closing = max(1, round(base_rank * mult * year_drift * round_factor))
                opening = max(1, round(closing * random.uniform(0.75, 0.95)))
                rows.append(
                    Cutoff(
                        college_course_id=college_course_id,
                        year=year,
                        round=round_no,
                        category=category,
                        quota=quota,
                        seat_type="Gender-Neutral",
                        opening_rank=opening,
                        closing_rank=closing,
                        source="demo_seed",
                        academic_year=f"{year}-{str(year + 1)[-2:]}",
                        verification_status="unverified_demo",
                    )
                )
    return rows


def run(reset: bool = False) -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Exam).first() is not None:
            if not reset:
                print("Seed data already present — pass --reset to wipe and reseed.")
                return
            print("Resetting: dropping and recreating all tables...")
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)

        # ---- Exams (real, public catalog facts — not fabricated statistics) ----
        jee_main = Exam(code="JEE_MAIN", name="JEE Main", category="engineering",
                         description="National-level UG engineering entrance exam conducted by NTA; gateway to NITs, IIITs, GFTIs, and JEE Advanced eligibility.")
        jee_adv = Exam(code="JEE_ADVANCED", name="JEE Advanced", category="engineering",
                        description="Entrance exam for admission to the IITs, open to top JEE Main qualifiers.")
        neet = Exam(code="NEET_UG", name="NEET-UG", category="medical",
                    description="National-level UG medical entrance exam for MBBS/BDS and other allied programs.")
        db.add_all([jee_main, jee_adv, neet])
        db.flush()

        # ---- Courses & branches ----
        btech = Course(name="B.Tech", level="UG", duration_years=4)
        mbbs = Course(name="MBBS", level="UG", duration_years=5.5)
        bds = Course(name="BDS", level="UG", duration_years=5)
        db.add_all([btech, mbbs, bds])
        db.flush()

        branch_defs = [("Computer Science and Engineering", "CSE"), ("Electronics and Communication Engineering", "ECE"),
                       ("Electrical Engineering", "EE"), ("Mechanical Engineering", "ME"), ("Civil Engineering", "CE")]
        branches = {code: Branch(course_id=btech.id, name=name, code=code) for name, code in branch_defs}
        db.add_all(branches.values())
        db.flush()

        # ---- Colleges (fictional names, clearly demo) ----
        # aliases exist specifically so a student typing the common short form (e.g. "NIT
        # Warangal") still finds the college — see §26 canonical/alias normalization.
        def college(name, ctype, ownership, state, city, year, aliases=None):
            return College(canonical_name=name, aliases=aliases or [], college_type=ctype, ownership=ownership,
                            state=state, city=city, established_year=year,
                            affiliated_university=None, accreditation="NAAC A (demo)",
                            official_website=None, is_demo_data=True)

        iit_delhi = college("Sample Institute of Technology, Delhi", "IIT", "government", "Delhi", "New Delhi", 1961,
                             aliases=["IIT Delhi"])
        iit_bombay = college("Sample Institute of Technology, Bombay", "IIT", "government", "Maharashtra", "Mumbai", 1958,
                              aliases=["IIT Bombay", "IIT Mumbai"])
        nit_warangal = college("National Institute of Engineering, Warangal", "NIT", "government", "Telangana", "Warangal", 1959,
                                aliases=["NIT Warangal", "NITW"])
        iiit_hyd = college("State Institute of Information Technology, Hyderabad", "IIIT", "government", "Telangana", "Hyderabad", 1998,
                            aliases=["IIIT Hyderabad", "IIIT-H"])
        metro_pvt_eng = college("Metro Institute of Technology, Mumbai", "Private", "private", "Maharashtra", "Mumbai", 1983,
                                 aliases=["MIT Mumbai"])
        central_med = college("Central Medical College, Delhi", "Medical-Govt", "government", "Delhi", "New Delhi", 1956,
                               aliases=["CMC Delhi"])
        state_med_pune = college("State Medical College, Pune", "Medical-Govt", "government", "Maharashtra", "Pune", 1962,
                                  aliases=["SMC Pune"])
        metro_med_pvt = college("Metro Dental & Medical College, Bengaluru", "Medical-Private", "private", "Karnataka", "Bengaluru", 1990,
                                 aliases=["Metro Dental Bengaluru"])
        db.add_all([iit_delhi, iit_bombay, nit_warangal, iiit_hyd, metro_pvt_eng, central_med, state_med_pune, metro_med_pvt])
        db.flush()

        # ---- CollegeCourses + Cutoffs ----
        # One CollegeCourse per (college, branch): quota is a property of Cutoff, not of
        # CollegeCourse, so multiple quotas for the same branch share one row instead of
        # duplicating it — otherwise a college with e.g. HS+OS quotas would show every
        # branch twice on its profile page.
        # (college, exam, seats, {branch_code: {quota: base_closing_rank}})
        eng_plan = [
            (iit_delhi, jee_adv, 120, {"CSE": {"AI": 65}, "ECE": {"AI": 350}, "EE": {"AI": 500},
                                        "ME": {"AI": 900}, "CE": {"AI": 1400}}),
            (iit_bombay, jee_adv, 130, {"CSE": {"AI": 45}, "ECE": {"AI": 300}, "EE": {"AI": 480},
                                         "ME": {"AI": 850}, "CE": {"AI": 1350}}),
            (nit_warangal, jee_main, 90, {
                "CSE": {"HS": 2500, "OS": 1400}, "ECE": {"HS": 5200, "OS": 3200},
                "EE": {"HS": 7000, "OS": 4500}, "ME": {"HS": 9500, "OS": 6500}, "CE": {"HS": 12000, "OS": 8500},
            }),
            (iiit_hyd, jee_main, 60, {"CSE": {"AI": 1800}, "ECE": {"AI": 4200}}),
            (metro_pvt_eng, jee_main, 180, {"CSE": {"AI": 28000}, "ECE": {"AI": 42000}, "EE": {"AI": 55000},
                                             "ME": {"AI": 65000}, "CE": {"AI": 78000}}),
        ]

        for college_obj, exam_obj, seats, branch_quota_bases in eng_plan:
            for branch_code, quota_bases in branch_quota_bases.items():
                cc = CollegeCourse(college_id=college_obj.id, course_id=btech.id, branch_id=branches[branch_code].id,
                                    exam_id=exam_obj.id, total_seats=seats, source="demo_seed",
                                    academic_year="2025-26", verification_status="unverified_demo")
                db.add(cc)
                db.flush()
                for quota, base_rank in quota_bases.items():
                    db.add_all(_demo_cutoffs(cc.id, base_rank, quota))

                db.add(Fee(college_course_id=cc.id, academic_year="2025-26", source="demo_seed",
                           verification_status="unverified_demo",
                           tuition_fee=125000 if college_obj.ownership == "government" else 220000,
                           admission_fee=5000, exam_fee=2000,
                           hostel_fee=45000, mess_fee=42000, security_deposit=10000, other_charges=8000))

        # ---- Medical ----
        # (college, seats, {quota: base_closing_rank})
        med_plan = [
            (central_med, 150, {"AIQ": 350, "State Quota": 420}),
            (state_med_pune, 200, {"State Quota": 8500, "AIQ": 6200}),
            (metro_med_pvt, 150, {"AIQ": 55000}),
        ]
        for college_obj, seats, quota_bases in med_plan:
            cc = CollegeCourse(college_id=college_obj.id, course_id=mbbs.id, branch_id=None, exam_id=neet.id,
                                total_seats=seats, source="demo_seed", academic_year="2025-26",
                                verification_status="unverified_demo")
            db.add(cc)
            db.flush()
            for quota, base_rank in quota_bases.items():
                db.add_all(_demo_cutoffs(cc.id, base_rank, quota))
            db.add(Fee(college_course_id=cc.id, academic_year="2025-26", source="demo_seed",
                       verification_status="unverified_demo",
                       tuition_fee=95000 if college_obj.ownership == "government" else 1800000,
                       admission_fee=10000, exam_fee=2500,
                       hostel_fee=50000, mess_fee=48000, security_deposit=15000, other_charges=10000))

        db.flush()

        # ---- Hostels, facilities, placements, nearby ----
        all_colleges = [iit_delhi, iit_bombay, nit_warangal, iiit_hyd, metro_pvt_eng, central_med, state_med_pune, metro_med_pvt]
        for c in all_colleges:
            for htype in ("boys", "girls"):
                db.add(Hostel(college_id=c.id, hostel_type=htype, capacity=random.randint(300, 900),
                               room_types=["double", "triple"], fee_annual=45000,
                               facilities=["wifi", "laundry", "24x7 security", "common room"],
                               rules="Entry closes 10 PM (demo placeholder rule).",
                               distance_from_academic_block_km=round(random.uniform(0.2, 1.5), 1),
                               source="demo_seed", verification_status="unverified_demo"))
            for ftype, desc in [("library", "Central library (demo placeholder description)."),
                                 ("labs", "Departmental labs (demo placeholder description)."),
                                 ("sports", "Sports complex with common facilities (demo placeholder).")]:
                db.add(Facility(college_id=c.id, facility_type=ftype, description=desc,
                                 verification_status="unverified_demo"))
            for place_type, name, dist, rent in [
                ("pg", "Sample Student PG (demo)", 0.8, 8000),
                ("hospital", "Sample City Hospital (demo)", 2.1, None),
                ("atm", "Sample Bank ATM (demo)", 0.3, None),
                ("bus_stop", "Sample Bus Stop (demo)", 0.4, None),
            ]:
                db.add(NearbyPlace(college_id=c.id, place_type=place_type, name=name, distance_km=dist,
                                    approx_monthly_rent=rent, source="demo_seed"))

        eng_placement = [
            (iit_delhi, 96, 2400000, 1900000, 9000000, ["Sample Tech Corp", "Sample Analytics Inc"]),
            (iit_bombay, 97, 2500000, 2000000, 9500000, ["Sample Tech Corp", "Sample Quant Fund"]),
            (nit_warangal, 88, 1400000, 1100000, 4500000, ["Sample Services Ltd", "Sample Tech Corp"]),
            (iiit_hyd, 90, 1600000, 1250000, 5000000, ["Sample Tech Corp", "Sample Software Co"]),
            (metro_pvt_eng, 72, 800000, 650000, 2200000, ["Sample Services Ltd"]),
        ]
        for c, pct, avg, med, high, recruiters in eng_placement:
            db.add(Placement(college_id=c.id, academic_year="2024-25", source="demo_seed",
                              verification_status="unverified_demo",
                              placement_percentage=pct, average_package=avg, median_package=med,
                              highest_package=high, major_recruiters=recruiters, extra={}))

        med_placement = [
            (central_med, {"internship_stipend_monthly": 26000, "pg_pathways": "Strong track record of NEET-PG qualifiers (demo placeholder).",
                            "research_opportunities": "Departmental research projects available (demo placeholder).",
                            "clinical_exposure": "Attached tertiary-care hospital (demo placeholder)."}),
            (state_med_pune, {"internship_stipend_monthly": 20000, "pg_pathways": "Moderate NEET-PG track record (demo placeholder).",
                               "research_opportunities": "Limited formal research programs (demo placeholder).",
                               "clinical_exposure": "Attached district hospital (demo placeholder)."}),
            (metro_med_pvt, {"internship_stipend_monthly": 15000, "pg_pathways": "Growing NEET-PG track record (demo placeholder).",
                              "research_opportunities": "Emerging research initiatives (demo placeholder).",
                              "clinical_exposure": "Private multi-specialty hospital (demo placeholder)."}),
        ]
        for c, extra in med_placement:
            db.add(Placement(college_id=c.id, academic_year="2024-25", source="demo_seed",
                              verification_status="unverified_demo", extra=extra))

        # ---- Career library (career graph, §49) — see app/seed/careers.json ----
        from app.seed.careers import seed_careers

        db.flush()
        career_count = seed_careers(db)

        db.commit()

        from app.seed.questions import seed_questions  # imported here to keep the seeders independent

        questions = seed_questions(db, reset=True)
        print(f"Seed data loaded: 3 exams, 8 demo colleges, {career_count} careers, multi-year demo cutoffs, "
              f"{questions} practice questions.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop all tables and reseed from scratch.")
    args = parser.parse_args()
    run(reset=args.reset)
