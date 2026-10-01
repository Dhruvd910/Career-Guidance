from datetime import datetime

from pydantic import BaseModel, Field


class SubjectOption(BaseModel):
    subject: str
    available_questions: int
    question_count: int  # what a subject test will actually ask
    real_paper_questions: int  # what the real exam asks in that subject


class PracticeOptions(BaseModel):
    """What can be practised right now, and how it compares to the real paper."""

    exam_code: str
    subjects: list[SubjectOption]
    full_test_questions: int
    full_test_minutes: int
    full_test_breakdown: dict[str, int]
    real_paper_questions: int
    real_paper_minutes: int


class StartAttemptRequest(BaseModel):
    exam_code: str
    mode: str = "subject"  # subject|full
    subject: str | None = None
    question_count: int | None = Field(default=None, ge=1, le=180)


class QuestionOut(BaseModel):
    """A question as the student sees it — never carries the answer."""

    id: int
    subject: str
    topic: str | None
    difficulty: str
    stem: str
    options: list[str]


class AttemptOut(BaseModel):
    attempt_id: int
    exam_code: str
    mode: str
    subject: str | None
    duration_seconds: int
    correct_marks: float
    wrong_marks: float
    questions: list[QuestionOut]


class SubmittedAnswer(BaseModel):
    question_id: int
    selected_index: int | None = None


class SubmitAttemptRequest(BaseModel):
    answers: list[SubmittedAnswer] = Field(default_factory=list)
    seconds_taken: int | None = Field(default=None, ge=0)


class SubjectScore(BaseModel):
    subject: str
    correct: int
    wrong: int
    unanswered: int
    score: float
    max_score: float


class QuestionReview(BaseModel):
    position: int
    question_id: int
    subject: str
    topic: str | None
    stem: str
    options: list[str]
    correct_index: int
    selected_index: int | None
    is_correct: bool | None
    explanation: str | None


class AttemptSummary(BaseModel):
    attempt_id: int
    exam_code: str
    title: str
    mode: str
    subject: str | None
    submitted_at: datetime | None
    seconds_taken: int | None
    duration_seconds: int
    total_questions: int
    correct: int
    wrong: int
    unanswered: int
    score: float
    max_score: float
    accuracy: float
    subject_scores: list[SubjectScore]
    review: list[QuestionReview] = Field(default_factory=list)
