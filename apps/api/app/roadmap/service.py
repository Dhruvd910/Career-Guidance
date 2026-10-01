"""The student's roadmap over time (spec §18–20, docs/design/14-phase5-plan.md).

- **The first build:** `current()` builds version 1.
- **Changes:** `adapt()` applies one of spec §19's changes, and `rebuild()` follows a
  reassessment or a profile change. Each makes a new version with a reason for every change.
  Months moving on aren't a change.
- **Progress:** `update_progress()` records the student's own progress on a node, kept by node key
  so it survives every later version. Some nodes complete themselves: an assessment taken, a focus
  chosen, a skill measured strong. Those carry their evidence.
- **Reading it:** `view()` is the tree with progress, and `next_step()` is the first thing to do.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment import alignment
from app.knowledge.graph_store import graph
from app.memory import consent
from app.models.memory import StudentEvent, StudentGoal
from app.models.roadmap import Roadmap, RoadmapChange, RoadmapNode, RoadmapProgress, RoadmapVersion
from app.models.student import StudentProfile
from app.roadmap.generator import STRONG, SUBJECT_SKILLS, Inputs, band_for, build, t

KINDS = ("initial", "time_budget", "difficulty", "interest_change", "focus", "reassessment", "profile_change", "manual")
SUBJECT_WORDS = {"maths": "mathematics", "math": "mathematics", "mathematics": "mathematics", "physics": "physics",
                 "chemistry": "chemistry", "biology": "biology", "english": "english", "accounts": "accountancy",
                 "accountancy": "accountancy", "economics": "economics", "गणित": "mathematics", "मैथ्स": "mathematics"}
SIGNIFICANT = ("title", "stage", "state", "parent_key", "prerequisites", "kind")  # windows moving on isn't a change
WORK = ("module", "task")


class RoadmapError(ValueError):
    def __init__(self, message: str, not_found: bool = False):
        super().__init__(message)
        self.not_found = not_found


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- inputs ----------------

def inputs_for(db: Session, profile: StudentProfile, roadmap: Roadmap, today: date | None = None) -> Inputs:
    store = graph(db)
    latest = alignment.latest_attempts(db, profile)
    results = alignment._results(latest)
    measured = {}
    for skill in store.of_type("skill"):
        for measure in skill["attrs"].get("measured_by", []):
            found = next((c for c in alignment.FALLBACKS.get(measure, [measure]) if c in results), None)
            if found:
                measured[skill["key"]] = {"value": results[found]["score"], "says": results[found]["says"], "dimension": found}
                break
    directions = []
    if not roadmap.focus_career and "interests" in latest:
        summary = alignment.directions(db, profile).get("summary", {})
        directions = (summary.get("strong", []) + summary.get("potential", []))[:3]
    goals = []
    if consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        goals = [g.title for g in db.execute(select(StudentGoal).where(
            StudentGoal.student_profile_id == profile.id, StudentGoal.status == "active")).scalars()]
    today = today or date.today()
    return Inputs(class_level=profile.class_level, education_stage=profile.education_stage, stream=profile.stream,
                  board=profile.school_board, state=profile.state, hours_per_week=roadmap.hours_per_week,
                  focus=roadmap.focus_career, branches=list(roadmap.branches or []),
                  dropped=list(roadmap.dropped or []), difficulties=list(roadmap.difficulties or []),
                  measured=measured, directions=directions, assessments_done=sorted(latest), goals=goals,
                  month=f"{today.year:04d}-{today.month:02d}")


# ---------------- versions ----------------

def get_roadmap(db: Session, profile: StudentProfile) -> Roadmap | None:
    return db.execute(select(Roadmap).where(Roadmap.student_profile_id == profile.id)).scalar_one_or_none()


def active_version(db: Session, roadmap: Roadmap) -> RoadmapVersion | None:
    return db.get(RoadmapVersion, roadmap.active_version_id) if roadmap.active_version_id else None


def _node_dict(node: RoadmapNode) -> dict:
    return {k: getattr(node, k) for k in ("node_key", "parent_key", "kind", "stage", "title", "detail", "prerequisites",
                                         "est_hours", "window", "kg_refs", "state", "attrs", "sort")}


def _default_reason(trigger: dict, op: str) -> dict:
    kind, detail = trigger.get("kind"), trigger.get("detail") or ""
    texts = {
        "initial": t("Your first roadmap.", "आपका पहला रोडमैप।"),
        "time_budget": t(f"You now have {detail} hours a week for it.", f"अब आपके पास हफ़्ते में {detail} घंटे हैं।"),
        "difficulty": t(f"You said {detail} feels hard.", f"आपने कहा कि {detail} मुश्किल लगता है।"),
        "interest_change": t(f"Your interests changed: {detail}.", f"आपकी रुचि बदली: {detail}।"),
        "focus": t(f"You chose a new focus: {detail}.", f"आपने नया लक्ष्य चुना: {detail}।"),
        "reassessment": t(f"A new assessment result: {detail}.", f"नया आकलन नतीजा: {detail}।"),
        "profile_change": t("Your details changed.", "आपकी जानकारी बदली।"),
        "manual": t("Rebuilt from your current details.", "आपकी मौजूदा जानकारी से दोबारा बनाया।"),
    }
    return texts.get(kind, texts["manual"])


def diff(before: list[dict], after: list[dict], trigger: dict) -> list[dict]:
    """The changes from one version to the next, each with its reason — the node's own (e.g. why
    it was deferred) or the trigger's."""
    old = {n["node_key"]: n for n in before}
    new = {n["node_key"]: n for n in after}
    # Months moving on isn't a change — but when the weekly time changed, the new dates are the point.
    fields = SIGNIFICANT + (("window",) if trigger.get("kind") == "time_budget" else ())
    changes = []
    for key, node in new.items():
        reason = node["attrs"].get("reason") or _default_reason(trigger, "add")
        if key not in old:
            changes.append({"op": "add", "node_key": key, "before": None, "after": _brief(node), "reason": reason})
            continue
        was = old[key]
        if was["state"] != node["state"]:
            op = {"deferred": "defer", "parked": "park"}.get(node["state"], "resume")
            changes.append({"op": op, "node_key": key, "before": _brief(was), "after": _brief(node), "reason": reason})
        elif any(was[f] != node[f] for f in fields):
            changes.append({"op": "modify", "node_key": key, "before": _brief(was), "after": _brief(node), "reason": reason})
    for key, node in old.items():
        if key not in new:
            changes.append({"op": "remove", "node_key": key, "before": _brief(node), "after": None,
                            "reason": _default_reason(trigger, "remove")})
    return changes


