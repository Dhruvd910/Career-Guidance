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
        "for_fees_hostels_distances": "Use college_facts or find_colleges; never estimate them.",
        "student_state_unknown": state is None,
    }


# How students say a subject or skill, beyond its name in the graph.
SAID_AS = {
    "subject:mathematics": ["maths", "math", "mathematics", "ganit", "गणित", "numbers"],
    "subject:biology": ["bio", "biology", "जीव विज्ञान"],
    "subject:computer_science": ["computer", "computers", "computer science", "cs"],
    "subject:chemistry": ["chem", "chemistry"],
    "subject:physics": ["physics", "phy"],
    "subject:economics": ["eco", "economics"],
    "skill:programming_fundamentals": ["coding", "programming"],
    "skill:drawing_sketching": ["drawing", "sketching", "art"],
    "skill:public_speaking": ["speaking", "public speaking"],
    "skill:spatial_visualisation": ["spatial", "3d thinking"],
    "exam:NEET_UG": ["NEET", "neet", "NEET UG"],
    "exam:CUET_UG": ["CUET", "cuet"],
    "exam:UPSC_CSE": ["UPSC", "upsc", "IAS", "civil services"],
    "exam:JEE_MAIN": ["JEE", "jee main", "jee mains"],
    "exam:NDA": ["NDA", "nda"],
    "exam:NID_DAT": ["NID", "nid"],
    "exam:NIFT": ["NIFT", "nift"],
    "exam:CA_FOUNDATION": ["CA foundation", "ca exam"],
}


def _resolve_thing(store: GraphStore, said: str) -> str | None:
    """'maths' → subject:mathematics, 'Python' → skill:python, 'JEE Main' → exam:JEE_MAIN. Exams, then
    subjects, then skills: "maths" means the school subject before the skill."""
    from app.knowledge.linking import _aliases, _lexical

    text = said.strip()
    for node_type in ("exam", "subject", "skill"):
        nodes = store.of_type(node_type)
        aliases = _aliases(store, [n["key"] for n in nodes])
        found = _lexical(text, [(n["key"], [*SAID_AS.get(n["key"], []), n["name"]["en"], n["name"]["hi"],
                                            *aliases[n["key"]], n["key"].split(":", 1)[1].replace("_", " ")])
                                for n in nodes])
        if found:
            return found[0]
    return None


def careers_needing(db: Session, profile: StudentProfile, args: dict) -> dict:
    store = graph(db)
    said = str(args.get("thing") or "")
    key = _resolve_thing(store, said)
    if key is None:
        return {"error": f"Nothing called '{said}' in the career graph. Try a school subject (maths, biology), "
                         "a skill (Python, drawing) or an entrance exam (JEE Main, NEET, CLAT)."}

    def row(r):
        out = {"career": r["name"]["en"], "key": r["key"].split(":", 1)[1]}
        if r["draws_on"] is not None:
            out["how_central"] = "central" if r["draws_on"] >= 0.8 else "important" if r["draws_on"] >= 0.5 else "some"
        if r["needed_on"]:
            out["required"] = r["needed_on"]
        if r["via"]:
            out["through"] = [v["name"]["en"] for v in r["via"]][:3]
        return out

    rows = store.careers_needing(key)
    return {"for": store.node(key)["name"]["en"], "kind": store.node(key)["type"], "careers": [row(r) for r in rows],
            "not_listed": "Careers not listed don't need it on their usual routes (within MAYA's 29 careers).",
            "source": "MAYA's curated career knowledge (not yet reviewed by a person)"}


def degree_specialisations(db: Session, profile: StudentProfile, args: dict) -> dict:
    store = graph(db)
    key = resolve_career(store, args.get("career"))
    if key is None:
        return _unknown(store, args.get("career"))
    degrees = [e["other"] for e in store.out(key, "entered_through")]
    names = store.names(degrees)
    out = []
    for degree in degrees:
        found = store.specialisations(degree)
        if found["general"] or found["specialisations"]:
            out.append({"degree": names[degree]["en"], "offered_plain_at": found["general"],
                        "specialisations": [{"name": s["name"], "colleges": s["colleges"], "e.g.": s["programmes"][0]}
                                            for s in found["specialisations"][:8]]})
    return {"career": store.node(key)["name"]["en"], "degrees": out,
            "source": "Official JoSAA / MCC 2026 programme names; colleges = how many offer it",
            "note": "A specialisation is chosen when applying (it's a separate programme with its own cutoff)."}


GRAPH_TOOLS = {
    "career_pathways": career_pathways,
    "career_skills": career_skills,
    "related_careers": related_careers,
    "what_stays_open": what_stays_open,
    "colleges_offering": colleges_offering,
    "careers_needing": careers_needing,
    "degree_specialisations": degree_specialisations,
}
