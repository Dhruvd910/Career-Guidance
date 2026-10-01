from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.schemas.roadmap import RoadmapResponse
from app.services.roadmap_service import generate_roadmap

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])


@router.get("", response_model=RoadmapResponse)
def get_roadmap(
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> RoadmapResponse:
    return generate_roadmap(db, profile)
