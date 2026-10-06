"""Learn: where to learn each topic of a career path — topic videos (English and Hindi) and a
YouTube search, as links the Pi shows with QR codes (app/knowledge/learning.py)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.knowledge import learning
from app.knowledge.graph_store import graph
from app.models.student import StudentProfile

router = APIRouter(prefix="/api/learn", tags=["learn"])


@router.get("")
def learning_plan(career: str | None = None, profile: StudentProfile = Depends(get_current_student_profile),
                  db: Session = Depends(get_db)) -> dict:
    """The skills of a career in learning order, each with its status and where to learn it. Without
    `career`: the roadmap's focus, else the strongest career direction, else none (pick one)."""
    return learning.learning_plan(db, profile, career)


@router.get("/skill/{skill_key}")
def skill(skill_key: str, db: Session = Depends(get_db)) -> dict:
    key = skill_key if skill_key.startswith("skill:") else f"skill:{skill_key}"
    node = graph(db).node(key)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such skill")
    return {"skill": key, "name": node["name"], **learning.for_skill(key, node["name"]["en"])}
