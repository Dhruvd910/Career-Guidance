"""Personalized roadmap generator (§33) — a deterministic template chosen by class level
and exam status, not an LLM guess, so it stays consistent and explainable."""

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.exam import ExamProfile
from app.models.student import StudentProfile
from app.schemas.roadmap import RoadmapResponse, RoadmapStep


SYLLABUS = Path(__file__).resolve().parent.parent / "seed" / "syllabus.json"
EXAM_NAMES = {"JEE_MAIN": "JEE Main", "JEE_ADVANCED": "JEE Advanced", "NEET_UG": "NEET-UG"}


@lru_cache(maxsize=1)
def load_syllabus() -> dict:
    return json.loads(SYLLABUS.read_text())


def build_study_plan(exam_code: str | None, class_level: int) -> dict | None:
    """Every chapter to cover for the exam, in the order to cover it, with the exact NCERT book
    and chapter to learn it from, the heavily-tested ones marked, and free resources."""
    if exam_code not in EXAM_NAMES:
        return None
    syllabus = load_syllabus()
    if class_level >= 12:
        order = [("12", "Now — Class 12"), ("11", "Revise alongside — Class 11")]
    elif class_level == 11:
        order = [("11", "Now — Class 11"), ("12", "Next year — Class 12")]
    else:
        order = [("11", "From Class 11"), ("12", "Then Class 12")]
    subjects = []
    for subject in syllabus["subjects"]:
        if exam_code not in subject["exams"]:
            continue
        classes = []
        for level, focus in order:
            classes.append({
                "class_level": int(level),
                "focus": focus,
                "chapters": [
                    {
                        "name": ch["name"],
                        "weight": ch.get("weight", "normal"),
                        "where": f"NCERT {ch['book']} (Class {level}), Chapter {ch['chapter']}",
                    }
                    for ch in subject["classes"][level]
                ],
            })
        subjects.append({
            "name": subject["name"],
            "classes": classes,
            "extra": subject.get("extra", []),
            "tips": subject.get("tips", []),
            "resources": subject.get("resources", []),
        })
    phase_key = "12" if class_level >= 12 else "11"
    return {
        "exam": exam_code,
        "exam_name": EXAM_NAMES[exam_code],
        "phases": syllabus["phases"][phase_key],
        "subjects": subjects,
        "sources": syllabus["sources"],
        "note": ("Chapters marked high-weight have carried many marks in past papers — a guide for where "
                 "to spend time, not a guarantee of what will be asked."),
    }


def _status(index: int, current_index: int) -> str:
    if index < current_index:
        return "done"
    if index == current_index:
        return "current"
    return "upcoming"


def generate_roadmap(db: Session, profile: StudentProfile) -> RoadmapResponse:
    exam_profile = (
        db.query(ExamProfile)
        .filter(ExamProfile.student_profile_id == profile.id)
        .order_by(ExamProfile.updated_at.desc())
        .first()
    )

    if profile.class_level in (8, 9):
        titles = [
            ("Explore interests & strengths", "Take the career exploration assessment and try varied activities."),
            ("Choose a stream in Class 10", "Use your exploration results to guide PCM/PCB/Commerce/Arts choice."),
            ("Build subject fundamentals", "Strengthen maths and science basics regardless of eventual stream."),
            ("Class 11 specialization", "Pick subjects aligned with your emerging interests."),
            ("Exam preparation (if applicable)", "Start structured prep once a target exam is chosen."),
            ("Prediction & counselling", "Use rank/score prediction once you have exam results."),
        ]
        current_index = 0
    elif profile.class_level == 10:
        titles = [
            ("Explore interests & strengths", "Foundational exploration from Class 8-9."),
            ("Choose your stream", "Take the stream-recommendation assessment."),
            ("Class 11 specialization", "Enroll in the subjects matching your chosen stream."),
            ("Exam preparation", "Begin structured preparation for your target entrance exam."),
            ("Monthly mock tests", "Track performance regularly once preparation begins."),
            ("College prediction", "Use rank/score-based prediction closer to your exam."),
            ("Counselling & college selection", "Generate a preference list and compare colleges."),
        ]
        current_index = 1
    else:
        titles = [
            ("Stream chosen", "Already completed in Class 10."),
            ("Exam preparation", "Structured preparation for your target entrance exam."),
            ("Monthly mock tests", "Regular mock tests to track readiness."),
            ("Performance analysis", "Review subject-wise trends and address weak areas."),
            ("Exam attempt", "Appear for the exam(s) relevant to your goal."),
            ("College & branch prediction", "Get data-driven, explainable predictions from your rank/score."),
            ("Counselling", "Generate a personalized preference list."),
            ("College selection", "Compare shortlisted colleges and finalize your choice."),
        ]
        if exam_profile is None:
            current_index = 1
        elif exam_profile.status == "planning":
            current_index = 1
        elif exam_profile.status == "preparing":
            current_index = 2
        elif exam_profile.status == "appeared":
            current_index = 5
        elif exam_profile.status == "qualified" and exam_profile.rank:
            current_index = 5
        else:
            current_index = 4

    steps = [
        RoadmapStep(order=i + 1, title=title, description=desc, status=_status(i, current_index))
        for i, (title, desc) in enumerate(titles)
    ]

    return RoadmapResponse(
        steps=steps,
        current_milestone=steps[current_index].title,
        next_action=steps[min(current_index + 1, len(steps) - 1)].description,
        long_term_goal="Make an informed, well-supported career and college decision — not a guaranteed outcome.",
        study_plan=build_study_plan(
            profile.target_exam_code or (exam_profile.exam.code if exam_profile is not None else None),
            profile.class_level,
        ),
    )
