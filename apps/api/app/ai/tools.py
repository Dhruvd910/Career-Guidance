"""Tool functions the LLM can call (spec §29/§60E). Every tool is a thin wrapper around
the existing service layer — the LLM only ever sees data that already went through the
same validation/provenance path as the REST API. It never computes a prediction, cutoff,
fee, or placement figure itself.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.assessment.tools import ASSESSMENT_TOOLS
from app.knowledge.tools import GRAPH_TOOLS
from app.roadmap.tools import ROADMAP_TOOLS
from app.models.student import StudentProfile
from app.schemas.prediction import PredictionRequest, PreferenceListRequest
from app.facts import topics
from app.services import college_profiles, college_service
from app.services.exam_service import get_exam_profile, list_exams, to_out
from app.services.prediction_service import generate_preference_list, predict
from app.services.student_service import get_next_onboarding_step

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_student_profile",
            "description": "Get the current student's profile: class, board, state, category, preferences.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exam_profile",
            "description": "Get the student's saved profile for a specific exam (score/rank/preferences).",
            "parameters": {
                "type": "object",
                "properties": {"exam_code": {"type": "string", "description": "e.g. JEE_MAIN, NEET_UG"}},
                "required": ["exam_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_colleges",
            "description": "Search the college database by name, exam, state, city, ownership, or course.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "exam_code": {"type": "string"},
                    "state": {"type": "string"},
                    "city": {"type": "string"},
                    "ownership": {"type": "string", "enum": ["government", "private", "deemed"]},
                    "course_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_college",
            "description": "Get full details for one college by its id.",
            "parameters": {
                "type": "object",
                "properties": {"college_id": {"type": "integer"}},
                "required": ["college_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cutoffs",
            "description": "Get historical closing-rank cutoffs for a college.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_id": {"type": "integer"},
                    "category": {"type": "string"},
                    "branch_name": {"type": "string"},
                },
                "required": ["college_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "college_facts",
            "description": "What MAYA knows about one college, by topic: fees (tuition, hostel, mess, waivers), "
                           "campus (hostel, medical facility…), location (address, nearest station, airport, "
                           "hospital), admissions (route, exam, dates), rankings (NIRF), placements. Every value "
                           "comes with its source, academic year and how recently it was checked; an attribute "
                           "that isn't listed is unknown — say so, never estimate it.",
            "parameters": {
                "type": "object",
                "properties": {"college_id": {"type": "integer"},
                               "topic": {"type": "string", "enum": ["fees", "campus", "location", "admissions",
                                                                    "rankings", "placements"]}},
                "required": ["college_id", "topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search official admission documents (JoSAA business rules, MCC counselling scheme, NTA "
                           "information bulletins, JEE Advanced brochure, colleges' own notices) for what they say: "
                           "eligibility, how counselling rounds work, documents needed, rules. query: in English, "
                           "a few key words. Quote the document and its date; a fee or date inside a passage is "
                           "what that document said, not necessarily current — current values come from college_facts.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "exam": {"type": "string", "enum": ["JEE_MAIN", "JEE_ADVANCED", "NEET_UG"],
                         "description": "only documents about this exam"}},
                "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_colleges",
            "description": "Compare 2-4 colleges side by side on cutoffs, fees, hostel, placement, rating.",
            "parameters": {
                "type": "object",
                "properties": {
                    "college_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 4}
                },
                "required": ["college_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_jee",
            "description": "Predict college/branch admission chances for JEE Main/Advanced given rank and category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_code": {"type": "string", "enum": ["JEE_MAIN", "JEE_ADVANCED"]},
                    "rank": {"type": "integer"},
                    "category": {"type": "string"},
                    "quota": {"type": "string"},
                    "preferred_branches": {"type": "array", "items": {"type": "string"}},
                    "preferred_states": {"type": "array", "items": {"type": "string"}},
                    "college_type_preference": {"type": "string", "enum": ["government", "private", "any"]},
                },
                "required": ["exam_code", "rank"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_neet",
            "description": "Predict college admission chances for NEET-UG given rank and category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_code": {"type": "string", "enum": ["NEET_UG"]},
                    "rank": {"type": "integer"},
                    "category": {"type": "string"},
                    "quota": {"type": "string"},
                    "preferred_branches": {"type": "array", "items": {"type": "string"}},
                    "preferred_states": {"type": "array", "items": {"type": "string"}},
                    "college_type_preference": {"type": "string", "enum": ["government", "private", "any"]},
                },
                "required": ["exam_code", "rank"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_preference_list",
            "description": "Generate a Dream/Ambitious/Possible/Good Chance/Safe counselling preference list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_code": {"type": "string"},
                    "rank": {"type": "integer"},
                    "category": {"type": "string"},
                    "preferred_branches": {"type": "array", "items": {"type": "string"}},
                    "preferred_states": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["exam_code", "rank"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_assessments",
            "description": "The student's assessment results (latest of each: interests, thinking skills, skills, "
                           "marks, coding check) and their career directions by band. Use before talking about "
                           "their strengths or which careers suit them.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_direction",
            "description": "Why one career is in its band for this student: the components with their scores, "
                           "why it may fit, strengths, development areas with next steps, questions to "
                           "investigate, things to try, and the usual education path. Call it whenever the "
                           "student asks about one career for themselves — whether it suits them, what to work on.",
            "parameters": {
                "type": "object",
                "properties": {"career_key": {"type": "string", "description": "e.g. cse, ai_data, mbbs, law"}},
                "required": ["career_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_assessments",
            "description": "How the student's results changed between attempts — for 'how much have I improved?'. "
                           "Leave instrument_key out to compare every assessment they've taken more than once. "
                           "change is +1/-1 only when bigger than the noise; 0 means about the same.",
            "parameters": {
                "type": "object",
                "properties": {"instrument_key": {"type": "string",
                                                  "enum": ["interests", "aptitude", "skills", "academic", "coding_check"],
                                                  "description": "optional: just this one (interests = What you "
                                                                 "enjoy, aptitude = Thinking skills, skills = Your "
                                                                 "skills, academic = Your marks)"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_assessment",
            "description": "Offer the student an assessment: puts a Start button for it on their screen. It "
                           "starts nothing by itself — they tap if they want to — so call it straight away (don't "
                           "ask first, and don't just mention the assessment) when they're unsure what suits them, "
                           "ask about their strengths, or a direction needs something measured. Only after calling "
                           "it, tell them in a sentence what it is and how long it takes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instrument_key": {"type": "string",
                                       "enum": ["interests", "aptitude", "skills", "academic", "coding_check"]},
                    "reason": {"type": "string", "description": "a few words on why, for the button"},
                },
                "required": ["instrument_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "career_pathways",
            "description": "How people get into a career: the common and alternative routes, each with the degree, the class "
                           "11-12 subjects it needs, which streams lead there, the entrance exams (with official sites) and "
                           "what can follow. Call it before describing the route into ANY career, even well-known ones "
                           "(doctor, lawyer, IAS): 'how do I become…', 'lawyer kaise bante hain', 'which exam for…'. "
                           "For what to LEARN, use career_skills instead.",
            "parameters": {"type": "object", "properties": {"career": {"type": "string", "description": "a career key (ai_data, cse, mbbs…) or its everyday name (AI, doctor, IAS)"}}, "required": ["career"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "career_skills",
            "description": "The skills a career needs, the student's own results for the ones an assessment measured, the "
                           "gaps (only measured ones), and a learning path in prerequisite order with projects to try. Use "
                           "for what to learn or practise: 'what do I need to learn for…', 'kya kya seekhna padega', "
                           "'what should I work on', 'how do I prepare my skills'. Mention the first steps and a project.",
            "parameters": {"type": "object", "properties": {"career": {"type": "string", "description": "a career key (ai_data, cse, mbbs…) or its everyday name (AI, doctor, IAS)"}}, "required": ["career"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "related_careers",
            "description": "Careers related to one career — named as related, or sharing many of its skills.",
            "parameters": {"type": "object", "properties": {"career": {"type": "string", "description": "a career key (ai_data, cse, mbbs…) or its everyday name (AI, doctor, IAS)"}}, "required": ["career"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "what_stays_open",
            "description": "For a class 11-12 stream (PCM, PCB, PCMB, commerce, humanities): which careers stay open, "
                           "which open only if they add an optional subject, and which close — with the subject that "
                           "decides it. Use for stream choices ('PCB lu toh kya khula rahega?').",
            "parameters": {"type": "object", "properties": {"stream": {"type": "string"}}, "required": ["stream"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "colleges_offering",
            "description": "Colleges with an official JoSAA/MCC 2026 programme on a route into a career — near the student "
                           "(their state) unless another state or city is given. Names, places and programmes only: fees, "
                           "hostels and facilities aren't available yet.",
            "parameters": {"type": "object", "properties": {
                "career": {"type": "string"}, "state": {"type": "string"}, "city": {"type": "string"}},
                "required": ["career"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_roadmap",
            "description": "The student's roadmap: focus career, current stage with each step's status and months, later "
                           "stages, % done, weekly hours. Use for 'show my plan', 'what's on my roadmap'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "roadmap_next_step",
            "description": "The next thing to do on the roadmap, why, when it's done, and things to try. Use for "
                           "'Mera next step kya hai?', 'what should I do now?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_roadmap",
            "description": "Change the roadmap when the student's situation changes (spec §19), making a new version and "
                           "keeping the old ones. Call it as soon as they tell you, with save false: it says what "
                           "would change without changing anything, so you can tell them and ask. Once they agree, "
                           "call it again with save true and explain the changes. kind: time_budget (hours_a_day: the study time a day they said, e.g. 2 for "
                           "'I only have two hours a day'; or hours_a_week: hours a week just for the roadmap's own "
                           "steps, only if they said exactly that), difficulty (subject: the one they find hard), "
                           "interest_change (career: a new interest to explore alongside), focus (career: the one "
                           "to build the roadmap around). With either, pass dropping whenever they say they no "
                           "longer want a career: 'I no longer want AI, I like cybersecurity' is kind focus, "
                           "career cybersecurity, dropping AI.",
            "parameters": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["time_budget", "difficulty", "interest_change", "focus"]},
                "hours_a_day": {"type": "number"}, "hours_a_week": {"type": "integer"}, "subject": {"type": "string"},
                "career": {"type": "string"}, "dropping": {"type": "string"},
                "detail": {"type": "string", "description": "what they said, in a few words"},
                "save": {"type": "boolean", "description": "true only once they've agreed to this change (or asked for "
                                                           "it outright); false shows what would change"}},
                "required": ["kind", "save"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_roadmap_focus",
            "description": "Build the roadmap around one career the student has chosen (key or everyday name). save "
                           "true when they've asked for it ('mera roadmap bana do') or agreed; save false to show what "
                           "would change first and ask. dropping: a career they said they no longer want, if they did.",
            "parameters": {"type": "object", "properties": {"career": {"type": "string"}, "dropping": {"type": "string"},
                                                            "save": {"type": "boolean"}},
                           "required": ["career", "save"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_roadmap_progress",
            "description": "Record that the student finished or started a roadmap step ('I finished the Python course'). "
                           "It returns the step it recorded: say that name back to them.",
            "parameters": {"type": "object", "properties": {
                "step": {"type": "string", "description": "the student's own words for the step, copied as they said "
                                                          "them ('logical reasoning wala step' → 'logical reasoning'); "
                                                          "never a different step"}, "status": {"type": "string", "enum": ["done", "in_progress", "not_started"]},
                "note": {"type": "string"}}, "required": ["step"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_progress",
            "description": "How the student's measured skills moved (first vs now, from assessments and practice papers), "
                           "plus roadmap completion, milestones and projects done. Use for 'Main kitna improve hua hoon?' "
                           "together with compare_assessments.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exam_study_plan",
            "description": "For a JEE or NEET student: the chapter-by-chapter study plan (NCERT book and chapter, "
                           "high-weight chapters marked).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_onboarding_next_step",
            "description": "Get what profile information is still missing / what to ask the student next.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _dump(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_dump(o) for o in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


MAX_CUTOFF_ROWS = 60


def execute_tool(db: Session, profile: StudentProfile, name: str, args: dict[str, Any]) -> Any:
    try:
        if name == "get_student_profile":
            from app.schemas.student import StudentProfileOut

            return _dump(StudentProfileOut.model_validate(profile))
        if name == "get_exam_profile":
            return _dump(to_out(get_exam_profile(db, profile, args["exam_code"])))
        if name == "search_colleges":
            return _dump(college_service.search_colleges(db, **args))
        if name == "get_college":
            college = college_service.get_college_or_404(db, args["college_id"])
            return _dump(college_service.to_detail(db, college))
        if name == "get_cutoffs":
            cutoffs = college_service.get_cutoffs(db, **args)
            if len(cutoffs) > MAX_CUTOFF_ROWS:
                # An IIT has hundreds of seat groups; the summary plus a filtered follow-up
                # call keeps the conversation small enough to answer from.
                return {"summary": college_profiles.admission_summary(db, args["college_id"]),
                        "rows": _dump([c for c in cutoffs if c.seat_type == "Gender-Neutral"][:MAX_CUTOFF_ROWS]),
                        "note": f"{len(cutoffs)} seat groups in all; pass category and/or branch_name to narrow."}
            return _dump(cutoffs)
        if name == "college_facts":
            college_service.get_college_or_404(db, args["college_id"])
            found = topics.for_model(topics.facts(db, args["college_id"], args.get("topic")))
            return {"facts": found, "note": (
                "Say where each value comes from and how recently it was checked; for 'Needs verification' or "
                "'Stale', say so. Anything not listed here is unknown: say you couldn't verify it."
                if found else f"Nothing verified about this college's {args.get('topic')} yet — say so plainly.")}
        if name == "search_documents":
            from app import rag
            from app.providers.registry import get_embedding_provider

            hits = rag.search(db, str(args.get("query") or ""), get_embedding_provider(),
                              entity=f"exam:{args['exam']}" if args.get("exam") else None)
            return {"passages": [{k: h[k] for k in ("text", "document", "academic_year", "publisher", "page", "retrieved",
                                                     "url", "official")} for h in hits],
                    "note": ("Answer from these passages only, naming the document and its year. Prefer the newest "
                             "year's document; if only an older one says it, say so (rules can change). Nothing relevant "
                             "here means the documents don't say: tell them so." if hits else
                             "No official document on this yet — say you couldn't find it in the official documents.")}
        if name == "compare_colleges":
            return _dump(college_service.compare_colleges(db, args["college_ids"]))
        if name in ("predict_jee", "predict_neet"):
            return _dump(predict(db, PredictionRequest(**args)))
        if name == "generate_preference_list":
            return _dump(generate_preference_list(db, PreferenceListRequest(**args)))
        if name in ASSESSMENT_TOOLS:
            return ASSESSMENT_TOOLS[name](db, profile, args)
        if name in GRAPH_TOOLS:
            return GRAPH_TOOLS[name](db, profile, args)
        if name in ROADMAP_TOOLS:
            return ROADMAP_TOOLS[name](db, profile, args)
        if name == "get_onboarding_next_step":
            return _dump(get_next_onboarding_step(profile))
        if name == "list_exams":
            return _dump(list_exams(db))
        return {"error": f"Unknown tool '{name}'"}
    except HTTPException as e:
        return {"error": e.detail}
    except Exception as e:  # noqa: BLE001 — tool errors must reach the LLM as data, not crash the chat
        return {"error": f"Tool '{name}' failed: {e}"}
