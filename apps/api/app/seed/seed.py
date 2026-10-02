"""Seeds the reference catalogue: the exams, courses and branches, the career library and the
practice questions. No colleges: real ones come from the official JoSAA and MCC tables
(app.seed.josaa, app.seed.mcc), and everything else about them from the OKF bundle (Phase 6).
Fictional colleges live only in the tests.

Run with: python -m app.seed.seed [--reset]
"""

import argparse

from app.core.db import Base, SessionLocal, engine
from app.models.college import Branch, Course
from app.models.exam import Exam

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

        # ---- Career library (career graph, §49) — see app/seed/careers.json ----
        from app.seed.careers import seed_careers

        db.flush()
        career_count = seed_careers(db)

        db.commit()

        from app.seed.questions import seed_questions  # imported here to keep the seeders independent

        questions = seed_questions(db, reset=True)
        print(f"Seed data loaded: 3 exams, {career_count} careers, {questions} practice questions. "
              "Colleges come from the official tables: python -m app.seed.josaa and app.seed.mcc.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop all tables and reseed from scratch.")
    args = parser.parse_args()
    run(reset=args.reset)
