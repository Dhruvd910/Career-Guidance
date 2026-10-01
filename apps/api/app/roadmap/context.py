"""The roadmap in a few lines, for every reply: focus, stage, % done, the next step, and the last
change with its reason. Only once a roadmap exists — talking to MAYA doesn't make one."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.student import StudentProfile
from app.roadmap import service

OFFER = ("If they say a career they want (\"doctor banna hai\", \"I want to do AI\"), offer in one short question to "
         "build their roadmap around it and, on yes, call set_roadmap_focus — don't first ask for their class (you "
         "have it), hours or hard subjects; those adjust it later.")
NONE_YET = ("The student has no roadmap yet. " + OFFER + " If they ask what to do next without a career in mind, call "
            "get_my_roadmap: it starts from their stage.")


def roadmap_context(db: Session, profile: StudentProfile) -> str:
    roadmap = service.get_roadmap(db, profile)
    if roadmap is None or roadmap.active_version_id is None:
        return NONE_YET
    v = service.view(db, profile)
    stage = next((s for s in v["stages"] if s["stage"] == v["current_stage"]), None)
    lines = [f"The student's roadmap (version {v['version']}, {v['hours_per_week']} hours a week on top of school): "
             f"focus {v['focus']['name']['en'] if v['focus'] else 'not chosen yet'}"
             + (f"; also exploring {', '.join(b['name']['en'] for b in v['branches'])}" if v["branches"] else "")
             + (f"; moved away from {', '.join(d['name']['en'] for d in v['dropped'])}" if v["dropped"] else "") + "."]
    if stage:
        lines.append(f"Now: {stage['title']['en']}, {stage['percent']}% of this stage done.")
    if v["next_step"]:
        overdue = " (overdue)" if v["next_step"]["overdue"] else ""
        why = ((v["next_step"]["detail"] or {}).get("why") or {}).get("en")
        lines.append(f"Next step: {v['next_step']['title']['en']}{overdue}" + (f" — why: {why.rstrip('.')}" if why else "") + ".")
    shown = [c for c in v["changes"] if c["op"] in ("add", "defer", "park")
             and c["node_key"].split(":")[0] in ("module", "task", "branch")][:2]
    if shown and v["version"] > 1:
        lines.append("Last change: " + "; ".join(f"{c['op']} {(c['title'] or {}).get('en')} — {c['reason']['en'].rstrip('.')}"
                                                 for c in shown) + ".")
    if not v["focus"]:
        lines.append("No focus career yet. " + OFFER)
    lines.append("Roadmap questions ('Mera next step kya hai?') come from roadmap_next_step / get_my_roadmap.")
    return " ".join(lines)
