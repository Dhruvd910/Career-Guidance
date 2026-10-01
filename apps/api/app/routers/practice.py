from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.schemas.practice import AttemptOut, AttemptSummary, PracticeOptions, StartAttemptRequest, SubmitAttemptRequest
from app.services.practice_service import (
    get_attempt_summary, get_options, list_attempts, start_attempt, submit_attempt,
)

router = APIRouter(prefix="/api/practice", tags=["practice"])


@router.get("/options", response_model=PracticeOptions)
def practice_options(
    exam_code: str = Query(..., description="JEE_MAIN | JEE_ADVANCED | NEET_UG"),
    _profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> PracticeOptions:
    return get_options(db, exam_code)


@router.post("/start", response_model=AttemptOut, status_code=201)
def start(
    payload: StartAttemptRequest,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> AttemptOut:
    return start_attempt(db, profile, payload)


@router.post("/{attempt_id}/submit", response_model=AttemptSummary)
def submit(
    attempt_id: int,
    payload: SubmitAttemptRequest,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> AttemptSummary:
    return submit_attempt(db, profile, attempt_id, payload)


@router.get("/attempts", response_model=list[AttemptSummary])
def attempts(
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> list[AttemptSummary]:
    return list_attempts(db, profile)


@router.get("/attempts/{attempt_id}", response_model=AttemptSummary)
def attempt_detail(
    attempt_id: int,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> AttemptSummary:
    return get_attempt_summary(db, profile, attempt_id)
