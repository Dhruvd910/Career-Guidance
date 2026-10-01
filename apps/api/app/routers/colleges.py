from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.summarize import generate_college_comparison_summary
from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.schemas.college import (
    CollegeCompareRequest,
    CollegeCompareResponse,
    CollegeDetail,
    CollegeReviewCreate,
    CollegeReviewOut,
    CollegeSummary,
    CutoffOut,
    FeeOut,
    HostelOut,
    NearbyPlaceOut,
    PlacementOut,
)
from app.services import college_service

router = APIRouter(prefix="/api/colleges", tags=["colleges"])


@router.get("", response_model=list[CollegeSummary])
def list_colleges(
    q: str | None = None,
    exam_code: str | None = None,
    state: str | None = None,
    city: str | None = None,
    ownership: str | None = None,
    college_type: str | None = None,
    course_name: str | None = None,
    db: Session = Depends(get_db),
) -> list[CollegeSummary]:
    return college_service.search_colleges(
        db, q=q, exam_code=exam_code, state=state, city=city,
        ownership=ownership, college_type=college_type, course_name=course_name,
    )


@router.post("/compare", response_model=CollegeCompareResponse)
async def compare(payload: CollegeCompareRequest, db: Session = Depends(get_db)) -> CollegeCompareResponse:
    result = college_service.compare_colleges(db, payload.college_ids)
    result.ai_summary = await generate_college_comparison_summary([row.model_dump() for row in result.rows])
    return result


@router.get("/{college_id}", response_model=CollegeDetail)
def get_college(college_id: int, db: Session = Depends(get_db)) -> CollegeDetail:
    college = college_service.get_college_or_404(db, college_id)
    return college_service.to_detail(db, college)


@router.get("/{college_id}/cutoffs", response_model=list[CutoffOut])
def get_cutoffs(
    college_id: int, category: str | None = None, branch_name: str | None = None, db: Session = Depends(get_db)
) -> list[CutoffOut]:
    return college_service.get_cutoffs(db, college_id, category, branch_name)


@router.get("/{college_id}/fees", response_model=list[FeeOut])
def get_fees(college_id: int, db: Session = Depends(get_db)) -> list[FeeOut]:
    return college_service.get_fees(db, college_id)


@router.get("/{college_id}/hostel", response_model=list[HostelOut])
def get_hostel(college_id: int, db: Session = Depends(get_db)) -> list[HostelOut]:
    return college_service.get_hostels(db, college_id)


@router.get("/{college_id}/placements", response_model=list[PlacementOut])
def get_placements(college_id: int, db: Session = Depends(get_db)) -> list[PlacementOut]:
    return college_service.get_placements(db, college_id)


@router.get("/{college_id}/nearby", response_model=list[NearbyPlaceOut])
def get_nearby(college_id: int, db: Session = Depends(get_db)) -> list[NearbyPlaceOut]:
    return college_service.get_nearby(db, college_id)


@router.get("/{college_id}/reviews", response_model=list[CollegeReviewOut])
def get_reviews(college_id: int, db: Session = Depends(get_db)) -> list[CollegeReviewOut]:
    return college_service.get_reviews(db, college_id)


@router.post("/{college_id}/reviews", response_model=CollegeReviewOut, status_code=201)
def add_review(
    college_id: int,
    payload: CollegeReviewCreate,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> CollegeReviewOut:
    return college_service.add_review(db, college_id, profile, payload)
