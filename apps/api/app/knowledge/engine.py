"""The career engine (spec §11, docs/design/13-phase4-plan.md Step 4): Phase 3's directions,
explained with the career graph — never a new score.

For every career, on top of its band and reasons:

- **Required education**: the common route's degree, its class 11-12 subjects, the streams that
  lead there, and its entrance exams (with official sites).
- **Typical and alternative pathways**: stream → exam → degree → what can follow → roles, with
  the alternatives listed.
- **Skills it needs**, each with the student's own result where something measured it. A gap is
  only claimed there (P4-7); unmeasured skills say so. Foundation gaps are measured skills that
  an unmeasured one builds on ("machine learning builds on programming — your coding check was
  3 of 8").
- **Learning path** (for one career): the needed skills in prerequisite order, with projects and
  free courses that build each.
- **Related careers**, and **how many colleges** offer a route in, from the official programmes —
  in all, and in the student's state.
- **From memory**: interests the student told MAYA, linked to the graph (app/knowledge/linking.py),
  with the memory permission only.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment import alignment
from app.knowledge.graph_store import GraphStore, graph
from app.knowledge.linking import link
from app.memory import consent
from app.models.career import CareerOption
from app.models.knowledge import KgEdge
from app.models.memory import StudentInterest
from app.models.student import StudentProfile
from app.providers.registry import get_embedding_provider

logger = logging.getLogger(__name__)

STRONG, GAP = 0.7, 0.55
FOUNDATION_FOR = 0.8  # a skill this important to the career is worth tracing to its measured foundations
MAX_LEARNING_STEPS = 12
STATUS = {"strong": {"en": "a strength", "hi": "आपकी ताक़त"}, "ok": {"en": "on track", "hi": "ठीक चल रहा है"},
          "gap": {"en": "to work on", "hi": "इस पर काम करना है"},
          "not_measured": {"en": "not measured yet", "hi": "अभी मापा नहीं गया"}}


# ---------------- the student's measurements ----------------

def _results(db: Session, profile: StudentProfile) -> dict[str, dict]:
    return alignment._results(alignment.latest_attempts(db, profile))


def skill_status(skill: dict, results: dict[str, dict]) -> dict:
    found = None
    for measure in skill.get("measured_by", []):
        for candidate in alignment.FALLBACKS.get(measure, [measure]):
            if candidate in results:
                found = (candidate, results[candidate])
                break
        if found:
            break
    row = {"key": skill["key"], "name": skill["name"], "level": skill.get("level"),
           "importance": skill.get("importance"), "measured": found is not None}
    if found is None:
        row.update(status="not_measured", score=None, says=None, measured_as=None)
    else:
        measured_as, r = found
        status = "strong" if r["score"] >= STRONG else "gap" if r["score"] < GAP else "ok"
        row.update(status=status, score=r["score"], says=r["says"], measured_as=measured_as,
                   measured_label=alignment.dimension_labels().get(measured_as))
    row["status_label"] = STATUS[row["status"]]
    return row


# ---------------- what she remembers ----------------

def remembered_links(db: Session, profile: StudentProfile, store: GraphStore, embedder="default") -> dict[str, list[str]]:
    """{graph node key: [the interests that point at it]} — with the memory permission only.
    A link found once is kept on the interest (node_key)."""
    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return {}
    interests = db.execute(select(StudentInterest).where(StudentInterest.student_profile_id == profile.id,
                                                         StudentInterest.status == "active")).scalars().all()
    unlinked = [i for i in interests if not i.node_key]
    if unlinked:
        if embedder == "default":
            embedder = get_embedding_provider()
        from app.knowledge.loader import current_version

        version = current_version(db)
        found = link(store, [i.label for i in unlinked], embedder, version.id if version else None)
        for interest, matches in zip(unlinked, found):
            if matches:
                interest.node_key = matches[0]["key"]
        db.commit()
    links: dict[str, list[str]] = {}
    for interest in interests:
        if interest.node_key:
            links.setdefault(interest.node_key, []).append(interest.label)
    return links


def _from_memory(career_key: str, store: GraphStore, links: dict[str, list[str]]) -> list[dict]:
    if not links:
        return []
    reasons = []
    for label in links.get(career_key, []):
        reasons.append({"en": f"You told MAYA you're interested in {label}",
                        "hi": f"आपने MAYA को बताया था कि आपकी रुचि {label} में है"})
    for e in store.out(career_key, "part_of"):
        for label in links.get(e["other"], []):
            reasons.append({"en": f"You told MAYA you're interested in {label}",
                            "hi": f"आपने MAYA को बताया था कि आपकी रुचि {label} में है"})
    for e in store.out(career_key, "related_subject"):
        if e["attrs"].get("strength", 0) >= 0.66:
            for label in links.get(e["other"], []):
                reasons.append({"en": f"You told MAYA you like {label}", "hi": f"आपने MAYA को बताया था कि आपको {label} पसंद है"})
    unique, seen = [], set()
    for r in reasons:
        if r["en"] not in seen:
            seen.add(r["en"])
            unique.append(r)
    return unique


# ---------------- routes ----------------

def _summary(route: dict) -> dict:
    return {"degree": route["degree"], "commonness": route["commonness"], "note": route.get("note"),
            "subjects": route["subjects"], "streams": route["streams"], "exams": route["exams"], "then": route["then"],
            "colleges_on_record": route["colleges_on_record"]}


def _typical(routes: dict, store: GraphStore, career_key: str) -> list[dict]:
    first = (routes["common"] or routes["alternative"] or [None])[0]
    if first is None:
        return []
    steps = []
    if first["streams"]:
        steps.append({"kind": "stream", "items": [s["name"] for s in first["streams"]]})
    if first["exams"]:
        steps.append({"kind": "exam", "items": [e["name"] for e in first["exams"]]})
    steps.append({"kind": "degree", "items": [first["degree"]["name"]]})
    if routes.get("career_exams"):
        steps.append({"kind": "exam", "items": [e["name"] for e in routes["career_exams"]]})
    roles = store.out(career_key, "leads_to_role")
    if roles:
        names = store.names([e["other"] for e in roles[:3]])
        steps.append({"kind": "roles", "items": [names[e["other"]] for e in roles[:3]]})
    return steps


# ---------------- one career ----------------

def _learning_path(store: GraphStore, skills: list[dict], results: dict) -> list[dict]:
    targets = [s["key"] for s in skills if (s["importance"] or 0) >= FOUNDATION_FOR and s["status"] != "strong"]
    path = []
    for step in store.prerequisite_path(targets):
        status = skill_status({"key": step["key"], "name": step["name"],
                               "measured_by": (store.node(step["key"]) or {}).get("attrs", {}).get("measured_by", [])}, results)
        if status["status"] == "strong":
            continue  # already there
        builds = store.developed_by(step["key"])[:2]
        path.append({**status, "needs": step["needs"],
                     "try": [{"key": b["key"], "type": b["type"], "name": b["name"], "url": b["attrs"].get("url"),
                              "hours": b["attrs"].get("hours")} for b in builds]})
    return path[:MAX_LEARNING_STEPS]


def _foundation_gaps(store: GraphStore, skills: list[dict], results: dict) -> list[dict]:
    gaps = []
    for s in skills:
        if s["measured"] or (s["importance"] or 0) < FOUNDATION_FOR:
            continue
        for step in store.prerequisite_path([s["key"]])[:-1]:
            node = store.node(step["key"]) or {}
            status = skill_status({"key": step["key"], "name": step["name"],
                                   "measured_by": node.get("attrs", {}).get("measured_by", [])}, results)
            if status["status"] == "gap" and all(g["skill"]["key"] != step["key"] for g in gaps):
                gaps.append({"skill": status, "needed_for": {"key": s["key"], "name": s["name"]}})
    return gaps


def enrich(career: dict, store: GraphStore, results: dict, links: dict, state: str | None, full: bool = False) -> dict:
    key = f"career:{career['career_key']}"
    routes = store.pathways(key)
    skills = [skill_status(s, results) for s in store.skills_for(key)]
    first = (routes["common"] or routes["alternative"] or [None])[0]
    others = [r for r in routes["common"] + routes["alternative"] if r is not first]
    out = {
        **career,
        "domain": store.domain_of(key),
        "required_education": _summary(first) if first else None,
        "typical_pathway": _typical(routes, store, key),
        "alternative_pathways": [_summary(r) for r in others],
        "career_exams": routes["career_exams"],
        "skills": skills,
        "skill_gaps": [s for s in skills if s["status"] == "gap"],
        "foundation_gaps": _foundation_gaps(store, skills, results),
        "colleges": store.college_counts(key, state),
        "from_memory": _from_memory(key, store, links),
    }
    if full:
        out["learning_path"] = _learning_path(store, skills, results)
        out["related"] = store.related(key)
        out["sources"] = _sources(store, key)
    return out


def _sources(store: GraphStore, key: str) -> dict:
    """Where this career's knowledge came from — honest about what a person hasn't reviewed yet."""
    rows = store.db.execute(select(KgEdge.source, KgEdge.review).where(KgEdge.src_key == key)).all()
    refs = sorted({json.dumps(s, sort_keys=True) for s, _r in rows})
    unreviewed = sum(1 for _s, r in rows if r == "unreviewed")
    return {"refs": [json.loads(r) for r in refs], "unreviewed_links": unreviewed, "total_links": len(rows),
            "note": {"en": "Skills and routes are MAYA's curated knowledge, not yet reviewed by a person; colleges "
                           "and exams come from official sources.",
                     "hi": "हुनर और रास्ते MAYA का संकलित ज्ञान है, जिसकी अभी किसी व्यक्ति ने समीक्षा नहीं की है; "
                           "कॉलेज और परीक्षाएँ आधिकारिक स्रोतों से हैं।"}}


@lru_cache(maxsize=1)
def _questions() -> dict:
    return alignment.career_needs()["careers"]


def _unassessed(db: Session, career_key: str) -> dict | None:
    """A career for someone without assessments: the graph's explanation, no band."""
    row = db.execute(select(CareerOption).where(CareerOption.key == career_key)).scalar_one_or_none()
    if row is None:
        return None
    return {"career_key": career_key, "name": row.name, "band": None, "band_label": None, "components": {},
            "measures": [], "why": [], "strengths": [], "development_areas": [],
            "questions": _questions().get(career_key, {}).get("ask_yourself", []), "not_measured": [],
            "things_to_try": list(row.explore_next or []), "education_path": row.education_path,
            "exams": list(row.typical_entrance_exam_codes or []), "evidence": []}


