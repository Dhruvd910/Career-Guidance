"""What actually happened in a session, from the modules themselves (docs/design/16-phase7-plan.md,
P7-4): roadmap versions made, steps ticked, assessments completed, colleges shortlisted or dropped.
It goes into the session's summary beside the model's account, and the summary's roadmap_changes
come from here — never from the model."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import AssessmentAttempt
from app.models.chat import Conversation
from app.models.memory import StudentEvent
from app.models.roadmap import Roadmap, RoadmapNode, RoadmapProgress, RoadmapVersion


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=timezone.utc) if moment is not None and moment.tzinfo is None else moment


def happened(db: Session, conversation: Conversation, now: datetime | None = None) -> dict:
    start = _aware(conversation.created_at)
    end = _aware(conversation.ended_at) or now or datetime.now(timezone.utc)
    pid = conversation.student_profile_id

    def within(moment) -> bool:
        moment = _aware(moment)
        return moment is not None and start <= moment <= end

    out: list[dict] = []
    roadmap_changes: list[dict] = []
    roadmap = db.execute(select(Roadmap).where(Roadmap.student_profile_id == pid)).scalar_one_or_none()
    if roadmap is not None:
        for v in db.execute(select(RoadmapVersion).where(RoadmapVersion.roadmap_id == roadmap.id)
                            .order_by(RoadmapVersion.version_no)).scalars():
            if within(v.created_at):
                why = (v.rationale or {}).get("en", "")
                roadmap_changes.append({"version": v.version_no, "trigger": (v.trigger or {}).get("kind"), "why": why,
                                        "changes": len(v.changes)})
                out.append({"kind": "roadmap", "what": f"Roadmap version {v.version_no}: {why}"})
        titles = {n.node_key: n.title.get("en") for n in db.execute(select(RoadmapNode).where(
            RoadmapNode.version_id == roadmap.active_version_id)).scalars()} if roadmap.active_version_id else {}
        for p in db.execute(select(RoadmapProgress).where(RoadmapProgress.roadmap_id == roadmap.id)).scalars():
            if within(p.updated_at) and p.status in ("done", "in_progress"):
                how = (p.evidence or [{}])[-1].get("kind", "")
                out.append({"kind": "progress", "what": f"{titles.get(p.node_key, p.node_key)}: {p.status.replace('_', ' ')}"
                            + (f" ({how})" if how and how != "self" else "")})
    for a in db.execute(select(AssessmentAttempt).where(AssessmentAttempt.student_profile_id == pid,
                                                        AssessmentAttempt.status == "completed")).scalars():
        if within(a.completed_at):
            out.append({"kind": "assessment", "what": f"Took “{a.instrument.title['en']}”"})
    for e in db.execute(select(StudentEvent).where(StudentEvent.student_profile_id == pid,
                                                   StudentEvent.event_type.in_(("COLLEGE_SHORTLISTED", "COLLEGE_UNSHORTLISTED")))).scalars():
        if within(e.occurred_at):
            verb = "Shortlisted" if e.event_type == "COLLEGE_SHORTLISTED" else "Took off the shortlist:"
            out.append({"kind": "shortlist", "what": f"{verb} {(e.payload or {}).get('college')}"})
    return {"happened": out, "roadmap_changes": roadmap_changes}
