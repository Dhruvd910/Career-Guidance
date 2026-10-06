"""The student's track — what they're heading for — so an assessment doesn't ask about what can't
matter to them: a JEE student who wants computer science isn't asked about hospitals and blood.

The clearest signal wins: the exam they're preparing for, then the roadmap's focus career (by its
domain), then their class 11-12 stream. A student still exploring has no track and is asked
everything. Which questions each track skips is written in the instrument files
(applies_to.skip_for_tracks), where they're reviewed with the questions themselves.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.student import StudentProfile

TRACKS = ("engineering", "medical", "commerce", "humanities")
BY_EXAM = {"JEE_MAIN": "engineering", "JEE_ADVANCED": "engineering", "NEET_UG": "medical"}
BY_DOMAIN = {"technology": "engineering", "engineering": "engineering", "health": "medical", "business": "commerce",
             "law": "humanities", "public_service": "humanities", "media": "humanities", "people": "humanities",
             "hospitality": "humanities"}  # science and design keep every door open: no track
BY_STREAM = {"PCM": "engineering", "PCB": "medical", "COMMERCE": "commerce", "HUMANITIES": "humanities"}  # PCMB: both


def track_for(db: Session, profile: StudentProfile) -> str | None:
    if profile.target_exam_code in BY_EXAM:
        return BY_EXAM[profile.target_exam_code]
    from app.roadmap import service as roadmaps

    roadmap = roadmaps.get_roadmap(db, profile)
    if roadmap is not None and roadmap.focus_career:
        from app.knowledge.graph_store import graph

        domain = graph(db).domain_of(f"career:{roadmap.focus_career}")
        if domain and domain["key"].split(":", 1)[1] in BY_DOMAIN:
            return BY_DOMAIN[domain["key"].split(":", 1)[1]]
    return BY_STREAM.get((profile.stream or "").upper())
