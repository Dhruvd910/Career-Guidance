"""One-off (Phase 3, Step 4): every assessment taken with MAYA's original quiz becomes an
interests attempt in the new tables, dated when it was taken, so the history and career
directions include it. Safe to run again — an assessment already brought over is skipped.
The old `career_assessments` rows stay as they are.

    python scripts/migrate_legacy_assessments.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.assessment.service import import_answers  # noqa: E402
from app.models.assessment import AssessmentAttempt  # noqa: E402
from app.models.career import CareerAssessment  # noqa: E402
from app.models.student import StudentProfile  # noqa: E402


def migrate(db: Session) -> tuple[int, int]:
    """(brought over, skipped)."""
    done = set(db.execute(select(AssessmentAttempt.legacy_assessment_id)
                          .where(AssessmentAttempt.legacy_assessment_id.is_not(None))).scalars())
    moved = skipped = 0
    for old in db.execute(select(CareerAssessment).order_by(CareerAssessment.created_at)).scalars().all():
        answers = (old.responses or {}).get("answers")
        if old.id in done or not answers:
            skipped += 1  # already brought over, or the old slider form (no question-by-question answers)
            continue
        import_answers(db, db.get(StudentProfile, old.student_profile_id), answers,
                       legacy_assessment_id=old.id, completed_at=old.created_at)
        moved += 1
    return moved, skipped


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        moved, skipped = migrate(session)
    print(f"Brought over {moved} assessment(s); skipped {skipped}.")
