"""The roadmap and progress over HTTP (docs/design/07-api-contracts.md §6, 14-phase5-plan.md).

The old one-size template moved to /api/roadmap/legacy — the JEE/NEET chapter-by-chapter study
plan still comes from it."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.roadmap import progress, service
from app.roadmap.service import RoadmapError
from app.schemas.roadmap import RoadmapResponse
from app.services.roadmap_service import generate_roadmap

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])
progress_router = APIRouter(prefix="/api/progress", tags=["roadmap"])


class Recalculate(BaseModel):
    kind: str  # time_budget | difficulty | interest_change | focus | manual
    detail: str = Field(default="", max_length=300)
    hours_per_week: int | None = None
    subject: str | None = None
    career: str | None = None
    dropping: str | None = None


class Focus(BaseModel):
    career: str


class ProgressUpdate(BaseModel):
    node_key: str
    status: str  # not_started | in_progress | done | skipped
    percent: int | None = None
    note: str | None = Field(default=None, max_length=300)


def _fail(e: RoadmapError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND if e.not_found else status.HTTP_400_BAD_REQUEST, str(e))


@router.get("")
def roadmap(version: int | None = None, profile: StudentProfile = Depends(get_current_student_profile),
            db: Session = Depends(get_db)) -> dict:
    """The roadmap tree with progress — the latest version, or `?version=n` from its history."""
    try:
        return service.view(db, profile, version)
    except RoadmapError as e:
        raise _fail(e) from e


@router.get("/legacy", response_model=RoadmapResponse)
def legacy(profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> RoadmapResponse:
    return generate_roadmap(db, profile)


@router.get("/versions")
def versions(profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> list[dict]:
    return service.versions(db, profile)


@router.get("/next-step")
def next_step(profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> dict:
    return {"next_step": service.next_step(db, profile)}


@router.post("/recalculate")
def recalculate(body: Recalculate, profile: StudentProfile = Depends(get_current_student_profile),
                db: Session = Depends(get_db)) -> dict:
    """One of spec §19's changes → a new version, with what changed and why."""
    try:
        return service.adapt(db, profile, body.kind, detail=body.detail, hours_per_week=body.hours_per_week,
                             subject=body.subject, career=body.career, dropping=body.dropping)
    except RoadmapError as e:
        raise _fail(e) from e


@router.post("/focus")
def focus(body: Focus, profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> dict:
    try:
        return service.adapt(db, profile, "focus", career=body.career)
    except RoadmapError as e:
        raise _fail(e) from e


@progress_router.get("")
def my_progress(profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> dict:
    return progress.summary(db, profile)


@progress_router.post("/update")
def update(body: ProgressUpdate, profile: StudentProfile = Depends(get_current_student_profile),
           db: Session = Depends(get_db)) -> dict:
    try:
        return service.update_progress(db, profile, body.node_key, body.status, body.percent, body.note)
    except RoadmapError as e:
        raise _fail(e) from e
