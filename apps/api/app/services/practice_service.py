"""Building a practice paper and marking it.

Marking follows the real exams: +4 for a correct answer, -1 for a wrong one, 0 for one left
blank — so a student practising here sees the same trade-off between guessing and skipping
that they'll face in the exam.

The question bank is smaller than a real paper, so a "full-length" practice paper keeps the
real paper's *shape* (its subject proportions and per-question time) at whatever length the
bank can actually fill, and says how long the real thing is. It never pretends to be one.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.exam import Exam
from app.models.mock_test import MockTest
from app.models.practice import AttemptAnswer, FULL_MODE, Question, QuestionExam, SUBJECT_MODE, TestAttempt
from app.models.student import StudentProfile
from app.schemas.practice import (
    AttemptOut, AttemptSummary, PracticeOptions, QuestionOut, QuestionReview, StartAttemptRequest,
    SubjectOption, SubmitAttemptRequest, SubjectScore,
)
from app.services.exam_service import get_exam_by_code

CORRECT_MARKS = 4.0
WRONG_MARKS = -1.0

# The real papers, for shape and for telling the student what they're practising against.
EXAM_PATTERNS = {
    "JEE_MAIN": {"subjects": {"Physics": 25, "Chemistry": 25, "Maths": 25}, "minutes": 180},
    "JEE_ADVANCED": {"subjects": {"Physics": 17, "Chemistry": 17, "Maths": 17}, "minutes": 180},
    "NEET_UG": {"subjects": {"Physics": 45, "Chemistry": 45, "Biology": 90}, "minutes": 200},
}
DEFAULT_SUBJECT_QUESTIONS = 10
MAX_QUESTIONS = 180


def _pattern(exam_code: str) -> dict:
    pattern = EXAM_PATTERNS.get(exam_code)
    if pattern is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No practice paper pattern for '{exam_code}'")
    return pattern


def _seconds_per_question(exam_code: str) -> float:
    pattern = _pattern(exam_code)
    return pattern["minutes"] * 60 / sum(pattern["subjects"].values())


def _bank(db: Session, exam: Exam, subject: str | None = None):
    exam_ids = [exam.id]
    if exam.code == "JEE_ADVANCED":
        # JEE Advanced's syllabus takes in JEE Main's, so its practice draws on both banks.
        main = db.query(Exam).filter(Exam.code == "JEE_MAIN").first()
        if main is not None:
            exam_ids.append(main.id)
    query = (
        db.query(Question)
        .join(QuestionExam, QuestionExam.question_id == Question.id)
        .filter(QuestionExam.exam_id.in_(exam_ids), Question.is_active.is_(True))
        .distinct()
    )
    if subject:
        query = query.filter(Question.subject == subject)
    return query


def get_options(db: Session, exam_code: str) -> PracticeOptions:
    """What this student can actually sit right now, given what's in the bank."""
    exam = get_exam_by_code(db, exam_code)
    pattern = _pattern(exam.code)

    subjects = []
    for subject, real_count in pattern["subjects"].items():
        available = _bank(db, exam, subject).count()
        if not available:
            continue
        subjects.append(SubjectOption(
            subject=subject,
            available_questions=available,
            question_count=min(DEFAULT_SUBJECT_QUESTIONS, available),
            real_paper_questions=real_count,
        ))

    full_plan = _full_paper_plan(db, exam)
    full_total = sum(full_plan.values())
    return PracticeOptions(
        exam_code=exam.code,
        subjects=subjects,
        full_test_questions=full_total,
        full_test_minutes=round(full_total * _seconds_per_question(exam.code) / 60) if full_total else 0,
        real_paper_questions=sum(pattern["subjects"].values()),
        real_paper_minutes=pattern["minutes"],
        full_test_breakdown={s: n for s, n in full_plan.items() if n},
    )


