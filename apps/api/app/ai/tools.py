"""Tool functions the LLM can call (spec §29/§60E). Every tool is a thin wrapper around
the existing service layer — the LLM only ever sees data that already went through the
same validation/provenance path as the REST API. It never computes a prediction, cutoff,
fee, or placement figure itself.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.assessment.tools import ASSESSMENT_TOOLS
from app.models.student import StudentProfile
from app.schemas.prediction import PredictionRequest, PreferenceListRequest
from app.services import college_profiles, college_service
from app.services.exam_service import get_exam_profile, list_exams, to_out
from app.services.prediction_service import generate_preference_list, predict
from app.services.roadmap_service import generate_roadmap
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
            "name": "get_fees",
            "description": "What a college costs: tuition, hostel/mess and fee waivers, with sources.",
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
            "name": "get_hostel",
            "description": "Get hostel information for a college.",
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
            "name": "get_placements",
            "description": "Placements for a college: median/highest package with the year and source (engineering), or what graduates do next (medical).",
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
            "name": "get_nearby_places",
            "description": "What's around a college: nearest airport and railway station, local transport and daily needs (approximate distances, researched).",
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
                           "investigate, things to try, and the usual education path.",
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
            "description": "How the student's results changed between attempts at one assessment — for "
                           "'how much have I improved?'. change is +1/-1 only when bigger than the noise; 0 means "
                           "about the same.",
            "parameters": {
                "type": "object",
                "properties": {"instrument_key": {"type": "string",
                                                  "enum": ["interests", "aptitude", "skills", "academic", "coding_check"]}},
                "required": ["instrument_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_assessment",
            "description": "Offer the student an assessment: puts a button to start it on their screen. Use when "
                           "they're unsure what suits them, ask about their strengths, or a direction needs "
                           "something measured. Then tell them what it is and how long it takes.",
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
            "name": "generate_roadmap",
            "description": "Generate the student's personalized step-by-step career roadmap.",
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


def _with_profile(db: Session, college_id: int, records: list, section: str) -> Any:
    """Real colleges have no per-record fee/placement/nearby rows; their researched profile
    (with sources) answers those questions instead."""
    if records:
        return _dump(records)
    college = college_service.get_college_or_404(db, college_id)
    profile = college_profiles.profile_for(college.canonical_name)
    if not profile or not profile.get(section):
        return {"records": [], "note": "Not researched for this college yet — reliable data is unavailable."}
    return {"researched_profile": profile[section], "sources": profile["sources"]}


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
        if name == "get_fees":
            return _with_profile(db, args["college_id"], college_service.get_fees(db, args["college_id"]), "fees")
        if name == "get_hostel":
            return _dump(college_service.get_hostels(db, args["college_id"]))
        if name == "get_placements":
            return _with_profile(db, args["college_id"],
                                 college_service.get_placements(db, args["college_id"]), "placements")
        if name == "get_nearby_places":
            return _with_profile(db, args["college_id"],
                                 college_service.get_nearby(db, args["college_id"]), "surroundings")
        if name == "compare_colleges":
            return _dump(college_service.compare_colleges(db, args["college_ids"]))
        if name in ("predict_jee", "predict_neet"):
            return _dump(predict(db, PredictionRequest(**args)))
        if name == "generate_preference_list":
            return _dump(generate_preference_list(db, PreferenceListRequest(**args)))
        if name in ASSESSMENT_TOOLS:
            return ASSESSMENT_TOOLS[name](db, profile, args)
        if name == "generate_roadmap":
            return _dump(generate_roadmap(db, profile))
        if name == "get_onboarding_next_step":
            return _dump(get_next_onboarding_step(profile))
        if name == "list_exams":
            return _dump(list_exams(db))
        return {"error": f"Unknown tool '{name}'"}
    except HTTPException as e:
        return {"error": e.detail}
    except Exception as e:  # noqa: BLE001 — tool errors must reach the LLM as data, not crash the chat
        return {"error": f"Tool '{name}' failed: {e}"}
