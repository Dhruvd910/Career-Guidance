"""MAYA's tools for assessments (app/ai/tools.py lists them for the model).

Each returns data the model narrates; nothing here computes a new judgement. A result with a
"ui" entry also asks the student's screen to show something — suggest_assessment puts a "Start"
button there (the orchestrator turns it into a `ui.suggest` event and keeps it from the model).
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.assessment import alignment, service
from app.assessment.loader import instrument_files
from app.models.student import StudentProfile

KEYS = ("interests", "aptitude", "skills", "academic", "coding_check")


def _brief(career: dict) -> dict:
    return {"career_key": career["career_key"], "name": career["name"], "band": career["band"]}


def get_my_assessments(db: Session, profile: StudentProfile, _args: dict) -> dict:
    latest = alignment.latest_attempts(db, profile)
    results = {}
    for key, attempt in latest.items():
        r = service.result(db, attempt)
        results[key] = {"title": r["title"]["en"], "completed_at": r["completed_at"],
                        "scores": [{"dimension": s["label"]["en"], "result": s["says"]["en"]} for s in r["scores"]
                                   if not s["dimension"].startswith("learning:")][:12]}
    directions = alignment.directions(db, profile) if latest else {"ready": False}
    out: dict[str, Any] = {"results": results,
                           "not_taken": [k for k in KEYS if k not in latest]}
    if directions.get("ready"):
        careers = [c for d in directions["domains"] for c in d["careers"]]
        out["directions"] = {band: [_brief(c) for c in careers if c["band"] == band]
                             for band in ("strong", "potential", "explore")}
        out["directions_note"] = ("Bands, not a ranking: present several, with reasons from explain_direction; "
                                  "the student decides.")
    return out


def explain_direction(db: Session, profile: StudentProfile, args: dict) -> dict:
    found = alignment.explain(db, profile, str(args.get("career_key", "")))
    if found is None:
        return {"error": "No direction for that career — either the key is wrong or the student hasn't taken "
                         "the 'What you enjoy' assessment yet."}
    keep = ("name", "band", "band_label", "components", "measures", "why", "strengths", "development_areas", "questions",
            "not_measured", "things_to_try", "education_path", "exams")
    return {k: found[k] for k in keep}


def compare_assessments(db: Session, profile: StudentProfile, args: dict) -> dict:
    key = args.get("instrument_key")
    if key not in KEYS:
        return {"error": f"instrument_key must be one of {list(KEYS)}"}
    history = service.history(db, profile, key)
    attempts = history["attempts"]
    if len(attempts) < 2:
        return {"attempts": len(attempts), "note": "There's nothing to compare yet — this needs two attempts. "
                "Suggest taking it again in a few weeks (suggest_assessment)."}

    def rows(changes):
        return [{"dimension": r["label"]["en"], "before": r["before"]["en"], "after": r["after"]["en"],
                 "change": r["change"], "note": r["note"]} for r in changes]

    return {"attempts": len(attempts), "first_taken": attempts[0]["completed_at"],
            "latest_taken": attempts[-1]["completed_at"],
            "since_first": rows(history["since_first"]), "since_previous": rows(history["since_previous"]),
            "note": "change 0 means within the noise for that many questions: call it 'about the same', not "
                    "better or worse."}


def suggest_assessment(db: Session, profile: StudentProfile, args: dict) -> dict:
    key = args.get("instrument_key")
    files = instrument_files()
    if key not in files:
        return {"error": f"instrument_key must be one of {list(files)}"}
    spec = files[key][0]
    reason = str(args.get("reason") or "")[:120]
    return {"suggested": spec.title.en, "minutes": spec.est_minutes, "about": spec.about.en,
            "ui": {"action": "open_assessment", "instrument_key": key, "title": spec.title.model_dump(),
                   "est_minutes": spec.est_minutes, "reason": reason}}


ASSESSMENT_TOOLS: dict[str, Callable[[Session, StudentProfile, dict], dict]] = {
    "get_my_assessments": get_my_assessments,
    "explain_direction": explain_direction,
    "compare_assessments": compare_assessments,
    "suggest_assessment": suggest_assessment,
}