def _full_paper_plan(db: Session, exam: Exam) -> dict[str, int]:
    """How many questions per subject a full paper can have: the real proportions, scaled to
    whatever the smallest-stocked subject allows, so the mix stays right."""
    pattern = _pattern(exam.code)
    ratios = pattern["subjects"]
    available = {subject: _bank(db, exam, subject).count() for subject in ratios}
    if not any(available.values()):
        return {subject: 0 for subject in ratios}

    # The largest scale at which every subject's share can be filled from the bank.
    scale = min(
        (available[subject] / count for subject, count in ratios.items() if count),
        default=0.0,
    )
    scale = min(scale, 1.0)
    plan = {subject: int(count * scale) for subject, count in ratios.items()}
    if sum(plan.values()) == 0:  # a very small bank: one from each subject that has any
        plan = {subject: min(1, available[subject]) for subject in ratios}
    return plan


def start_attempt(db: Session, profile: StudentProfile, payload: StartAttemptRequest) -> AttemptOut:
    exam = get_exam_by_code(db, payload.exam_code)

    if payload.mode == SUBJECT_MODE:
        if not payload.subject:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A subject test needs a subject")
        wanted = min(payload.question_count or DEFAULT_SUBJECT_QUESTIONS, MAX_QUESTIONS)
        questions = _pick(db, exam, {payload.subject: wanted})
    elif payload.mode == FULL_MODE:
        questions = _pick(db, exam, _full_paper_plan(db, exam))
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown test mode '{payload.mode}'")

    if not questions:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No practice questions are available for that yet.",
        )

    duration = int(len(questions) * _seconds_per_question(exam.code))
    attempt = TestAttempt(
        student_profile_id=profile.id,
        exam_id=exam.id,
        mode=payload.mode,
        subject=payload.subject if payload.mode == SUBJECT_MODE else None,
        duration_seconds=duration,
        total_questions=len(questions),
        unanswered=len(questions),
        max_score=len(questions) * CORRECT_MARKS,
    )
    db.add(attempt)
    db.flush()
    for position, question in enumerate(questions):
        db.add(AttemptAnswer(attempt_id=attempt.id, question_id=question.id, position=position))
    db.commit()
    db.refresh(attempt)
    return to_attempt_out(attempt, questions)


def _pick(db: Session, exam: Exam, plan: dict[str, int]) -> list[Question]:
    """A random draw per subject, then subjects interleaved the way a real paper is sectioned."""
    picked: list[Question] = []
    for subject, count in plan.items():
        if count <= 0:
            continue
        pool = _bank(db, exam, subject).all()
        picked.extend(random.sample(pool, min(count, len(pool))))
    picked.sort(key=lambda q: (q.subject, q.id))
    return picked


def to_attempt_out(attempt: TestAttempt, questions: list[Question] | None = None) -> AttemptOut:
    if questions is None:
        questions = [a.question for a in attempt.answers]
    return AttemptOut(
        attempt_id=attempt.id,
        exam_code=attempt.exam.code,
        mode=attempt.mode,
        subject=attempt.subject,
        duration_seconds=attempt.duration_seconds,
        correct_marks=CORRECT_MARKS,
        wrong_marks=WRONG_MARKS,
        questions=[
            QuestionOut(
                id=q.id, subject=q.subject, topic=q.topic, difficulty=q.difficulty,
                stem=q.stem, options=q.options,
            )
            for q in questions
        ],
    )


def _get_attempt(db: Session, profile: StudentProfile, attempt_id: int) -> TestAttempt:
    attempt = (
        db.query(TestAttempt)
        .filter(TestAttempt.id == attempt_id, TestAttempt.student_profile_id == profile.id)
        .first()
    )
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such test attempt")
    return attempt