def _brief(node: dict) -> dict:
    return {"title": node["title"], "stage": node["stage"], "state": node["state"], "kind": node["kind"]}


def rebuild(db: Session, profile: StudentProfile, trigger: dict, today: date | None = None) -> RoadmapVersion | None:
    """Builds from the current inputs; stores a new version only if something meaningful changed
    (or there's none yet). Returns the new version, or None."""
    roadmap = get_roadmap(db, profile)
    if roadmap is None:
        roadmap = Roadmap(student_profile_id=profile.id, branches=[], dropped=[], difficulties=[])
        db.add(roadmap)
        db.flush()
    inputs = inputs_for(db, profile, roadmap, today)
    nodes = build(graph(db), inputs, today or date.today())
    previous = active_version(db, roadmap)
    before = [_node_dict(n) for n in previous.nodes] if previous else []
    changes = diff(before, nodes, trigger) if previous else []
    if previous is not None and not changes:
        _auto_progress(db, roadmap, nodes, inputs)
        db.commit()
        return None
    version = RoadmapVersion(roadmap=roadmap, version_no=(previous.version_no + 1) if previous else 1,
                             parent_version_id=previous.id if previous else None,
                             trigger=trigger, rationale=_default_reason(trigger, "version"),
                             inputs_snapshot=inputs.snapshot())
    version.nodes = [RoadmapNode(**n) for n in nodes]
    version.changes = [RoadmapChange(**c) for c in changes]
    db.add(version)
    db.flush()
    roadmap.active_version_id = version.id
    _auto_progress(db, roadmap, nodes, inputs)
    _event(db, profile, "ROADMAP_CREATED" if previous is None else "ROADMAP_UPDATED",
           {"version": version.version_no, "trigger": trigger.get("kind"), "changes": len(changes),
            "focus": roadmap.focus_career})
    db.commit()
    return version


