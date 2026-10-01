"""MAYA's roadmap tools (app/ai/tools.py lists them for the model): read the roadmap and the next
step, change it the way spec §19 describes, record what the student finished, and show how their
skills have moved. Results are short and in English; MAYA answers in the student's language and
explains every change with the reason that came back.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.student import StudentProfile
from app.roadmap import progress, service
from app.roadmap.service import RoadmapError

STATUS = {"done": "done", "in_progress": "in progress", "not_started": "not started", "skipped": "skipped"}


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n["children"])


def _window(w: dict | None) -> str | None:
    return f"{w['from']} to {w['to']}" if w else None


def get_my_roadmap(db: Session, profile: StudentProfile, _args: dict) -> dict:
    v = service.view(db, profile)
    stages = []
    for stage in v["stages"]:
        if stage["stage"] == v["current_stage"]:
            steps = [{"step": n["title"]["en"], "status": STATUS[n["status"]], "state": n["state"],
                      "when": _window(n["window"]), "key": n["node_key"]}
                     for n in _walk(stage["children"]) if n["kind"] in ("module", "task")]
            stages.append({"stage": stage["title"]["en"], "now": True, "done_percent": stage["percent"], "steps": steps})
        else:
            stages.append({"stage": stage["title"]["en"], "when": _window(stage["window"]),
                           "milestones": [m["title"]["en"] for m in stage["children"] if m["kind"] in ("milestone", "branch")]})
    return {
        "version": v["version"], "focus": v["focus"]["name"]["en"] if v["focus"] else None,
        "exploring": [b["name"]["en"] for b in v["branches"]], "moved_away_from": [d["name"]["en"] for d in v["dropped"]],
        "hours_per_week": v["hours_per_week"], "completion_percent": v["completion"], "time": v["time"],
        "stages": stages,
        "next_step": v["next_step"]["title"]["en"] if v["next_step"] else None,
        "note": ("No focus career yet: the roadmap is the stage's basics plus exploration. Offer to set one when "
                 "they've chosen (set_roadmap_focus)." if not v["focus"] else None),
    }


def roadmap_next_step(db: Session, profile: StudentProfile, _args: dict) -> dict:
    step = service.next_step(db, profile)
    if step is None:
        return {"next_step": None, "note": "Everything in this stage is done or waiting — well done. Suggest looking at the next stage."}
    detail = step["detail"] or {}
    return {
        "next_step": step["title"]["en"], "when": _window(step["window"]), "overdue": step["overdue"],
        "why": (detail.get("why") or {}).get("en"), "done_when": (detail.get("done_when") or {}).get("en"),
        "things_to_try": [h["en"] if isinstance(h, dict) else h for h in detail.get("how", [])][:3],
        "status": STATUS[step["status"]], "key": step["node_key"],
    }


def adjust_roadmap(db: Session, profile: StudentProfile, args: dict) -> dict:
    try:
        result = service.adapt(db, profile, args.get("kind", ""), detail=str(args.get("detail") or "")[:300],
                               hours_per_week=args.get("hours_per_week"), subject=args.get("subject"),
                               career=args.get("career"), dropping=args.get("dropping"))
    except RoadmapError as e:
        return {"error": str(e)}
    changes = result["changes"]
    shown = [{"change": c["op"], "step": (c["title"] or {}).get("en"), "reason": c["reason"]["en"]}
             for c in changes if c["op"] in ("add", "defer", "park", "remove", "resume")][:10]
    moved = sum(1 for c in changes if c["op"] == "modify")
    return {"new_version": result["version"], "changed": result["changed"], "changes": shown,
            "rescheduled_steps": moved,
            "note": "Explain what changed and why in a sentence or two; say that everything already finished still "
                    "counts and that older versions are kept."}


def set_roadmap_focus(db: Session, profile: StudentProfile, args: dict) -> dict:
    return adjust_roadmap(db, profile, {"kind": "focus", "career": args.get("career"), "detail": args.get("career")})


def update_roadmap_progress(db: Session, profile: StudentProfile, args: dict) -> dict:
    status = args.get("status", "done")
    said = str(args.get("step") or "").strip()
    v = service.view(db, profile)
    steps = [n for n in _walk(v["stages"]) if n["kind"] in ("module", "task")]
    match = [n for n in steps if n["node_key"] == said]
    if not match:
        words = [w for w in re.findall(r"\w+", said.lower()) if len(w) > 2]
        match = [n for n in steps if words and all(w in n["title"]["en"].lower() for w in words)]
        if not match:
            match = [n for n in steps if words and any(w in n["title"]["en"].lower() for w in words)]
    if len(match) != 1:
        return {"error": "Which step? " + ("Several match: " if match else "None match: ")
                + "; ".join(f"{n['title']['en']} ({n['node_key']})" for n in (match or steps)[:8])}
    node = match[0]
    try:
        service.update_progress(db, profile, node["node_key"], status, args.get("percent"), args.get("note"))
    except RoadmapError as e:
        return {"error": str(e)}
    after = service.next_step(db, profile)
    return {"updated": node["title"]["en"], "status": STATUS.get(status, status),
            "next_step": after["title"]["en"] if after else None,
            "note": "This is their own progress on the roadmap — not a measured skill level."}


def my_progress(db: Session, profile: StudentProfile, _args: dict) -> dict:
    s = progress.summary(db, profile)
    return {
        "skills": [{"skill": x["name"]["en"], "first": round(x["initial"] * 100), "now": round(x["current"] * 100),
                    "change": x["change"], "measurements": len(x["points"]),
                    "latest": (x["points"][-1]["says"] or {}).get("en")} for x in s["skills"]],
        "roadmap_completion_percent": s["roadmap"]["completion"],
        "milestones_done": [t["en"] for t in s["milestones"]["done_titles"]],
        "projects_done": [t["en"] for t in s["projects"]["done_titles"]],
        "assessments_taken": s["assessments"]["attempts"],
        "note": "Skill numbers are measured percentages; change is +1/-1 only beyond the noise (0.15). A skill "
                "measured once has no change yet.",
    }


def exam_study_plan(db: Session, profile: StudentProfile, _args: dict) -> dict:
    from app.services.roadmap_service import generate_roadmap

    plan = generate_roadmap(db, profile).study_plan
    if not plan:
        return {"note": "The chapter-by-chapter study plan is for JEE and NEET students; this student hasn't set one of those as their exam."}
    return {"exam": plan["exam_name"], "phases": plan["phases"],
            "subjects": [{"subject": s["name"], "now": [c["name"] for c in s["classes"][0]["chapters"]][:12]}
                         for s in plan["subjects"]], "note": plan["note"]}


ROADMAP_TOOLS = {
    "get_my_roadmap": get_my_roadmap,
    "roadmap_next_step": roadmap_next_step,
    "adjust_roadmap": adjust_roadmap,
    "set_roadmap_focus": set_roadmap_focus,
    "update_roadmap_progress": update_roadmap_progress,
    "my_progress": my_progress,
    "exam_study_plan": exam_study_plan,
}
