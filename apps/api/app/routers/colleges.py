from fastapi import APIRouter, Depends, HTTPException
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
)
from app.facts import discover, topics
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


@router.get("/discover")
def discover_colleges(career: str | None = None, degree: str | None = None, state: str | None = None,
                      exam: str | None = None, home: str | None = None, home_state: str | None = None,
                      radius_km: float | None = None, budget_max: int | None = None, hostel: bool = False,
                      medical: bool = False, sort: str = "name", limit: int = 50, db: Session = Depends(get_db)) -> dict:
    """Career or degree → colleges offering it → the student's filters → plain attributes, sorted by
    what the student chose (name, distance, fee, nirf). No overall score. Colleges left out because
    something isn't known are counted in `left_out`."""
    if sort not in discover.SORTS:
        raise HTTPException(status_code=400, detail=f"sort must be one of {list(discover.SORTS)}")
    return discover.discover(db, career=career, degree=degree, state=state, exam=exam, home=home, home_state=home_state,
                             radius_km=radius_km, budget_max=budget_max, hostel=hostel, medical=medical, sort=sort,
                             limit=min(limit, 200))


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


@router.get("/{college_id}/facts")
def get_facts(college_id: int, topic: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Everything MAYA knows about the college from outside, each value with its source, academic
    year and freshness (a FactView); `topic` narrows it to fees, campus, location, admissions,
    rankings or placements."""
    college_service.get_college_or_404(db, college_id)
    if topic is not None and topic not in topics.TOPICS:
        raise HTTPException(status_code=400, detail=f"topic must be one of {sorted(topics.TOPICS)}")
    return {"college_id": college_id, "facts": topics.facts(db, college_id, topic)}


@router.get("/{college_id}/sources")
def get_sources(college_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Every document behind what MAYA shows about this college, best tier first."""
    college_service.get_college_or_404(db, college_id)
    return college_service.sources_for(db, college_id)


@router.post("/{college_id}/refresh")
def request_refresh(college_id: int, db: Session = Depends(get_db)) -> dict:
    """'Check for updates': the college is looked at first in tonight's refresh. Asking twice
    before then doesn't queue it twice."""
    from app.models.facts import RefreshRequest

    college_service.get_college_or_404(db, college_id)
    waiting = db.query(RefreshRequest).filter(RefreshRequest.college_id == college_id, RefreshRequest.done_at.is_(None)).first()
    if waiting is None:
        db.add(RefreshRequest(college_id=college_id))
        db.commit()
    return {"queued": True, "message": "MAYA will check this college's official sources again tonight."}


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
