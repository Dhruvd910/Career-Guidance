from pydantic import BaseModel, Field


class ExamOut(BaseModel):
    id: int
    code: str
    name: str
    category: str
    description: str | None

    model_config = {"from_attributes": True}


class ExamProfileUpsert(BaseModel):
    exam_code: str
    status: str = "planning"  # planning|preparing|appeared|qualified
    attempt_year: int | None = None
    score: float | None = None
    percentile: float | None = Field(default=None, ge=0, le=100)
    rank: int | None = Field(default=None, ge=1)
    category_rank: int | None = Field(default=None, ge=1)
    extra: dict = Field(default_factory=dict)
    preferred_branches: list[str] = Field(default_factory=list)
    preferred_states: list[str] = Field(default_factory=list)
    preferred_cities: list[str] = Field(default_factory=list)
    college_type_preference: str | None = None  # government|private|any
    budget_max: float | None = None


class ExamProfileOut(ExamProfileUpsert):
    id: int
    student_profile_id: int

    model_config = {"from_attributes": True}
