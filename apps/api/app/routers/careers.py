from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.career import CareerOption
from app.models.student import StudentProfile
from app.schemas.career import CareerAssessmentOut, CareerAssessmentRequest, CareerOptionOut
from app.services.assessment_engine import load_bank
from app.services.career_service import list_career_options, run_career_assessment

router = APIRouter(prefix="/api/careers", tags=["careers"])


@router.get("", response_model=list[CareerOptionOut])
def get_careers(db: Session = Depends(get_db)) -> list[CareerOptionOut]:
    return list_career_options(db)


@router.get("/assessment/questions")
def assessment_questions() -> dict:
    """MAYA's assessment conversation: the questions, their options, and which follow-ups
    depend on which answers. Weights are included — nothing about the scoring is secret."""
    return load_bank()


@router.get("/key/{career_key}", response_model=CareerOptionOut)
def get_career_by_key(career_key: str, db: Session = Depends(get_db)) -> CareerOptionOut:
    career = db.query(CareerOption).filter(CareerOption.key == career_key).first()
    if career is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Career not found")
    return career


@router.get("/{career_id}", response_model=CareerOptionOut)
def get_career(career_id: int, db: Session = Depends(get_db)) -> CareerOptionOut:
    career = db.get(CareerOption, career_id)
    if career is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Career not found")
    return career


@router.post("/assessment", response_model=CareerAssessmentOut, status_code=201)
def submit_assessment(
    payload: CareerAssessmentRequest,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> CareerAssessmentOut:
    assessment, highlights = run_career_assessment(db, profile, payload)
    return CareerAssessmentOut(
        id=assessment.id,
        student_profile_id=assessment.student_profile_id,
        assessment_type=assessment.assessment_type,
        results=assessment.results,
        highlights=highlights,
        created_at=assessment.created_at,
    )
