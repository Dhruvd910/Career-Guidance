from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.exam import Exam, ExamProfile
from app.models.student import StudentProfile
from app.schemas.exam import ExamProfileOut, ExamProfileUpsert


def list_exams(db: Session) -> list[Exam]:
    return db.query(Exam).filter(Exam.is_active.is_(True)).all()


def get_exam_by_code(db: Session, code: str) -> Exam:
    exam = db.query(Exam).filter(Exam.code == code.upper()).first()
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown exam code '{code}'")
    return exam


def upsert_exam_profile(db: Session, profile: StudentProfile, payload: ExamProfileUpsert) -> ExamProfile:
    exam = get_exam_by_code(db, payload.exam_code)

    exam_profile = (
        db.query(ExamProfile)
        .filter(ExamProfile.student_profile_id == profile.id, ExamProfile.exam_id == exam.id)
        .first()
    )
    data = payload.model_dump(exclude={"exam_code"})
    if exam_profile is None:
        exam_profile = ExamProfile(student_profile_id=profile.id, exam_id=exam.id, **data)
        db.add(exam_profile)
    else:
        for field, value in data.items():
            setattr(exam_profile, field, value)

    # Saving an exam profile says what the student is aiming at — but only sets the goal when
    # none is chosen yet: a NEET student checking JEE cutoffs out of curiosity keeps NEET.
    if profile.target_exam_code in (None, "careers"):
        profile.target_exam_code = exam.code

    db.commit()
    db.refresh(exam_profile)
    return exam_profile


def get_exam_profile(db: Session, profile: StudentProfile, exam_code: str) -> ExamProfile:
    exam = get_exam_by_code(db, exam_code)
    exam_profile = (
        db.query(ExamProfile)
        .filter(ExamProfile.student_profile_id == profile.id, ExamProfile.exam_id == exam.id)
        .first()
    )
    if exam_profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No exam profile yet for this exam")
    return exam_profile


def to_out(exam_profile: ExamProfile) -> ExamProfileOut:
    return ExamProfileOut(
        id=exam_profile.id,
        student_profile_id=exam_profile.student_profile_id,
        exam_code=exam_profile.exam.code,
        status=exam_profile.status,
        attempt_year=exam_profile.attempt_year,
        score=exam_profile.score,
        percentile=exam_profile.percentile,
        rank=exam_profile.rank,
        category_rank=exam_profile.category_rank,
        extra=exam_profile.extra,
        preferred_branches=exam_profile.preferred_branches,
        preferred_states=exam_profile.preferred_states,
        preferred_cities=exam_profile.preferred_cities,
        college_type_preference=exam_profile.college_type_preference,
        budget_max=exam_profile.budget_max,
    )
