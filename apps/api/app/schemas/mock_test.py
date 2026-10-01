from datetime import date

from pydantic import BaseModel, Field


class MockTestCreate(BaseModel):
    exam_code: str
    test_name: str
    test_date: date
    total_score: float
    max_score: float
    percentile: float | None = Field(default=None, ge=0, le=100)
    estimated_rank: int | None = None
    subject_scores: dict[str, float] = Field(default_factory=dict)


class MockTestOut(MockTestCreate):
    id: int
    student_profile_id: int

    model_config = {"from_attributes": True}


class SubjectTrend(BaseModel):
    subject: str
    trend: str  # "Improving" | "Stable" | "Needs improvement"
    average: float
    latest: float


class MockTestDashboard(BaseModel):
    """§13 performance dashboard. estimated_range is explicitly labeled an estimate,
    never a guarantee (§13/§42)."""

    test_count: int
    average_score_pct: float | None
    best_score_pct: float | None
    lowest_score_pct: float | None
    recent_average_pct: float | None
    trend: list[dict]  # [{test_name, date, score_pct}]
    subject_trends: list[SubjectTrend]
    weak_subjects: list[str]
    strong_subjects: list[str]
    estimated_rank_range: str | None
    estimate_disclaimer: str = (
        "This is an estimate based on your mock-test history, not a guaranteed outcome."
    )