def current(db: Session, profile: StudentProfile, today: date | None = None) -> Roadmap:
    """The roadmap, built the first time it's asked for, and rebuilt if the student's details
    (class, stream, state) changed since the last version."""
    roadmap = get_roadmap(db, profile)
    version = active_version(db, roadmap) if roadmap else None
    if version is None:
        rebuild(db, profile, {"kind": "initial"}, today)
    else:
        snap = version.inputs_snapshot
        if (snap.get("class_level"), snap.get("education_stage"), snap.get("stream"), snap.get("state")) != (
                profile.class_level, profile.education_stage, profile.stream, profile.state):
            rebuild(db, profile, {"kind": "profile_change"}, today)
    return get_roadmap(db, profile)


# ---------------- progress ----------------

def _progress(db: Session, roadmap: Roadmap) -> dict[str, RoadmapProgress]:
    return {p.node_key: p for p in db.execute(select(RoadmapProgress).where(RoadmapProgress.roadmap_id == roadmap.id)).scalars()}


def _set(db: Session, roadmap: Roadmap, key: str, status: str, evidence: dict, percent: int | None = None,
         existing: dict | None = None) -> RoadmapProgress:
    rows = existing if existing is not None else _progress(db, roadmap)
    row = rows.get(key)
    if row is None:
        row = RoadmapProgress(roadmap_id=roadmap.id, node_key=key, evidence=[])
        db.add(row)
        rows[key] = row
    row.status = status
    row.percent = 100 if status == "done" else (percent if percent is not None else (row.percent or 0))
    row.evidence = [*(row.evidence or []), {**evidence, "at": _now().isoformat()}]
    return row


def _auto_progress(db: Session, roadmap: Roadmap, nodes: list[dict], inputs: Inputs) -> None:
    """What completes itself: assessments taken, a focus chosen, skills measured strong — with evidence."""
    rows = _progress(db, roadmap)
    for node in nodes:
        key, attrs = node["node_key"], node["attrs"]
        if (rows.get(key) and rows[key].status == "done") or node["kind"] not in WORK:
            continue
        if attrs.get("auto") == "assessment" and attrs.get("instrument") in inputs.assessments_done:
            _set(db, roadmap, key, "done", {"kind": "assessment", "note": f"took {attrs['instrument']}"}, existing=rows)
        elif attrs.get("auto") == "focus" and inputs.focus:
            _set(db, roadmap, key, "done", {"kind": "focus", "note": inputs.focus}, existing=rows)
        elif attrs.get("skill") and not attrs.get("inserted_for"):
            measured = inputs.measured.get(attrs["skill"])
            if measured and measured["value"] >= STRONG:
                _set(db, roadmap, key, "done", {"kind": "assessment", "dimension": measured["dimension"],
                                                "says": measured["says"]}, existing=rows)


def update_progress(db: Session, profile: StudentProfile, node_key: str, status: str, percent: int | None = None,
                    note: str | None = None) -> dict:
    """The student's own progress on one node: not_started | in_progress | done | skipped."""
    if status not in ("not_started", "in_progress", "done", "skipped"):
        raise RoadmapError("Status must be not_started, in_progress, done or skipped.")
    roadmap = current(db, profile)
    version = active_version(db, roadmap)
    node = next((n for n in version.nodes if n.node_key == node_key), None)
    if node is None or node.kind not in WORK:
        raise RoadmapError("That isn't a step on your roadmap.", not_found=True)
    _set(db, roadmap, node_key, status, {"kind": "self", "note": (note or "")[:300]},
         None if percent is None else max(0, min(100, percent)))
    db.flush()
    if status == "done" and node.parent_key:
        siblings = [n for n in version.nodes if n.parent_key == node.parent_key and n.kind in WORK and n.state == "active"]
        rows = _progress(db, roadmap)
        if siblings and all(rows.get(n.node_key) and rows[n.node_key].status == "done" for n in siblings):
            parent = next((n for n in version.nodes if n.node_key == node.parent_key), None)
            if parent is not None:
                _event(db, profile, "MILESTONE_COMPLETED", {"title": parent.title["en"], "node_key": parent.node_key})
    db.commit()
    return view(db, profile)


# ---------------- adapting (spec §19) ----------------

def _career(db: Session, said: str | None) -> str | None:
    if not said:
        return None
    from app.knowledge.tools import resolve_career

    key = resolve_career(graph(db), said)
    return key.split(":", 1)[1] if key else None


