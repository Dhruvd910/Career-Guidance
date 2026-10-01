"""Assessments and the career directions that come from them (docs/design/07-api-contracts.md §4,
docs/design/12-phase3-plan.md)."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.assessment import alignment, service
from app.assessment.interpret import interpret
from app.assessment.service import AssessmentError
from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.student import StudentProfile
from app.providers.registry import get_llm_provider

router = APIRouter(prefix="/api/assessment", tags=["assessment"])
directions_router = APIRouter(prefix="/api/careers/directions", tags=["assessment"])


class Start(BaseModel):
    instrument_key: str
    language: str = "en"  # en | hi
    mode: str = "touch"  # touch | voice


class Answer(BaseModel):
    attempt_id: int
    item_key: str
    answer: dict | None = None  # {"option": key} | {"value": 0-100}
    skipped: bool = False
    transcript: str | None = Field(default=None, max_length=2000)
    interpreted_by: str = "touch"  # touch | keywords | llm
    response_ms: int | None = None


class Back(BaseModel):
    attempt_id: int


class Interpret(BaseModel):
    attempt_id: int
    item_key: str
    transcript: str = Field(min_length=1, max_length=500)


def _fail(e: AssessmentError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND if e.not_found else status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/instruments")
def instruments(profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> list[dict]:
    return service.instruments(db, profile)


@router.post("/start")
def start(body: Start, profile: StudentProfile = Depends(get_current_student_profile),
          db: Session = Depends(get_db)) -> dict:
    """Starts an assessment — or picks up an unfinished one where it stopped."""
    try:
        return service.start(db, profile, body.instrument_key, language=body.language, mode=body.mode)
    except AssessmentError as e:
        raise _fail(e) from e


@router.post("/answer")
def answer(body: Answer, profile: StudentProfile = Depends(get_current_student_profile),
           db: Session = Depends(get_db)) -> dict:
    """Records one answer (or a skip) → the next item, or the result when that was the last."""
    try:
        return service.answer(db, profile, body.attempt_id, body.item_key, body.answer, skipped=body.skipped,
                              transcript=body.transcript, interpreted_by=body.interpreted_by,
                              response_ms=body.response_ms)
    except AssessmentError as e:
        raise _fail(e) from e


@router.post("/back")
def back(body: Back, profile: StudentProfile = Depends(get_current_student_profile),
         db: Session = Depends(get_db)) -> dict:
    try:
        return service.back(db, profile, body.attempt_id)
    except AssessmentError as e:
        raise _fail(e) from e


@router.post("/interpret")
async def interpret_answer(body: Interpret, profile: StudentProfile = Depends(get_current_student_profile),
                           db: Session = Depends(get_db)) -> dict:
    """What a spoken answer the Pi couldn't match means — {"answer": … | null, "skip": bool}.
    It doesn't record anything: the client confirms by sending /answer."""
    try:
        attempt = service.get_attempt(db, profile, body.attempt_id)
    except AssessmentError as e:
        raise _fail(e) from e
    item = next((i for i in attempt.instrument.items if i.key == body.item_key), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That question isn't part of this assessment.")
    llm = get_llm_provider()
    if llm is None:
        return {"answer": None, "skip": False}
    return await interpret(item, body.transcript, llm)


@router.get("/result")
def result(attempt_id: int, profile: StudentProfile = Depends(get_current_student_profile),
           db: Session = Depends(get_db)) -> dict:
    try:
        attempt = service.get_attempt(db, profile, attempt_id)
    except AssessmentError as e:
        raise _fail(e) from e
    if attempt.status != "completed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That assessment isn't finished yet.")
    return service.result(db, attempt)


@router.get("/history")
def history(instrument_key: str, profile: StudentProfile = Depends(get_current_student_profile),
            db: Session = Depends(get_db)) -> dict:
    return service.history(db, profile, instrument_key)


@router.delete("/attempts/{attempt_id}", status_code=204)
def delete_attempt(attempt_id: int, profile: StudentProfile = Depends(get_current_student_profile),
                   db: Session = Depends(get_db)) -> Response:
    try:
        service.delete_attempt(db, profile, attempt_id)
    except AssessmentError as e:
        raise _fail(e) from e
    return Response(status_code=204)


@directions_router.get("")
def directions(profile: StudentProfile = Depends(get_current_student_profile), db: Session = Depends(get_db)) -> dict:
    """Every career in bands — strong, potential, needs exploration, less likely — grouped by
    domain, with why, strengths, gaps and questions. Never one answer."""
    return alignment.directions(db, profile)


@directions_router.get("/{career_key}")
def direction(career_key: str, profile: StudentProfile = Depends(get_current_student_profile),
              db: Session = Depends(get_db)) -> dict:
    found = alignment.explain(db, profile, career_key)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No direction for that career yet — take the interests check first.")
    return found
