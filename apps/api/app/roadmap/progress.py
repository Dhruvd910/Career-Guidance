"""Skill progress over time (spec §20): each graph skill's measured level, point by point, from
assessments and practice papers — never from the student ticking a roadmap module done.

An assessment dimension maps to the graph skills that list it in `measured_by` (with the same
stand-ins the directions use: class 9–10 "science" marks stand for physics, chemistry and
biology). A practice paper's subject accuracy maps to that subject's fundamentals.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment import alignment
from app.knowledge.graph_store import graph
from app.models.assessment import AssessmentAttempt
from app.models.practice import TestAttempt
from app.models.roadmap import SkillMeasurement
from app.models.student import StudentProfile

PRACTICE_SKILLS = {"physics": "skill:physics_fundamentals", "chemistry": "skill:chemistry_fundamentals",
                   "maths": "skill:school_mathematics", "mathematics": "skill:school_mathematics",
                   "biology": "skill:biology_fundamentals"}
CHANGE = 0.15  # smaller moves between two measurements are within the noise


def skills_measured_by(db: Session) -> dict[str, list[str]]:
    """{assessment dimension: [graph skills it measures]}, including stand-ins."""
    by_dimension: dict[str, list[str]] = defaultdict(list)
    for skill in graph(db).of_type("skill"):
        for measure in skill["attrs"].get("measured_by", []):
            for dimension in alignment.FALLBACKS.get(measure, [measure]):
                if skill["key"] not in by_dimension[dimension]:
                    by_dimension[dimension].append(skill["key"])
    return by_dimension


def _upsert(db: Session, profile_id: int, skill: str, value: float, kind: str, source_id, detail: dict, at) -> None:
    row = db.execute(select(SkillMeasurement).where(
        SkillMeasurement.student_profile_id == profile_id, SkillMeasurement.skill_key == skill,
        SkillMeasurement.source_kind == kind, SkillMeasurement.source_id == str(source_id))).scalar_one_or_none()
    if row is None:
        row = SkillMeasurement(student_profile_id=profile_id, skill_key=skill, source_kind=kind, source_id=str(source_id))
        db.add(row)
    row.value, row.detail = round(value, 4), detail
    if at is not None:
        row.measured_at = at


def record_attempt(db: Session, attempt: AssessmentAttempt) -> None:
    """A completed assessment's results, as measurements of the skills they measure."""
    from app.assessment.service import _phrase

    by_dimension = skills_measured_by(db)
    method = attempt.instrument.scoring_method
    for score in attempt.scores:
        for skill in by_dimension.get(score.dimension_key, []):
            says = {"en": _phrase(score.dimension_key, score, method, "en"), "hi": _phrase(score.dimension_key, score, method, "hi")}
            _upsert(db, attempt.student_profile_id, skill, score.score, "assessment", attempt.id,
                    {"dimension": score.dimension_key, "instrument": attempt.instrument.key, "says": says},
                    attempt.completed_at)


def record_practice(db: Session, attempt: TestAttempt) -> None:
    """A submitted practice paper's accuracy per subject."""
    for subject, stats in (attempt.subject_scores or {}).items():
        skill = PRACTICE_SKILLS.get(subject.lower())
        asked = stats.get("correct", 0) + stats.get("wrong", 0) + stats.get("unanswered", 0)
        if skill is None or not asked:
            continue
        says = {"en": f"{stats['correct']} of {asked} right in a practice paper",
                "hi": f"प्रैक्टिस पेपर में {asked} में से {stats['correct']} सही"}
        _upsert(db, attempt.student_profile_id, skill, stats["correct"] / asked, "practice", attempt.id,
                {"subject": subject, "says": says}, attempt.submitted_at)