def adapt(db: Session, profile: StudentProfile, kind: str, detail: str = "", hours_per_week: int | None = None,
          subject: str | None = None, career: str | None = None, dropping: str | None = None) -> dict:
    """One of spec §19's changes → a new version (or none, if nothing changed). Returns the
    changes made, for MAYA (or the screen) to explain."""
    if kind not in KINDS or kind == "initial":
        raise RoadmapError(f"kind must be one of {list(KINDS[1:])}")
    roadmap = current(db, profile)
    store = graph(db)
    trigger = {"kind": kind, "detail": detail}
    if kind == "time_budget":
        if not hours_per_week:
            raise RoadmapError("How many hours a week? (hours_per_week)")
        roadmap.hours_per_week = max(1, min(40, int(hours_per_week)))
        trigger["detail"] = str(roadmap.hours_per_week)
    elif kind == "difficulty":
        normalised = SUBJECT_WORDS.get((subject or "").strip().lower())
        if normalised not in SUBJECT_SKILLS:
            raise RoadmapError("Which subject? (mathematics, physics, chemistry, biology, english, accountancy, economics)")
        if normalised not in roadmap.difficulties:
            roadmap.difficulties = [*roadmap.difficulties, normalised]
        trigger["detail"] = normalised
    elif kind in ("interest_change", "focus"):
        new = _career(db, career)
        old = _career(db, dropping) if dropping else None
        if career and new is None:
            raise RoadmapError(f"There's no career called '{career}' in MAYA's knowledge.")
        if dropping and old is None:
            raise RoadmapError(f"There's no career called '{dropping}' in MAYA's knowledge.")
        branches, dropped, focus = list(roadmap.branches), list(roadmap.dropped), roadmap.focus_career
        if old:
            dropped = [*[d for d in dropped if d != old], old]
            branches = [b for b in branches if b != old]
            if focus == old:
                focus = None
        if new:
            dropped = [d for d in dropped if d != new]
            if kind == "focus" or focus is None:
                if focus and focus != new and focus not in dropped:
                    branches = [*branches, focus]  # the old focus stays as something being explored
                focus = new
                branches = [b for b in branches if b != new]
                _event(db, profile, "FOCUS_CHOSEN", {"career": new})
            elif new not in branches:
                branches = [*branches, new]
        roadmap.focus_career, roadmap.branches, roadmap.dropped = focus, branches, dropped
        names = {k: (store.node(f"career:{k}") or {}).get("name", {}).get("en", k) for k in (new, old) if k}
        trigger["detail"] = ", ".join(filter(None, [f"+{names[new]}" if new else None, f"−{names[old]}" if old else None]))
        if kind == "focus":
            trigger["detail"] = names.get(new, "")
    db.flush()
    version = rebuild(db, profile, trigger)
    return {"changed": version is not None, "version": version.version_no if version else None,
            "changes": [_change_view(c) for c in (version.changes if version else [])]}


def after_assessment(db: Session, profile: StudentProfile, instrument_title: str) -> None:
    """Called when an assessment completes: measured skills may now be done, new gaps may need a
    foundation module."""
    if get_roadmap(db, profile) is not None:
        rebuild(db, profile, {"kind": "reassessment", "detail": instrument_title})


# ---------------- reading it ----------------

def _change_view(change: RoadmapChange) -> dict:
    return {"op": change.op, "node_key": change.node_key, "title": (change.after or change.before or {}).get("title"),
            "stage": (change.after or change.before or {}).get("stage"), "reason": change.reason}


def _percent(status: RoadmapProgress | None) -> int:
    if status is None:
        return 0
    return 100 if status.status in ("done", "skipped") else (status.percent or (25 if status.status == "in_progress" else 0))


