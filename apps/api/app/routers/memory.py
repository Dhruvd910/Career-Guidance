"""Consent and the student's view of their own memory (spec §6, DPDP)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.memory import consent as consent_service
from app.memory.opening import counselling_state
from app.models.memory import (
    CounsellingThread, DataRequest, MemoryItem, SessionSummary, StudentConstraint, StudentEvent, StudentGoal,
    StudentInterest,
)
from app.models.student import StudentProfile

router = APIRouter(prefix="/api/consent", tags=["memory"])


class Guardian(BaseModel):
    name: str
    relationship: str  # mother, father, guardian…
    contact: str  # phone or email


class ConsentState(BaseModel):
    granted: bool
    granted_by: str | None = None
    verification: str | None = None
    decided_at: datetime | None = None


class ConsentOverview(BaseModel):
    is_minor: bool  # a guardian has to decide
    notice_version: str
    notice: dict[str, str]  # {"en": …, "hi": …}
    long_term_memory: ConsentState
    emotion_signals: ConsentState


class ConsentDecision(BaseModel):
    kind: str  # long_term_memory | emotion_signals
    granted: bool
    guardian: Guardian | None = None


class ConsentResult(BaseModel):
    kind: str
    state: ConsentState
    deleted: dict[str, int] = {}  # on withdrawal: what was removed, per table


def _state(db: Session, profile: StudentProfile, kind: str) -> ConsentState:
    decision = consent_service.current(db, profile, kind)
    if decision is None:
        return ConsentState(granted=False)
    return ConsentState(granted=decision.granted, granted_by=decision.granted_by,
                        verification=decision.verification, decided_at=decision.decided_at)


@router.get("", response_model=ConsentOverview)
def overview(profile: StudentProfile = Depends(get_current_student_profile),
             db: Session = Depends(get_db)) -> ConsentOverview:
    return ConsentOverview(
        is_minor=consent_service.is_minor(profile), notice_version=consent_service.NOTICE_VERSION,
        notice=consent_service.NOTICE,
        long_term_memory=_state(db, profile, consent_service.LONG_TERM_MEMORY),
        emotion_signals=_state(db, profile, consent_service.EMOTION_SIGNALS),
    )


@router.post("", response_model=ConsentResult)
def decide(payload: ConsentDecision, profile: StudentProfile = Depends(get_current_student_profile),
           db: Session = Depends(get_db)) -> ConsentResult:
    try:
        _consent, deleted = consent_service.decide(
            db, profile, payload.kind, payload.granted, payload.guardian.model_dump() if payload.guardian else None)
    except consent_service.ConsentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return ConsentResult(kind=payload.kind, state=_state(db, profile, payload.kind), deleted=deleted)


# ---------------- the student's view of their own memory ----------------

memory_router = APIRouter(prefix="/api/student", tags=["memory"])
counselling_router = APIRouter(prefix="/api/counselling", tags=["memory"])

# What a student can delete one at a time, by the name the API uses.
DELETABLE = {"memory": MemoryItem, "interest": StudentInterest, "goal": StudentGoal, "constraint": StudentConstraint,
             "thread": CounsellingThread}


class ThreadOut(BaseModel):
    id: int
    title: str
    status: str
    decision_status: str
    current_position: str
    open_questions: list[str]
    next_step: str | None
    last_touched_at: datetime

    model_config = {"from_attributes": True}


class ItemOut(BaseModel):
    id: int
    text: str
    kind: str | None = None
    sensitive: bool = False
    created_at: datetime | None = None


class SummaryOut(BaseModel):
    session_id: int
    summary: str
    decisions: list[str]
    next_steps: list[str]
    created_at: datetime


class MemoryOverview(BaseModel):
    enabled: bool  # the long-term memory permission
    threads: list[ThreadOut]
    interests: list[ItemOut]
    goals: list[ItemOut]
    constraints: list[ItemOut]
    memories: list[ItemOut]
    recent_sessions: list[SummaryOut]


class EventOut(BaseModel):
    id: int
    event_type: str
    occurred_at: datetime
    description: str
    reason: str | None


class Deleted(BaseModel):
    deleted: dict[str, int]


def _own(db: Session, model, profile: StudentProfile):
    return select(model).where(model.student_profile_id == profile.id)


@memory_router.get("/memory", response_model=MemoryOverview)
def my_memory(profile: StudentProfile = Depends(get_current_student_profile),
              db: Session = Depends(get_db)) -> MemoryOverview:
    """Everything MAYA remembers about the student — private items included: it's theirs."""
    threads = db.execute(_own(db, CounsellingThread, profile).order_by(CounsellingThread.last_touched_at.desc())).scalars()
    interests = db.execute(_own(db, StudentInterest, profile).where(StudentInterest.status == "active")).scalars()
    goals = db.execute(_own(db, StudentGoal, profile).where(StudentGoal.status == "active")).scalars()
    constraints = db.execute(_own(db, StudentConstraint, profile).where(StudentConstraint.status == "active")).scalars()
    memories = db.execute(_own(db, MemoryItem, profile).where(MemoryItem.status == "active")
                          .order_by(MemoryItem.created_at.desc())).scalars()
    sessions = db.execute(_own(db, SessionSummary, profile).order_by(SessionSummary.created_at.desc()).limit(10)).scalars()
    return MemoryOverview(
        enabled=consent_service.allowed(db, profile, consent_service.LONG_TERM_MEMORY),
        threads=[ThreadOut.model_validate(t) for t in threads],
        interests=[ItemOut(id=i.id, text=i.label, created_at=i.created_at) for i in interests],
        goals=[ItemOut(id=g.id, text=g.title, kind=g.kind, created_at=g.created_at) for g in goals],
        constraints=[ItemOut(id=c.id, text=c.detail, kind=c.kind, sensitive=c.sensitivity != "normal",
                             created_at=c.created_at) for c in constraints],
        memories=[ItemOut(id=m.id, text=m.text, kind=m.kind, sensitive=m.sensitivity != "normal",
                          created_at=m.created_at) for m in memories],
        recent_sessions=[SummaryOut(session_id=s.conversation_id, summary=s.summary, decisions=s.decisions,
                                    next_steps=s.next_steps, created_at=s.created_at) for s in sessions],
    )


