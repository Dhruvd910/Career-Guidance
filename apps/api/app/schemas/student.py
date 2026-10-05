from datetime import datetime

from pydantic import BaseModel, Field

# Class 6 to 12 at school. A college student keeps class_level 12 (school finished) and says where they
# are with education_stage.
MIN_CLASS, MAX_CLASS = 6, 12
EDUCATION_STAGE = r"^(class_([6-9]|1[0-2])|dropper|ug_y[1-5]|pg|graduate)$"


class StudentProfileUpdate(BaseModel):
    name: str | None = None
    class_level: int | None = Field(default=None, ge=MIN_CLASS, le=MAX_CLASS)
    school_board: str | None = None
    state: str | None = None
    domicile_state: str | None = None
    category: str | None = None  # General|EWS|OBC|SC|ST|Other
    preferred_language: str | None = None
    preferred_study_locations: list[str] | None = None
    knows_career_goal: bool | None = None
    target_exam_code: str | None = None
    onboarding_completed: bool | None = None
    education_stage: str | None = Field(default=None, pattern=EDUCATION_STAGE)  # class_6…class_12 | dropper | ug_y1…ug_y5 | pg | graduate
    stream: str | None = None  # PCM | PCB | PCMB | commerce | humanities
    birth_year: int | None = Field(default=None, ge=1950, le=2030)
    city: str | None = None
    study_hours_per_week: int | None = Field(default=None, ge=0, le=100)


class StudentProfileOut(BaseModel):
    id: int
    user_id: int
    name: str
    class_level: int
    school_board: str | None
    state: str | None
    domicile_state: str | None
    category: str | None
    preferred_language: str
    preferred_study_locations: list[str]
    knows_career_goal: bool | None
    target_exam_code: str | None
    onboarding_completed: bool
    education_stage: str | None = None
    stream: str | None = None
    birth_year: int | None = None
    city: str | None = None
    study_hours_per_week: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AcademicRecordCreate(BaseModel):
    academic_year: str
    class_level: int = Field(ge=MIN_CLASS, le=MAX_CLASS)
    board_percentage: float | None = Field(default=None, ge=0, le=100)
    subject_marks: dict[str, float] = Field(default_factory=dict)


class AcademicRecordOut(AcademicRecordCreate):
    id: int
    student_profile_id: int

    model_config = {"from_attributes": True}


class NextOnboardingStep(BaseModel):
    """Drives the dynamic onboarding flow (§3/§33) — only asks for what's still missing."""

    step: str
    missing_fields: list[str]
    prompt: str
