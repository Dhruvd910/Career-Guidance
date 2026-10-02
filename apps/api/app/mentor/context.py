"""The mentor's part of MAYA's context (docs/design/16-phase7-plan.md, Step 4): what's worth raising
today — at most two items, each once a session — and the shortlist. Each item included is marked
raised, so it isn't raised again this session (P7-3)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.mentor import agenda, shortlist
from app.models.student import StudentProfile


def mentor_context(db: Session, profile: StudentProfile, session_started: datetime | None = None,
                   now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = ["If they ask what to talk about (\"Aaj kya baat karein?\", \"what's next?\"), call what_next first and "
             "offer its first one or two items with their reasons — even ones you've mentioned already."]
    items = agenda.to_raise(db, profile, now, session_started)
    if items:
        lines.append("Worth raising if it fits — briefly, with its reason, once this session (if they say not now, or "
                     "it's done, call update_agenda with its key):")
        for i in items:
            lines.append(f"- [{i.key}] {i.title['en']} — {i.why['en']} (from {i.source})")
            agenda.mark(db, profile, i.key, "raised", now)
    saved = shortlist.items(db, profile)
    if saved:
        lines.append("Their college shortlist: " + "; ".join(f"{c['name']} ({c['city']})" for c in saved[:6])
                     + ". Facts about them come from my_shortlist / college_facts.")
    return "\n".join(lines)
