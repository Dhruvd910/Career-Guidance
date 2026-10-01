"""The career engine and knowledge graph over HTTP (docs/design/07-api-contracts.md §5,
13-phase4-plan.md Step 6). The older catalogue stays at /api/careers."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.knowledge import engine
from app.knowledge.graph_store import graph
from app.models.student import StudentProfile

router = APIRouter(prefix="/api/career", tags=["career"])
skills_router = APIRouter(prefix="/api/skills", tags=["career"])

STREAMS = {"pcm", "pcb", "pcmb", "commerce", "humanities"}


@router.get("/options")
def options(profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> dict:
    """Personalised directions by domain, each with required education, pathways, skill gaps (only
    where measured), colleges on record and reasons from memory. Never one answer."""
    return engine.options(db, profile)


@router.get("/explore")
def explore(db: Session = Depends(get_db)) -> dict:
    """The exploration tree (spec §11): every domain and its careers."""
    return {"domains": graph(db).domain_tree()}


@router.get("/stream/{stream}")
def stream(stream: str, db: Session = Depends(get_db)) -> dict:
    """What a class 11-12 stream keeps open, opens with an optional subject, or closes — and why."""
    if stream.lower() not in STREAMS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Streams are {sorted(STREAMS)}.")
    return graph(db).open_by_stream(f"stream:{stream.lower()}")


@router.get("/{career_key}/colleges")
def colleges(career_key: str, state: str | None = None, city: str | None = None, limit: int = Query(25, le=100),
             db: Session = Depends(get_db)) -> dict:
    """Colleges with an official 2026 programme on a route into this career. No fees or
    facilities: those aren't collected yet."""
    store = graph(db)
    if store.node(f"career:{career_key}") is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Career not found")
    return store.colleges_for(f"career:{career_key}", state=state, city=city, limit=limit)


@router.get("/{career_key}")
def career(career_key: str, profile: StudentProfile = Depends(get_current_student_profile),
           db: Session = Depends(get_db)) -> dict:
    """One career in full, for this student: band and reasons (if assessed), required education,
    pathways, skills with their results, a learning path, related careers, colleges, sources."""
    found = engine.explain(db, profile, career_key)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Career not found")
    return found


@skills_router.get("/{skill_key}/path")
def skill_path(skill_key: str, db: Session = Depends(get_db)) -> dict:
    """What to learn first for one skill, in order, and what builds each step."""
    store = graph(db)
    key = skill_key if skill_key.startswith("skill:") else f"skill:{skill_key}"
    if store.node(key) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found")
    path = store.prerequisite_path([key])
    return {"skill": key, "path": [{**step, "try": store.developed_by(step["key"])} for step in path]}
