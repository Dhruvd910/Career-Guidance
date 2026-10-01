"""MAYA's career-graph tools (app/ai/tools.py lists them for the model). Each returns what the
graph says — routes, skills, what a stream keeps open, colleges from official programmes — so
MAYA never has to recall education routes or colleges from her own memory. Results are kept
short and in English; MAYA answers in the student's language.

A career can be named by its key ("ai_data") or as people say it ("AI", "doctor", "IAS").
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.knowledge import engine
from app.knowledge.graph_store import GraphStore, graph
from app.models.student import StudentProfile

STREAMS = {"pcm": "pcm", "pcb": "pcb", "pcmb": "pcmb", "commerce": "commerce", "humanities": "humanities",
           "arts": "humanities", "non medical": "pcm", "non-medical": "pcm", "medical": "pcb", "science": "pcm"}


def resolve_career(store: GraphStore, said: str | None) -> str | None:
    """'ai_data', 'career:ai_data', 'AI', 'doctor' → a career key, or None."""
    if not said:
        return None
    text = said.strip()
    key = text if text.startswith("career:") else f"career:{text.lower()}"
    if store.node(key):
        return key
    from app.knowledge.linking import _aliases, _lexical

    careers = store.of_type("career")
    aliases = _aliases(store, [c["key"] for c in careers])
    found = _lexical(text, [(c["key"], [c["name"]["en"], c["name"]["hi"], *aliases[c["key"]]]) for c in careers])
    return found[0] if found else None


def _unknown(store: GraphStore, said) -> dict:
    return {"error": f"No career called '{said}'. Known careers: "
                     + ", ".join(f"{c['key'].split(':')[1]} ({c['name']['en']})" for c in store.of_type("career"))}


def _route(r: dict) -> dict:
    return {"degree": r["degree"]["name"]["en"], "years": r["degree"].get("duration_years"),
            "class_12_subjects": [s["name"]["en"] for s in r["subjects"]["mandatory"]]
            + [" or ".join(s["name"]["en"] for s in group) for group in r["subjects"]["one_of"]],
            "recommended": [f"{s['name']['en']}" + (f" ({s['note']})" if s.get("note") else "")
                            for s in r["subjects"]["recommended"]],
            "streams": [s["name"]["en"] + (f" (if you add {', '.join(s['if_you_add'])})" if s["if_you_add"] else "")
                        for s in r["streams"]],
            "entrance_exams": [e["name"]["en"] + (f" — {e['note']}" if e.get("note") else "") + (f" [{e['url']}]" if e.get("url") else "")
                               for e in r["exams"]],
            "then": [t["name"]["en"] for t in r["then"]],
            "official_programmes_on_record": r.get("colleges_on_record", 0), "note": r.get("note")}


def career_pathways(db: Session, profile: StudentProfile, args: dict) -> dict:
    store = graph(db)
    key = resolve_career(store, args.get("career"))
    if key is None:
        return _unknown(store, args.get("career"))
    routes = store.pathways(key)
    return {"career": store.node(key)["name"]["en"], "common_routes": [_route(r) for r in routes["common"]],
            "alternative_routes": [_route(r) for r in routes["alternative"]],
            "exam_for_the_career_itself": [e["name"]["en"] for e in routes["career_exams"]],
            "source": "MAYA's curated knowledge (not yet reviewed by a person) + official exam sites"}


def career_skills(db: Session, profile: StudentProfile, args: dict) -> dict:
    store = graph(db)
    key = resolve_career(store, args.get("career"))
    if key is None:
        return _unknown(store, args.get("career"))
    explained = engine.explain(db, profile, key.split(":", 1)[1])

    def skill(s):
        return {"skill": s["name"]["en"], "level_needed": s.get("level"), "status": s["status"],
                "their_result": s["says"]["en"] if s.get("says") else None}

    return {
        "career": explained["name"],
        "skills": [skill(s) for s in explained["skills"]],
        "gaps": [skill(s) for s in explained["skill_gaps"]],
        "foundation_gaps": [f"{g['skill']['name']['en']} ({g['skill']['says']['en']}) — needed for "
                            f"{g['needed_for']['name']['en']}" for g in explained["foundation_gaps"]],
        "learning_path": [{"step": n + 1, "skill": s["name"]["en"], "status": s["status"],
                           "try": [t["name"]["en"] for t in s["try"]]} for n, s in enumerate(explained["learning_path"])],
        "note": "status not_measured means no assessment measured it: never call it a weakness.",
    }


def related_careers(db: Session, profile: StudentProfile, args: dict) -> dict:
    store = graph(db)
    key = resolve_career(store, args.get("career"))
    if key is None:
        return _unknown(store, args.get("career"))
    return {"career": store.node(key)["name"]["en"],
            "related": [{"career": r["name"]["en"], "key": r["key"].split(":", 1)[1], "why": r["via"],
                         "shared_skills": [s["name"]["en"] for s in r["shared_skills"]]} for r in store.related(key, limit=6)]}


def what_stays_open(db: Session, profile: StudentProfile, args: dict) -> dict:
    said = re.sub(r"[^a-z -]", "", str(args.get("stream", "")).lower()).strip()
    stream = STREAMS.get(said)
    if stream is None:
        return {"error": "stream must be one of PCM, PCB, PCMB, commerce, humanities"}
    result = graph(db).open_by_stream(f"stream:{stream}")

    def row(r):
        out = {"career": r["career"]["name"]["en"], "via": r["via"]["name"]["en"]}
        if r["missing"]:
            out["needs"] = [m["name"]["en"] for m in r["missing"]]
        if r["notes"]:
            out["notes"] = [f"{n['name']['en']}: {n['note']}" for n in r["notes"]]
        return out

    return {"stream": result["stream"]["name"]["en"], "stays_open": [row(r) for r in result["open"]],
            "open_if_you_add_an_optional_subject": [row(r) for r in result["if_you_add"]],
            "closes": [row(r) for r in result["closed"]],
            "note": "Based on the class 11-12 subjects each degree requires; colleges can differ — check the official notice."}


def colleges_offering(db: Session, profile: StudentProfile, args: dict) -> dict:
    store = graph(db)
    key = resolve_career(store, args.get("career"))
    if key is None:
        return _unknown(store, args.get("career"))
    state = args.get("state") or (profile.state if args.get("near_me", True) else None)
    found = store.colleges_for(key, state=state, city=args.get("city"), limit=10)
    return {
        "career": store.node(key)["name"]["en"], "state": state, "city": args.get("city"), "total": found["total"],
        "colleges": [{"name": c["name"], "city": c["city"], "state": c["state"], "type": c["type"],
                      "programmes": sorted({f"{p['course']} {p['branch'] or ''}".strip() for p in c["programmes"]})[:3],
                      "admission_through": sorted({p["exam"] for p in c["programmes"]})}
                     for c in found["colleges"]],
        "source": "Official JoSAA / MCC 2026 programme lists",
        "not_available": "Fees, hostels, facilities and distances aren't collected yet — say so; never estimate them.",
        "student_state_unknown": state is None,
    }


GRAPH_TOOLS = {
    "career_pathways": career_pathways,
    "career_skills": career_skills,
    "related_careers": related_careers,
    "what_stays_open": what_stays_open,
    "colleges_offering": colleges_offering,
}
