from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.schemas.student import (
    AcademicRecordCreate,
    AcademicRecordOut,
    NextOnboardingStep,
    StudentProfileOut,
    StudentProfileUpdate,
)
from app.services.student_service import add_academic_record, get_next_onboarding_step, update_profile

router = APIRouter(prefix="/api/student", tags=["student"])


@router.get("/profile", response_model=StudentProfileOut)
def read_profile(profile: StudentProfile = Depends(get_current_student_profile)) -> StudentProfile:
    return profile


@router.put("/profile", response_model=StudentProfileOut)
def edit_profile(
    payload: StudentProfileUpdate,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> StudentProfile:
    return update_profile(db, profile, payload)


@router.post("/academic-record", response_model=AcademicRecordOut, status_code=201)
def create_academic_record(
    payload: AcademicRecordCreate,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> AcademicRecordOut:
    return add_academic_record(db, profile, payload)


@router.get("/onboarding/next-step", response_model=NextOnboardingStep)
def onboarding_next_step(
    profile: StudentProfile = Depends(get_current_student_profile),
) -> NextOnboardingStep:
    return get_next_onboarding_step(profile)