def backfill(db: Session, profile: StudentProfile) -> None:
    """Everything measured before skill progress existed."""
    for attempt in db.execute(select(AssessmentAttempt).where(AssessmentAttempt.student_profile_id == profile.id,
                                                              AssessmentAttempt.status == "completed")).scalars():
        record_attempt(db, attempt)
    for attempt in db.execute(select(TestAttempt).where(TestAttempt.student_profile_id == profile.id,
                                                        TestAttempt.submitted_at.is_not(None))).scalars():
        record_practice(db, attempt)
    db.commit()


def _at(value) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def skill_series(db: Session, profile: StudentProfile) -> list[dict]:
    """Per measured skill: initial, current, the change (only beyond the noise) and every point."""
    rows = db.execute(select(SkillMeasurement).where(SkillMeasurement.student_profile_id == profile.id)).scalars().all()
    by_skill: dict[str, list[SkillMeasurement]] = defaultdict(list)
    for row in rows:
        by_skill[row.skill_key].append(row)
    names = graph(db).names(list(by_skill))
    out = []
    for skill, points in by_skill.items():
        points.sort(key=lambda p: (_at(p.measured_at), p.id))
        first, last = points[0], points[-1]
        delta = last.value - first.value
        out.append({
            "skill": skill, "name": names.get(skill, {"en": skill, "hi": skill}),
            "initial": first.value, "current": last.value,
            "change": 0 if len(points) < 2 or abs(delta) < CHANGE else (1 if delta > 0 else -1),
            "points": [{"at": _at(p.measured_at).isoformat(), "value": p.value, "source": p.source_kind,
                        "says": p.detail.get("says")} for p in points],
        })
    return sorted(out, key=lambda s: (-len(s["points"]), s["name"]["en"]))


def summary(db: Session, profile: StudentProfile) -> dict:
    """Everything spec §20 tracks, in one place: skill progress (measured), assessments taken,
    the roadmap's completion, milestones and projects done, goals, and careers explored."""
    from app.memory import consent
    from app.models.memory import StudentGoal
    from app.roadmap import service as roadmaps

    view = roadmaps.view(db, profile)
    work = list(_walk(view["stages"]))
    milestones = [n for n in work if n["kind"] == "milestone" and n.get("work")]
    projects = [n for n in work if n["kind"] == "task" and n["attrs"].get("project")]
    latest = alignment.latest_attempts(db, profile)
    taken = db.execute(select(AssessmentAttempt).where(AssessmentAttempt.student_profile_id == profile.id,
                                                       AssessmentAttempt.status == "completed")).scalars().all()
    goals = []
    if consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        goals = [{"title": g.title, "status": g.status} for g in db.execute(
            select(StudentGoal).where(StudentGoal.student_profile_id == profile.id)).scalars()]
    return {
        "skills": skill_series(db, profile),
        "assessments": {"kinds": sorted(latest), "attempts": len(taken)},
        "roadmap": {"version": view["version"], "completion": view["completion"],
                    "current_stage": view["current_stage"], "focus": view["focus"]},
        "milestones": {"done": sum(1 for m in milestones if m["percent"] == 100), "total": len(milestones),
                       "done_titles": [m["title"] for m in milestones if m["percent"] == 100]},
        "projects": {"done": sum(1 for p in projects if p["status"] == "done"), "total": len(projects),
                     "done_titles": [p["title"] for p in projects if p["status"] == "done"]},
        "goals": goals,
        "careers_explored": {"focus": view["focus"], "branches": view["branches"], "moved_away_from": view["dropped"]},
        "note": {"en": "Skill levels come only from assessments and practice papers — ticking a step done is your "
                       "progress on the roadmap, not a skill score.",
                 "hi": "हुनर का स्तर सिर्फ़ आकलनों और प्रैक्टिस पेपरों से आता है — किसी कदम को पूरा मार्क करना रोडमैप पर "
                       "आपकी प्रगति है, हुनर का अंक नहीं।"},
    }


def _walk(nodes: list[dict]):
    for n in nodes:
        yield n
        yield from _walk(n["children"])
