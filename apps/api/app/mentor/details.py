"""A decision about the student's stream, applied once they've said yes (P7-5): their details, then their
roadmap, which is rebuilt from the new stream. MAYA never calls this on her own reading of a decision."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.student import StudentProfile

# As the student's details store them (models/student.py).
STORED = {"pcm": "PCM", "pcb": "PCB", "pcmb": "PCMB", "commerce": "commerce", "humanities": "humanities",
          "arts": "humanities"}


class DetailsError(ValueError):
    pass


def set_stream(db: Session, profile: StudentProfile, said: str) -> dict:
    from app.roadmap import service

    stream = STORED.get(said.strip().lower())
    if stream is None:
        raise DetailsError("The stream must be one of PCM, PCB, PCMB, commerce or humanities.")
    before = profile.stream
    if before == stream:
        return {"stream": stream, "changed": False, "roadmap_changes": []}
    profile.stream = stream
    service._event(db, profile, "PROFILE_UPDATED", {"stream": stream})
    version = None
    if service.get_roadmap(db, profile) is not None:
        version = service.rebuild(db, profile, {"kind": "profile_change", "detail": f"stream {stream}"})
    db.commit()
    changes = [f"{c.op}: {((c.after or c.before or {}).get('title') or {}).get('en', c.node_key)}"
               for c in (version.changes if version else [])][:6]
    return {"stream": stream, "before": before, "changed": True,
            "roadmap_version": version.version_no if version else None, "roadmap_changes": changes}
