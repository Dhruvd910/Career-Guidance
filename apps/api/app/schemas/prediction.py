from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    exam_code: str  # JEE_MAIN | JEE_ADVANCED | NEET_UG
    # The rank if the student has one. Otherwise an expected JEE Main percentile or NEET
    # score is turned into an estimated rank (services/rank_estimates.py), and the
    # response says it's an estimate.
    rank: int | None = Field(default=None, ge=1)
    percentile: float | None = Field(default=None, ge=0, le=100)
    score: float | None = Field(default=None, ge=0, le=720)
    gender: str | None = None  # "female" adds JoSAA's female-only seat pool; others use gender-neutral seats
    # For EWS/OBC/SC/ST: reserved seats are allotted by category rank (JoSAA publishes
    # reserved-category closing ranks as category ranks), so they need this to be compared.
    category_rank: int | None = Field(default=None, ge=1)
    category: str = "General"
    quota: str | None = None  # defaults based on domicile if omitted
    domicile_state: str | None = None
    preferred_branches: list[str] = Field(default_factory=list)
    preferred_states: list[str] = Field(default_factory=list)
    college_type_preference: str | None = None  # government|private|any
    budget_max: float | None = None


class PredictionExplanation(BaseModel):
    years_considered: list[int]
    historical_closing_ranks: dict[str, int]  # {"2023": 41234, "2024": 39876, ...}
    rounds_considered: int
    data_freshness: str | None
    reasoning: str


class PredictionResultItem(BaseModel):
    college_id: int
    seat_type: str = "Gender-Neutral"
    college_name: str
    college_type: str
    city: str
    state: str
    course_name: str
    branch_name: str | None
    category: str
    quota: str
    band: str  # "high_probability" | "possible" | "ambitious"
    band_label: str  # "High Probability" | "Possible" | "Ambitious/Dream"
    band_emoji: str  # "🟢" | "🟡" | "🔴"
    confidence: str  # "High" | "Medium" | "Low"
    explanation: PredictionExplanation
    is_demo_data: bool


class PredictionResponse(BaseModel):
    exam_code: str
    student_rank: int
    rank_estimated: bool = False
    rank_basis: str | None = None  # where an estimated rank came from
    notes: list[str] = Field(default_factory=list)  # e.g. why reserved seats weren't included
    results: list[PredictionResultItem]
    disclaimer: str = (
        "These are data-driven estimates based on historical closing ranks, not a guarantee "
        "of admission. Actual results depend on the current year's counselling process."
    )


class PreferenceListRequest(PredictionRequest):
    pass


class PreferenceListItem(BaseModel):
    position: int
    college_id: int
    college_name: str
    course_name: str
    branch_name: str | None
    label: str  # Dream | Ambitious | Possible | Good Chance | Safe
    explanation: str


class PreferenceListResponse(BaseModel):
    items: list[PreferenceListItem]
    disclaimer: str = (
        "This ordering is a planning aid for counselling — it does not guarantee that "
        "following it will result in admission."
    )
