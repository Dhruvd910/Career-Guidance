"""Consent and the student's view of their own memory (spec §6, DPDP)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.memory import consent as consent_service
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