def submit_attempt(
    db: Session, profile: StudentProfile, attempt_id: int, payload: SubmitAttemptRequest
) -> AttemptSummary:
    attempt = _get_attempt(db, profile, attempt_id)
    if attempt.submitted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That test has already been submitted")

    chosen = {a.question_id: a.selected_index for a in payload.answers}
    subject_scores: dict[str, dict] = {}
    correct = wrong = unanswered = 0
    score = 0.0

    for answer in attempt.answers:
        selected = chosen.get(answer.question_id)
        if selected is not None and not 0 <= selected < len(answer.question.options):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Option {selected} is not on question {answer.question_id}")
        answer.selected_index = selected
        answer.is_correct = None if selected is None else selected == answer.question.correct_index

        stats = subject_scores.setdefault(
            answer.question.subject, {"correct": 0, "wrong": 0, "unanswered": 0, "score": 0.0, "max_score": 0.0},
        )
        stats["max_score"] += CORRECT_MARKS
        if selected is None:
            unanswered += 1
            stats["unanswered"] += 1
        elif answer.is_correct:
            correct += 1
            score += CORRECT_MARKS
            stats["correct"] += 1
            stats["score"] += CORRECT_MARKS
        else:
            wrong += 1
            score += WRONG_MARKS
            stats["wrong"] += 1
            stats["score"] += WRONG_MARKS

    attempt.correct, attempt.wrong, attempt.unanswered = correct, wrong, unanswered
    attempt.score = score
    attempt.subject_scores = subject_scores
    attempt.submitted_at = datetime.now(UTC)
    attempt.seconds_taken = min(payload.seconds_taken, attempt.duration_seconds) if payload.seconds_taken else None

    # Practice papers feed the same score history as tests taken elsewhere, so trends and the
    # dashboard cover everything the student has done.
    db.add(MockTest(
        student_profile_id=profile.id,
        exam_id=attempt.exam_id,
        test_name=_attempt_title(attempt),
        test_date=date.today(),
        total_score=score,
        max_score=attempt.max_score,
        subject_scores={subject: stats["score"] for subject, stats in subject_scores.items()},
    ))
    from app.roadmap.progress import record_practice  # skill progress over time (Phase 5)

    record_practice(db, attempt)
    db.commit()
    db.refresh(attempt)
    return to_summary(attempt, include_review=True)


def _attempt_title(attempt: TestAttempt) -> str:
    if attempt.mode == FULL_MODE:
        return f"{attempt.exam.code} full-length practice paper"
    return f"{attempt.exam.code} {attempt.subject} practice test"


def to_summary(attempt: TestAttempt, include_review: bool = False) -> AttemptSummary:
    review = []
    if include_review:
        review = [
            QuestionReview(
                position=a.position,
                question_id=a.question_id,
                subject=a.question.subject,
                topic=a.question.topic,
                stem=a.question.stem,
                options=a.question.options,
                correct_index=a.question.correct_index,
                selected_index=a.selected_index,
                is_correct=a.is_correct,
                explanation=a.question.explanation,
            )
            for a in attempt.answers
        ]
    return AttemptSummary(
        attempt_id=attempt.id,
        exam_code=attempt.exam.code,
        title=_attempt_title(attempt),
        mode=attempt.mode,
        subject=attempt.subject,
        submitted_at=attempt.submitted_at,
        seconds_taken=attempt.seconds_taken,
        duration_seconds=attempt.duration_seconds,
        total_questions=attempt.total_questions,
        correct=attempt.correct,
        wrong=attempt.wrong,
        unanswered=attempt.unanswered,
        score=attempt.score,
        max_score=attempt.max_score,
        accuracy=round(attempt.correct / attempt.total_questions * 100, 1) if attempt.total_questions else 0.0,
        subject_scores=[
            SubjectScore(subject=subject, **stats) for subject, stats in (attempt.subject_scores or {}).items()
        ],
        review=review,
    )


def get_attempt_summary(db: Session, profile: StudentProfile, attempt_id: int) -> AttemptSummary:
    attempt = _get_attempt(db, profile, attempt_id)
    if attempt.submitted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That test hasn't been submitted yet")
    return to_summary(attempt, include_review=True)


def list_attempts(db: Session, profile: StudentProfile, limit: int = 20) -> list[AttemptSummary]:
    attempts = (
        db.query(TestAttempt)
        .filter(TestAttempt.student_profile_id == profile.id, TestAttempt.submitted_at.isnot(None))
        .order_by(TestAttempt.submitted_at.desc())
        .limit(limit)
        .all()
    )
    return [to_summary(a) for a in attempts]