@memory_router.delete("/memory/{kind}/{item_id}", response_model=Deleted)
def forget_one(kind: str, item_id: int, profile: StudentProfile = Depends(get_current_student_profile),
               db: Session = Depends(get_db)) -> Deleted:
    model = DELETABLE.get(kind)
    item = db.get(model, item_id) if model else None
    if item is None or item.student_profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if model is MemoryItem:  # anything it superseded no longer points at it
        db.execute(MemoryItem.__table__.update().where(MemoryItem.superseded_by == item.id).values(superseded_by=None))
    db.delete(item)
    db.add(DataRequest(student_profile_id=profile.id, kind=f"delete_{kind}", detail={"id": item_id}))
    db.commit()
    return Deleted(deleted={model.__tablename__: 1})


@memory_router.delete("/memory", response_model=Deleted)
def forget_everything(profile: StudentProfile = Depends(get_current_student_profile),
                      db: Session = Depends(get_db)) -> Deleted:
    """Clears what MAYA remembers; the permission itself stays as it was."""
    counts = consent_service.forget(db, profile, consent_service.LONG_TERM_MEMORY, reason="student asked")
    db.commit()
    return Deleted(deleted=counts)


def _describe(event: StudentEvent) -> str:
    p = event.payload or {}
    what = {
        "CAREER_INTEREST_ADDED": f"New interest: {p.get('label')}",
        "CAREER_INTEREST_REMOVED": f"No longer interested in {p.get('label')}",
        "GOAL_CREATED": f"New goal: {p.get('title')}",
        "GOAL_COMPLETED": f"Goal done: {p.get('title')}",
        "DECISION_MADE": f"Decided: {p.get('title')}",
        "DECISION_REOPENED": f"Thinking again about: {p.get('title')}",
        "COUNSELLING_SESSION": f"Talked with MAYA: {p.get('summary', '')}",
        "PROFILE_UPDATED": "Profile updated: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in p.items()),
        "ASSESSMENT_COMPLETED": f"Assessment done: {p.get('title')}",
        "ROADMAP_CREATED": "Roadmap started",
        "ROADMAP_UPDATED": f"Roadmap updated (version {p.get('version')})",
        "MILESTONE_COMPLETED": f"Milestone done: {p.get('title')}",
        "FOCUS_CHOSEN": f"Focus chosen: {p.get('career', '').replace('_', ' ')}",
        "COLLEGE_SHORTLISTED": f"Shortlisted {p.get('college', 'a college')}",
        "COLLEGE_UNSHORTLISTED": f"Took {p.get('college', 'a college')} off the shortlist",
    }
    return what.get(event.event_type, event.event_type.replace("_", " ").capitalize())


