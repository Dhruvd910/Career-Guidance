from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.schemas.exam import ExamOut, ExamProfileOut, ExamProfileUpsert
from app.services.exam_service import get_exam_profile, list_exams, to_out, upsert_exam_profile

router = APIRouter(prefix="/api/exams", tags=["exams"])


@router.get("", response_model=list[ExamOut])
def get_exams(db: Session = Depends(get_db)) -> list[ExamOut]:
    return list_exams(db)


@router.post("/profile", response_model=ExamProfileOut)
def save_exam_profile(
    payload: ExamProfileUpsert,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> ExamProfileOut:
    exam_profile = upsert_exam_profile(db, profile, payload)
    return to_out(exam_profile)


@router.get("/{exam_code}/profile", response_model=ExamProfileOut)
def read_exam_profile(
    exam_code: str,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> ExamProfileOut:
    exam_profile = get_exam_profile(db, profile, exam_code)
    return to_out(exam_profile)
