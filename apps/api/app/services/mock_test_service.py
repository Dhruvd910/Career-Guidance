from statistics import mean

from sqlalchemy.orm import Session

from app.models.mock_test import MockTest
from app.models.student import StudentProfile
from app.schemas.mock_test import MockTestCreate, MockTestDashboard, SubjectTrend
from app.services.exam_service import get_exam_by_code


def create_mock_test(db: Session, profile: StudentProfile, payload: MockTestCreate) -> MockTest:
    exam = get_exam_by_code(db, payload.exam_code)
    mock_test = MockTest(
        student_profile_id=profile.id,
        exam_id=exam.id,
        **payload.model_dump(exclude={"exam_code"}),
    )
    db.add(mock_test)
    db.commit()
    db.refresh(mock_test)
    return mock_test


def list_mock_tests(db: Session, profile: StudentProfile, exam_code: str | None = None) -> list[MockTest]:
    query = db.query(MockTest).filter(MockTest.student_profile_id == profile.id)
    if exam_code:
        exam = get_exam_by_code(db, exam_code)
        query = query.filter(MockTest.exam_id == exam.id)
    return query.order_by(MockTest.test_date).all()


def _classify_trend(early_avg: float, late_avg: float) -> str:
    if early_avg == 0:
        return "Stable"
    relative_change = (late_avg - early_avg) / early_avg
    if relative_change > 0.05:
        return "Improving"
    if relative_change < -0.05:
        return "Needs improvement"
    return "Stable"


def build_dashboard(db: Session, profile: StudentProfile, exam_code: str | None = None) -> MockTestDashboard:
    tests = list_mock_tests(db, profile, exam_code)

    if not tests:
        return MockTestDashboard(
            test_count=0,
            average_score_pct=None,
            best_score_pct=None,
            lowest_score_pct=None,
            recent_average_pct=None,
            trend=[],
            subject_trends=[],
            weak_subjects=[],
            strong_subjects=[],
            estimated_rank_range=None,
        )

    score_pcts = [t.total_score / t.max_score * 100 for t in tests]
    recent = score_pcts[-3:]

    trend = [
        {"test_name": t.test_name, "date": t.test_date.isoformat(), "score_pct": round(pct, 1)}
        for t, pct in zip(tests, score_pcts)
    ]

    # Per-subject trend: compare the earliest half of entries against the latest half.
    subjects: dict[str, list[float]] = {}
    for t in tests:
        for subject, score in t.subject_scores.items():
            subjects.setdefault(subject, []).append(score)

    subject_trends = []
    for subject, scores in subjects.items():
        midpoint = max(1, len(scores) // 2)
        early_avg = mean(scores[:midpoint]) if scores[:midpoint] else scores[0]
        late_avg = mean(scores[midpoint:]) if scores[midpoint:] else scores[-1]
        subject_trends.append(
            SubjectTrend(
                subject=subject,
                trend=_classify_trend(early_avg, late_avg),
                average=round(mean(scores), 1),
                latest=round(scores[-1], 1),
            )
        )

    weak_subjects: list[str] = []
    strong_subjects: list[str] = []
    latest_scores = tests[-1].subject_scores
    if len(latest_scores) > 1:
        latest_avg = mean(latest_scores.values())
        for subject, score in latest_scores.items():
            if score < latest_avg * 0.9:
                weak_subjects.append(subject)
            elif score > latest_avg * 1.1:
                strong_subjects.append(subject)

    estimated_rank_range = None
    recent_ranks = [t.estimated_rank for t in tests[-3:] if t.estimated_rank is not None]
    if recent_ranks:
        estimated_rank_range = f"{min(recent_ranks):,} - {max(recent_ranks):,}"

    return MockTestDashboard(
        test_count=len(tests),
        average_score_pct=round(mean(score_pcts), 1),
        best_score_pct=round(max(score_pcts), 1),
        lowest_score_pct=round(min(score_pcts), 1),
        recent_average_pct=round(mean(recent), 1),
        trend=trend,
        subject_trends=subject_trends,
        weak_subjects=weak_subjects,
        strong_subjects=strong_subjects,
        estimated_rank_range=estimated_rank_range,
    )
