"""Where to learn each topic: a video in English and one in Hindi for every skill, found and
checked by scripts/find_videos.py (videos.json), plus a YouTube search for the topic — so a
student always has somewhere to start, shown on the Pi as a QR code to open on a phone.

learning_plan() is the Learn screen: the skills of one career in the order they build on each
other, each with its status (from the student's own results) and where to learn it. The career is
the one asked for, else the roadmap's focus, else the strongest career direction.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from app.knowledge import engine
from app.knowledge.graph_store import GraphStore, graph
from app.models.student import StudentProfile

VIDEOS = Path(__file__).parent / "videos.json"


@lru_cache(maxsize=1)
def _videos() -> dict:
    return json.loads(VIDEOS.read_text())["skills"] if VIDEOS.exists() else {}


def youtube_search(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + quote_plus(query)


def for_skill(key: str, name: str | None = None) -> dict:
    """{"videos": [{lang, title, channel, length, url, checked}], "search": {"en": url, "hi": url}}."""
    entry = _videos().get(key) or {}
    query = entry.get("query") or {"en": f"{name or key.split(':', 1)[-1]} tutorial for beginners",
                                   "hi": f"{name or key.split(':', 1)[-1]} hindi"}
    return {
        "videos": [{"lang": v["lang"], "title": v["title"], "channel": v["channel"], "length": v.get("length"),
                    "url": f"https://www.youtube.com/watch?v={v['id']}", "checked": v.get("checked")}
                   for v in entry.get("videos", [])],
        "search": {"en": youtube_search(query["en"]), "hi": youtube_search(query["hi"])},
    }


def _chosen_career(db: Session, profile: StudentProfile, asked: str | None, store: GraphStore) -> tuple[str | None, str]:
    from app.knowledge.tools import resolve_career

    if asked:
        key = resolve_career(store, asked)
        return (key.split(":", 1)[1], "asked") if key else (None, "unknown")
    from app.roadmap import service as roadmaps

    roadmap = roadmaps.get_roadmap(db, profile)
    if roadmap is not None and roadmap.focus_career:
        return roadmap.focus_career, "focus"
    from app.assessment import alignment

    summary = alignment.directions(db, profile).get("summary") or {}
    for band in ("strong", "potential"):
        if summary.get(band):
            return summary[band][0], band
    return None, "none"


def learning_plan(db: Session, profile: StudentProfile, career: str | None = None) -> dict:
    store = graph(db)
    key, why = _chosen_career(db, profile, career, store)
    careers = [{"key": c["key"].split(":", 1)[1], "name": c["name"]} for c in store.of_type("career")]
    if key is None:
        return {"career": None, "why": why, "careers": careers, "steps": []}
    node = store.node(f"career:{key}")
    results = engine._results(db, profile)
    skills = {s["key"]: s for s in store.skills_for(f"career:{key}")}
    steps = []
    for step in store.prerequisite_path(list(skills)):
        info = store.node(step["key"]) or {}
        status = engine.skill_status({"key": step["key"], "name": step["name"],
                                      "measured_by": info.get("attrs", {}).get("measured_by", [])}, results)
        builds = store.developed_by(step["key"])[:2]
        steps.append({
            "skill": step["key"], "name": step["name"], "status": status["status"], "status_label": status["status_label"],
            "says": status.get("says"), "for_career": step["key"] in skills,
            "level": (skills.get(step["key"]) or {}).get("level"),
            "builds_on": [n for n in step.get("needs", [])],
            "try": [{"name": b["name"], "type": b["type"], "url": b["attrs"].get("url")} for b in builds],
            **for_skill(step["key"], step["name"]["en"]),
        })
    return {"career": {"key": key, "name": node["name"] if node else {"en": key, "hi": key}}, "why": why,
            "careers": careers, "steps": steps}
