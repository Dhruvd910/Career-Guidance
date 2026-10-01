"""Consent for MAYA's memory (DPDP Act 2023; students are mostly minors).

Two separate permissions, both off until given:
- long_term_memory: remembering what was discussed across sessions (summaries, open topics,
  the timeline, interests, goals, constraints, memory items)
- emotion_signals: noting how the student seems in a conversation (confused, under pressure)
  to adjust MAYA's tone — never a diagnosis, never shown to anyone

Anyone under 18 needs a parent or guardian to give them. That consent is recorded as declared:
DPDP asks for *verifiable* parental consent, which needs an identity check (e.g. DigiLocker)
this app can't do by itself — a legal question for whoever deploys MAYA to real students.

Withdrawing a permission deletes what it covered, and says how much.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.memory import (
    Consent, CounsellingThread, DataRequest, MemoryItem, SessionSummary, StudentConstraint, StudentEvent,
    StudentGoal, StudentInterest, TurnAnalysis,
)
from app.models.student import StudentProfile

LONG_TERM_MEMORY, EMOTION_SIGNALS = "long_term_memory", "emotion_signals"
KINDS = (LONG_TERM_MEMORY, EMOTION_SIGNALS)
ADULT_AGE = 18
NOTICE_VERSION = "2026-10-01"

NOTICE = {
    "en": (
        "MAYA can remember your conversations, so next time she can pick up where you left off "
        "instead of starting again.\n\n"
        "What she keeps: short summaries of each conversation, the topics you're still deciding "
        "(like PCM or PCB), your interests and goals, and a timeline of your career journey. "
        "Separately, if you allow it, she can notice how you seem — confused, under pressure — to "
        "talk more kindly. That is never a diagnosis and is never shown to anyone.\n\n"
        "Where it stays: on this device. To understand you, what you say is sent to the AI "
        "services MAYA uses (speech-to-text, the AI model, her voice), as it is today.\n\n"
        "Your control: you can see everything MAYA remembers, delete any of it, or switch memory "
        "off at any time — switching it off deletes what it covered.\n\n"
        "If you are under 18, a parent or guardian must agree."
    ),
    "hi": (
        "MAYA आपकी बातचीत याद रख सकती है, ताकि अगली बार वह फिर से शुरू करने के बजाय वहीं से "
        "आगे बढ़ सके जहाँ आपने छोड़ा था।\n\n"
        "वह क्या रखती है: हर बातचीत का छोटा सारांश, वे विषय जिन पर आप अभी फ़ैसला कर रहे हैं "
        "(जैसे PCM या PCB), आपकी रुचियाँ और लक्ष्य, और आपकी करियर यात्रा की टाइमलाइन। अलग से, "
        "अगर आप अनुमति दें, तो वह यह भी ध्यान रख सकती है कि आप कैसा महसूस कर रहे हैं — उलझन, "
        "दबाव — ताकि वह और प्यार से बात करे। यह कभी कोई निदान नहीं है और किसी को नहीं दिखाया जाता।\n\n"
        "यह कहाँ रहता है: इसी डिवाइस पर। आपको समझने के लिए, आप जो कहते हैं वह MAYA की AI सेवाओं "
        "(बोली को लिखना, AI मॉडल, उसकी आवाज़) को भेजा जाता है, जैसा आज होता है।\n\n"
        "आपका नियंत्रण: आप देख सकते हैं कि MAYA क्या याद रखती है, उसमें से कुछ भी मिटा सकते हैं, "
        "या कभी भी याद रखना बंद कर सकते हैं — बंद करने पर उससे जुड़ी सारी जानकारी मिट जाती है।\n\n"
        "अगर आपकी उम्र 18 साल से कम है, तो माता-पिता या अभिभावक की सहमति ज़रूरी है।"
    ),
}


class ConsentError(ValueError):
    pass


def is_minor(profile: StudentProfile, today: datetime | None = None) -> bool:
    """When in doubt, a guardian decides: without a birth year, and in the year someone turns 18
    (they may not have had the birthday yet), they count as a minor."""
    if not profile.birth_year:
        return True
    year = (today or datetime.now(timezone.utc)).year
    return year - profile.birth_year <= ADULT_AGE


def current(db: Session, profile: StudentProfile, kind: str) -> Consent | None:
    return db.execute(
        select(Consent).where(Consent.student_profile_id == profile.id, Consent.kind == kind)
        .order_by(Consent.decided_at.desc(), Consent.id.desc()).limit(1)
    ).scalar_one_or_none()


def allowed(db: Session, profile: StudentProfile, kind: str) -> bool:
    decision = current(db, profile, kind)
    return bool(decision and decision.granted)


def decide(db: Session, profile: StudentProfile, kind: str, granted: bool,
           guardian: dict | None = None) -> tuple[Consent, dict]:
    """Records a decision. Returns it and, for a withdrawal, what was deleted."""
    if kind not in KINDS:
        raise ConsentError(f"unknown consent kind {kind!r}")
    granted_by = "student"
    if granted and is_minor(profile):
        missing = [f for f in ("name", "relationship", "contact") if not str((guardian or {}).get(f, "")).strip()]
        if missing:
            raise ConsentError("A parent or guardian has to agree for students under 18 — missing: " + ", ".join(missing))
        granted_by = "guardian"
    consent = Consent(student_profile_id=profile.id, kind=kind, granted=granted, granted_by=granted_by,
                      guardian={k: str(guardian[k]).strip() for k in ("name", "relationship", "contact")}
                      if granted_by == "guardian" else None,
                      notice_version=NOTICE_VERSION, decided_at=datetime.now(timezone.utc))
    db.add(consent)
    deleted = {} if granted else forget(db, profile, kind, reason="consent withdrawn")
    db.commit()
    return consent, deleted


def forget(db: Session, profile: StudentProfile, kind: str, reason: str) -> dict:
    """Deletes everything a permission covered (rows and, with them, their vectors), and records
    that it happened. The caller commits."""
    tables = {
        LONG_TERM_MEMORY: (MemoryItem, SessionSummary, CounsellingThread, StudentEvent,
                           StudentInterest, StudentGoal, StudentConstraint),
        EMOTION_SIGNALS: (TurnAnalysis,),
    }[kind]
    counts = {}
    for model in tables:
        if model is MemoryItem:
            # Superseded items point at their replacements; clear that before deleting.
            db.execute(MemoryItem.__table__.update().where(MemoryItem.student_profile_id == profile.id)
                       .values(superseded_by=None))
        result = db.execute(delete(model).where(model.student_profile_id == profile.id))
        counts[model.__tablename__] = result.rowcount
    db.add(DataRequest(student_profile_id=profile.id, kind=f"delete_{kind}", status="done",
                       detail={"reason": reason, "deleted": counts}))
    return counts
