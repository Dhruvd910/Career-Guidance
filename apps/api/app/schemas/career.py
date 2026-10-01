from datetime import datetime

from pydantic import BaseModel, Field


class CareerOptionOut(BaseModel):
    id: int
    key: str | None = None
    name: str
    category: str
    description: str
    required_subjects: list[str]
    typical_entrance_exam_codes: list[str]
    education_path: str
    skills_required: list[str]
    timeline: str
    related_career_ids: list[int]
    possible_challenges: list[str]
    explore_next: list[str]
    details: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class CareerAssessmentRequest(BaseModel):
    """Raw Q&A captured from the structured counselling flow (§7 Step 1)."""

    assessment_type: str  # class8_9_exploration | class10_stream | class11_12_career
    responses: dict = Field(default_factory=dict)


class CareerFitResult(BaseModel):
    career_option_id: int
    career_key: str | None = None
    career_name: str
    category: str = ""
    rank: int | None = None
    reasons: list[str] = Field(default_factory=list)  # why it fits, in plain words
    watch_outs: list[str] = Field(default_factory=list)  # what it needs that you rated low
    fit_score: float  # 0-100, labeled "exploration fit" not scientific certainty (§7)
    fit_label: str  # Best match | Strong fit | Good fit | Worth exploring | Not a natural fit
    rationale: str
    possible_challenges: list[str]
    required_subjects: list[str]
    required_entrance_exams: list[str]
    education_path: str
    skills_required: list[str]
    timeline: str
    alternatives: list[str]
    explore_next: list[str]


class CareerAssessmentOut(BaseModel):
    id: int
    student_profile_id: int
    assessment_type: str
    results: list[CareerFitResult]
    highlights: list[str] = Field(default_factory=list)  # what stood out about the student
    created_at: datetime

    model_config = {"from_attributes": True}
