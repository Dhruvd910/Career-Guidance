from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.schemas.mock_test import MockTestCreate, MockTestDashboard, MockTestOut
from app.services.mock_test_service import build_dashboard, create_mock_test, list_mock_tests

router = APIRouter(prefix="/api/mock-tests", tags=["mock-tests"])


@router.post("", response_model=MockTestOut, status_code=201)
def add_mock_test(
    payload: MockTestCreate,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> MockTestOut:
    mock_test = create_mock_test(db, profile, payload)
    return MockTestOut(
        id=mock_test.id,
        student_profile_id=mock_test.student_profile_id,
        exam_code=payload.exam_code,
        test_name=mock_test.test_name,
        test_date=mock_test.test_date,
        total_score=mock_test.total_score,
        max_score=mock_test.max_score,
        percentile=mock_test.percentile,
        estimated_rank=mock_test.estimated_rank,
        subject_scores=mock_test.subject_scores,
    )


@router.get("/history", response_model=list[MockTestOut])
def get_history(
    exam_code: str | None = None,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> list[MockTestOut]:
    tests = list_mock_tests(db, profile, exam_code)
    return [
        MockTestOut(
            id=t.id,
            student_profile_id=t.student_profile_id,
            exam_code=t.exam.code,
            test_name=t.test_name,
            test_date=t.test_date,
            total_score=t.total_score,
            max_score=t.max_score,
            percentile=t.percentile,
            estimated_rank=t.estimated_rank,
            subject_scores=t.subject_scores,
        )
        for t in tests
    ]


@router.get("/dashboard", response_model=MockTestDashboard)
def get_dashboard(
    exam_code: str | None = None,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> MockTestDashboard:
    return build_dashboard(db, profile, exam_code)