def view(db: Session, profile: StudentProfile, version_no: int | None = None) -> dict:
    roadmap = current(db, profile)
    version = active_version(db, roadmap)
    if version_no is not None:
        version = db.execute(select(RoadmapVersion).where(RoadmapVersion.roadmap_id == roadmap.id,
                                                          RoadmapVersion.version_no == version_no)).scalar_one_or_none()
        if version is None:
            raise RoadmapError("There's no such version.", not_found=True)
    rows = _progress(db, roadmap)
    nodes = {n.node_key: {**_node_dict(n), "status": rows[n.node_key].status if n.node_key in rows else "not_started",
                          "percent": _percent(rows.get(n.node_key)),
                          "evidence": (rows[n.node_key].evidence or [])[-1:] if n.node_key in rows else [],
                          "children": []} for n in version.nodes}
    roots = []
    for n in sorted(nodes.values(), key=lambda n: n["sort"]):
        if n["parent_key"] and n["parent_key"] in nodes:
            nodes[n["parent_key"]]["children"].append(n)
        else:
            roots.append(n)

    def roll_up(node: dict) -> tuple[int, int]:
        """(sum of percents, count) over active work under this node."""
        if node["kind"] in WORK:
            return (node["percent"], 1) if node["state"] == "active" else (0, 0)
        total = count = 0
        for child in node["children"]:
            s, c = roll_up(child)
            total, count = total + s, count + c
        node["percent"] = round(total / count) if count else 0
        node["work"] = count
        return total, count

    total = count = 0
    for root in roots:
        s, c = roll_up(root)
        total, count = total + s, count + c
    current_stage = next((r["stage"] for r in roots if r["attrs"].get("current")), roots[0]["stage"] if roots else None)
    today = date.today()
    months_left = max(1, (12 * (today.year + (1 if today.month >= 4 else 0)) + 3) - (12 * today.year + today.month) + 1)
    needed = sum(n["est_hours"] or 0 for n in nodes.values() if n["stage"] == current_stage and n["kind"] in WORK
                 and n["state"] == "active" and n["status"] not in ("done", "skipped"))
    focus = roadmap.focus_career
    store = graph(db)
    name = lambda k: (store.node(f"career:{k}") or {}).get("name", {"en": k, "hi": k})  # noqa: E731
    return {
        "roadmap_id": roadmap.id, "version": version.version_no, "latest_version": active_version(db, roadmap).version_no,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "trigger": version.trigger, "rationale": version.rationale,
        "band": band_for(Inputs(class_level=profile.class_level, education_stage=profile.education_stage)),
        "focus": {"key": focus, "name": name(focus)} if focus else None,
        "branches": [{"key": b, "name": name(b)} for b in roadmap.branches],
        "dropped": [{"key": d, "name": name(d)} for d in roadmap.dropped],
        "hours_per_week": roadmap.hours_per_week, "difficulties": roadmap.difficulties,
        "current_stage": current_stage, "completion": round(total / count) if count else 0,
        # This stage's remaining work against the weekly time left until March.
        "time": {"hours_needed": round(needed), "hours_available": round(months_left * 4.345 * roadmap.hours_per_week)},
        "stages": roots, "changes": [_change_view(c) for c in version.changes],
        "next_step": _next(nodes, current_stage),
    }


def _next(nodes: dict[str, dict], current_stage: str | None) -> dict | None:
    done = {k for k, n in nodes.items() if n["status"] in ("done", "skipped")}
    work = sorted((n for n in nodes.values() if n["kind"] in WORK and n["state"] == "active" and n["status"] not in ("done", "skipped")),
                  key=lambda n: (n["stage"] != current_stage, n["sort"]))
    month = f"{date.today().year:04d}-{date.today().month:02d}"
    for node in work:
        waiting = [p for p in node["prerequisites"] if p not in done and nodes.get(p, {}).get("state") == "active"]
        if waiting:
            continue
        return {"node_key": node["node_key"], "title": node["title"], "stage": node["stage"], "detail": node["detail"],
                "window": node["window"], "status": node["status"],
                "overdue": bool(node["window"] and node["window"]["to"] < month), "attrs": node["attrs"]}
    return None


def next_step(db: Session, profile: StudentProfile) -> dict | None:
    return view(db, profile)["next_step"]


def versions(db: Session, profile: StudentProfile) -> list[dict]:
    roadmap = current(db, profile)
    return [{"version": v.version_no, "created_at": v.created_at.isoformat() if v.created_at else None,
             "trigger": v.trigger, "rationale": v.rationale, "changes": len(v.changes)} for v in roadmap.versions]


# ---------------- timeline ----------------

def _event(db: Session, profile: StudentProfile, event_type: str, payload: dict) -> None:
    """On the timeline — with the memory permission only, like everything MAYA remembers."""
    if consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        db.add(StudentEvent(student_profile_id=profile.id, event_type=event_type, actor="student"
                            if event_type in ("MILESTONE_COMPLETED", "FOCUS_CHOSEN") else "system", payload=payload))
