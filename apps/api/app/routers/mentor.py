"""The continuous mentor (Phase 7): the brief (spec §37's eight questions) and the agenda."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.mentor import agenda as agenda_module, shortlist
from app.mentor.brief import brief
from app.models.student import StudentProfile

router = APIRouter(prefix="/api/mentor", tags=["mentor"])


class Mark(BaseModel):
    key: str
    what: str  # done | not_now | raised


@router.get("/brief")
def get_brief(db: Session = Depends(get_db), profile: StudentProfile = Depends(get_current_student_profile)) -> dict:
    return brief(db, profile)


@router.get("/agenda")
def get_agenda(db: Session = Depends(get_db), profile: StudentProfile = Depends(get_current_student_profile)) -> list[dict]:
    return [i.as_dict() for i in agenda_module.agenda(db, profile)]


@router.post("/agenda/mark")
def mark(body: Mark, db: Session = Depends(get_db), profile: StudentProfile = Depends(get_current_student_profile)) -> dict:
    if body.what not in ("done", "not_now", "raised"):
        raise HTTPException(status_code=400, detail="what must be done, not_now or raised")
    row = agenda_module.mark(db, profile, body.key, body.what)
    db.commit()
    return {"key": row.key, "status": row.status, "snoozed_until": row.snoozed_until}


class Pick(BaseModel):
    college_id: int


@router.get("/shortlist")
def get_shortlist(db: Session = Depends(get_db), profile: StudentProfile = Depends(get_current_student_profile)) -> list[dict]:
    """The student's shortlisted colleges, each with its key facts, sources and freshness."""
    return shortlist.items(db, profile)


@router.post("/shortlist")
def add_to_shortlist(body: Pick, db: Session = Depends(get_db),
                     profile: StudentProfile = Depends(get_current_student_profile)) -> dict:
    try:
        return shortlist.add(db, profile, body.college_id)
    except shortlist.ShortlistError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/shortlist/{college_id}")
def remove_from_shortlist(college_id: int, db: Session = Depends(get_db),
                          profile: StudentProfile = Depends(get_current_student_profile)) -> dict:
    return shortlist.remove(db, profile, college_id)