@memory_router.get("/timeline", response_model=list[EventOut])
def my_timeline(limit: int = 50, before: datetime | None = None,
                profile: StudentProfile = Depends(get_current_student_profile),
                db: Session = Depends(get_db)) -> list[EventOut]:
    """The student's career journey, newest first (spec §21)."""
    q = _own(db, StudentEvent, profile).order_by(StudentEvent.occurred_at.desc(), StudentEvent.id.desc())
    if before is not None:
        q = q.where(StudentEvent.occurred_at < before)
    events = db.execute(q.limit(min(max(limit, 1), 200))).scalars()
    return [EventOut(id=e.id, event_type=e.event_type, occurred_at=e.occurred_at, description=_describe(e),
                     reason=e.reason) for e in events]


@counselling_router.get("/current-state")
def current_state(profile: StudentProfile = Depends(get_current_student_profile),
                  db: Session = Depends(get_db)) -> dict:
    """Where the counselling stands (spec §7) — {} when there's nothing yet or no permission."""
    if not consent_service.allowed(db, profile, consent_service.LONG_TERM_MEMORY):
        return {}
    return counselling_state(db, profile) or {}


@counselling_router.get("/history", response_model=list[SummaryOut])
def history(profile: StudentProfile = Depends(get_current_student_profile),
            db: Session = Depends(get_db)) -> list[SummaryOut]:
    sessions = db.execute(_own(db, SessionSummary, profile).order_by(SessionSummary.created_at.desc())).scalars()
    return [SummaryOut(session_id=s.conversation_id, summary=s.summary, decisions=s.decisions, next_steps=s.next_steps,
                       created_at=s.created_at) for s in sessions]


@counselling_router.get("/threads", response_model=list[ThreadOut])
def threads(profile: StudentProfile = Depends(get_current_student_profile),
            db: Session = Depends(get_db)) -> list[ThreadOut]:
    found = db.execute(_own(db, CounsellingThread, profile).order_by(CounsellingThread.last_touched_at.desc())).scalars()
    return [ThreadOut.model_validate(t) for t in found]


class ThreadChange(BaseModel):
    status: str  # open | parked | resolved


@counselling_router.patch("/threads/{thread_id}", response_model=ThreadOut)
def change_thread(thread_id: int, payload: ThreadChange, profile: StudentProfile = Depends(get_current_student_profile),
                  db: Session = Depends(get_db)) -> ThreadOut:
    """The student can park a topic ("not now") or close it ("sorted")."""
    thread = db.get(CounsellingThread, thread_id)
    if thread is None or thread.student_profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if payload.status not in ("open", "parked", "resolved"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "status must be open, parked or resolved")
    thread.status = payload.status
    thread.resolved_at = datetime.now(timezone.utc) if payload.status == "resolved" else None
    db.commit()
    return ThreadOut.model_validate(thread)
