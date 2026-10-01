from datetime import datetime

from pydantic import BaseModel, Field


class StudentProfileUpdate(BaseModel):
    name: str | None = None
    class_level: int | None = Field(default=None, ge=8, le=12)
    school_board: str | None = None
    state: str | None = None
    domicile_state: str | None = None
    category: str | None = None  # General|EWS|OBC|SC|ST|Other
    preferred_language: str | None = None
    preferred_study_locations: list[str] | None = None
    knows_career_goal: bool | None = None
    target_exam_code: str | None = None
    onboarding_completed: bool | None = None


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
    created_at: datetime

    model_config = {"from_attributes": True}


class AcademicRecordCreate(BaseModel):
    academic_year: str
    class_level: int = Field(ge=8, le=12)
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
