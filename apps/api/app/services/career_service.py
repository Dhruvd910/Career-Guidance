"""Rule-based career-fit heuristic (spec §7 Step 3) — an "exploration fit" signal, never
presented as scientific certainty. Deliberately transparent: every score traces back to
the student's own self-reported subject interests and traits (§4 class 8-9 questions),
never a black box."""

from sqlalchemy.orm import Session

from app.models.career import CareerAssessment, CareerOption
from app.models.student import StudentProfile
from app.services import assessment_engine
from app.schemas.career import CareerAssessmentRequest, CareerFitResult

# Maps a career's required_subjects/skills_required keywords to the keys students rate
# in the assessment form (0-10 scale). Anything not found gets a neutral default.
NEUTRAL_INTEREST = 5.0


def list_career_options(db: Session) -> list[CareerOption]:
    return db.query(CareerOption).all()


def _score_against(keys: list[str], ratings: dict[str, float]) -> tuple[float, list[str]]:
    if not keys:
        return NEUTRAL_INTEREST * 10, []
    scored = [(k, ratings.get(k.lower(), NEUTRAL_INTEREST)) for k in keys]
    avg_pct = sum(v for _, v in scored) / len(scored) * 10
    weak = [k for k, v in scored if v < 5]
    return avg_pct, weak


def _fit_label(score: float) -> str:
    if score >= 70:
        return "Strong fit"
    if score >= 45:
        return "Moderate fit"
    return "Possible alternative"


def _compute_fit(career: CareerOption, ratings: dict[str, float], all_by_id: dict[int, CareerOption]) -> CareerFitResult:
    subject_score, weak_subjects = _score_against(career.required_subjects, ratings)
    skill_score, weak_skills = _score_against(career.skills_required, ratings)
    fit_score = round((subject_score + skill_score) / 2, 1)

    rationale_parts = []
    if subject_score >= 60:
        rationale_parts.append(
            f"your interest in {', '.join(career.required_subjects) or 'the core subjects'} lines up well"
        )
    if skill_score >= 60:
        rationale_parts.append(f"you rated relevant strengths ({', '.join(career.skills_required)}) highly")
    if not rationale_parts:
        rationale_parts.append("this is included as a broader option to consider alongside your top matches")
    rationale = "Based on your responses, " + " and ".join(rationale_parts) + "."

    challenges = list(career.possible_challenges)
    if weak_subjects:
        challenges.append(f"You rated lower interest in: {', '.join(weak_subjects)}, which this path leans on.")

    alternatives = [
        all_by_id[rid].name for rid in career.related_career_ids if rid in all_by_id
    ]

    return CareerFitResult(
        career_option_id=career.id,
        career_name=career.name,
        fit_score=fit_score,
        fit_label=_fit_label(fit_score),
        rationale=rationale,
        possible_challenges=challenges or ["No major mismatches identified from your responses so far."],
        required_subjects=career.required_subjects,
        required_entrance_exams=career.typical_entrance_exam_codes,
        education_path=career.education_path,
        skills_required=career.skills_required,
        timeline=career.timeline,
        alternatives=alternatives,
        explore_next=list(career.explore_next),
    )


def _conversational_results(db: Session, answers: dict[str, str]) -> tuple[list[CareerFitResult], list[str]]:
    """MAYA's question-by-question assessment: every career, ranked, with reasons."""
    careers = list_career_options(db)
    all_by_id = {c.id: c for c in careers}
    results = []
    for r in assessment_engine.rank_careers(careers, answers):
        career = r["career"]
        reasons = r["reasons"]
        rationale = (
            "It fits because " + ", ".join(reasons[:-1]) + (" and " if len(reasons) > 1 else "") + reasons[-1] + "."
            if reasons else "Your answers didn't point strongly towards this one."
        )
        results.append(CareerFitResult(
            career_option_id=career.id,
            career_key=career.key,
            career_name=career.name,
            category=career.category,
            rank=r["rank"],
            fit_score=r["score"],
            fit_label=r["label"],
            reasons=reasons,
            watch_outs=r["watch_outs"],
            rationale=rationale,
            possible_challenges=list(career.possible_challenges),
            required_subjects=career.required_subjects,
            required_entrance_exams=career.typical_entrance_exam_codes,
            education_path=career.education_path,
            skills_required=career.skills_required,
            timeline=career.timeline,
            alternatives=[all_by_id[i].name for i in career.related_career_ids if i in all_by_id],
            explore_next=list(career.explore_next),
        ))
    return results, assessment_engine.top_dimensions(answers)


def run_career_assessment(
    db: Session, profile: StudentProfile, payload: CareerAssessmentRequest, top_n: int = 6
) -> tuple[CareerAssessment, list[str]]:
    """Returns the saved assessment and what stood out about the student."""
    if "answers" in payload.responses:
        results, highlights = _conversational_results(db, payload.responses["answers"])
        assessment = CareerAssessment(
            student_profile_id=profile.id,
            assessment_type=payload.assessment_type,
            responses=payload.responses,
            results=[r.model_dump() for r in results],
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        return assessment, highlights

    # The older slider-based form (still used by the web app).
    ratings: dict[str, float] = {
        k.lower(): float(v)
        for k, v in {**payload.responses.get("subject_interest", {}), **payload.responses.get("traits", {})}.items()
    }

    careers = list_career_options(db)
    all_by_id = {c.id: c for c in careers}
    results = [_compute_fit(c, ratings, all_by_id) for c in careers]
    results.sort(key=lambda r: r.fit_score, reverse=True)
    top_results = results[:top_n]

    assessment = CareerAssessment(
        student_profile_id=profile.id,
        assessment_type=payload.assessment_type,
        responses=payload.responses,
        results=[r.model_dump() for r in top_results],
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment, []