# ---------------- the API ----------------

def options(db: Session, profile: StudentProfile, embedder="default") -> dict:
    """Personalised directions, every career explained with the graph, grouped by domain."""
    store = graph(db)
    links = remembered_links(db, profile, store, embedder)
    directions = alignment.directions(db, profile)
    if not directions.get("ready"):
        mentioned = set()
        for node_key in links:
            node = store.node(node_key) or {}
            if node.get("type") == "career":
                mentioned.add(node_key.split(":", 1)[1])
            elif node.get("type") == "domain":
                mentioned |= {e["other"].split(":", 1)[1] for e in store.into(node_key, "part_of")}
        from_memory = [c for c in (_unassessed(db, k) for k in sorted(mentioned)) if c]
        return {"ready": False, "missing": directions.get("missing", ["interests"]), "tree": store.domain_tree(),
                "from_memory": [enrich(c, store, {}, links, profile.state) for c in from_memory]}
    results = _results(db, profile)
    order = {d["key"]: d["attrs"].get("order", 99) for d in store.of_type("domain")}
    grouped: dict[str, list[dict]] = {}
    for domain in directions["domains"]:
        for career in domain["careers"]:
            enriched = enrich(career, store, results, links, profile.state)
            grouped.setdefault((enriched["domain"] or {}).get("key", "domain:other"), []).append(enriched)
    domains = []
    for key, careers in grouped.items():
        careers.sort(key=lambda c: alignment.BANDS.index(c["band"]))
        node = store.node(key) or {"name": {"en": "Other", "hi": "अन्य"}}
        domains.append({"domain": key, "label": node["name"], "best_band": careers[0]["band"], "careers": careers})
    domains.sort(key=lambda d: (alignment.BANDS.index(d["best_band"]), order.get(d["domain"], 99)))
    return {"ready": True, "missing": directions["missing"], "inputs": directions["inputs"],
            "as_of": directions.get("as_of"), "summary": directions["summary"], "domains": domains}


def explain(db: Session, profile: StudentProfile, career_key: str, embedder="default") -> dict | None:
    """One career in full: its direction (if assessed) plus the learning path, related careers,
    colleges in the student's state and where the knowledge came from."""
    store = graph(db)
    if store.node(f"career:{career_key}") is None:
        return None
    career = alignment.explain(db, profile, career_key) or _unassessed(db, career_key)
    if career is None:
        return None
    links = remembered_links(db, profile, store, embedder)
    out = enrich(career, store, _results(db, profile), links, profile.state, full=True)
    if profile.state:
        nearby = store.colleges_for(f"career:{career_key}", state=profile.state, limit=8)
        out["colleges_in_state"] = nearby
    return out
