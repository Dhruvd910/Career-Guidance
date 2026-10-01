"""Taking an assessment: start (or pick up where you stopped), answer, go back, skip, finish.

The server decides what comes next, so the touch screen, voice and MAYA all see one state:
the first item, in order, that applies to this student and hasn't been answered — an item
applies when its `requires` matches earlier answers, its `applies_to` matches the student's
class, and it's on the attempt's form. `attempt.path` lists what has been answered, in order;
"back" steps along it, keeping the earlier answer to show.

Each view carries what MAYA should say for the item, in the attempt's language, so every client
speaks the same words.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment import scoring
from app.assessment.loader import spec_for, sync_instruments
from app.models.assessment import (
    AssessmentAttempt, AssessmentInstrument, AssessmentItem, AssessmentResponse, AssessmentScore,
    CareerAlignmentSnapshot,
)
from app.models.memory import StudentEvent
from app.models.student import StudentProfile

RESUME_WITHIN = timedelta(days=7)
LETTERS = "ABCDEFGH"
NUMBERS = {"en": ["One", "Two", "Three", "Four", "Five", "Six"], "hi": ["एक", "दो", "तीन", "चार", "पाँच", "छह"]}
HI_LETTERS = {"A": "ए", "B": "बी", "C": "सी", "D": "डी", "E": "ई", "F": "एफ़"}
STREAMS = {"PCM": "pcm", "PCB": "pcb", "PCMB": "pcmb", "COMMERCE": "commerce", "HUMANITIES": "humanities", "ARTS": "humanities"}


class AssessmentError(ValueError):
    """Something the student (or client) asked for that can't be done — 400, or 404 when not found."""

    def __init__(self, message: str, not_found: bool = False):
        super().__init__(message)
        self.not_found = not_found


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(when: datetime | None) -> datetime | None:
    return when.replace(tzinfo=timezone.utc) if when is not None and when.tzinfo is None else when


# ---------------- which items apply ----------------

def _applies(item: AssessmentItem, attempt: AssessmentAttempt, profile: StudentProfile, answers: dict[str, dict]) -> bool:
    if item.form is not None and item.form != attempt.form:
        return False
    content = item.content
    applies_to = content.get("applies_to") or {}
    if applies_to.get("class_levels") and profile.class_level not in applies_to["class_levels"]:
        return False
    for earlier, options in (content.get("requires") or {}).items():
        if (answers.get(earlier) or {}).get("option") not in options:
            return False
    return True


def _answers(attempt: AssessmentAttempt) -> dict[str, dict]:
    """{item key: answer} for the answered (not skipped) items."""
    return {r.item.key: r.answer for r in attempt.responses if not r.skipped and r.answer is not None}


def _next_item(attempt: AssessmentAttempt, profile: StudentProfile) -> AssessmentItem | None:
    answers = _answers(attempt)
    done = set(attempt.path)
    for item in attempt.instrument.items:
        if item.key not in done and _applies(item, attempt, profile, answers):
            return item
    return None


def _remaining(attempt: AssessmentAttempt, profile: StudentProfile) -> int:
    answers = _answers(attempt)
    done = set(attempt.path)
    return sum(1 for i in attempt.instrument.items if i.key not in done and _applies(i, attempt, profile, answers))


def _drop_stale(db: Session, attempt: AssessmentAttempt, profile: StudentProfile) -> None:
    """Changing "I love physics" to "I struggle with it" makes the physics follow-ups moot."""
    while True:
        answers = _answers(attempt)
        stale = [r for r in attempt.responses if not _applies(r.item, attempt, profile, answers)]
        if not stale:
            return
        for response in stale:
            attempt.responses.remove(response)
            db.delete(response)
            if response.item.key in attempt.path:
                attempt.path = [k for k in attempt.path if k != response.item.key]


# ---------------- what the client gets ----------------

def _say(item: AssessmentItem, language: str) -> str:
    content = item.content
    lang = language if language in ("en", "hi") else "en"
    base = (content.get("speak") or content["prompt"])[lang]
    options = content.get("options") or []
    if item.item_type == "problem":
        letters = [LETTERS[n] if lang == "en" else HI_LETTERS[LETTERS[n]] for n in range(len(options))]
        return base + " " + " ".join(f"{letter}: {o['label'][lang]}." for letter, o in zip(letters, options))
    if item.item_type == "anchored":
        return base + " " + " ".join(f"{NUMBERS[lang][n]}: {o['label'][lang]}." for n, o in enumerate(options))
    return base


def _item_view(item: AssessmentItem, attempt: AssessmentAttempt, intro: bool) -> dict:
    response = next((r for r in attempt.responses if r.item_id == item.id), None)
    say = _say(item, attempt.language)
    if intro:
        intro = spec_for(attempt.instrument.key, attempt.instrument.version).intro
        say = getattr(intro, attempt.language) + " " + say
    content = item.content
    view = {
        "key": item.key, "type": item.item_type, "section": content["section"], "prompt": content["prompt"],
        "options": [{"key": o["key"], "label": o["label"], "keywords": o.get("keywords", {})}
                    for o in content.get("options", [])],
        "say": say,
        "answer": None if response is None or response.skipped else response.answer,
    }
    if content.get("code"):
        view["code"] = content["code"]
    return view


def view(db: Session, attempt: AssessmentAttempt, profile: StudentProfile) -> dict:
    """The attempt as the client needs it: the next item, or the result when it's finished."""
    instrument = attempt.instrument
    base = {"attempt_id": attempt.id, "status": attempt.status, "language": attempt.language,
            "instrument": {"key": instrument.key, "version": instrument.version, "title": instrument.title}}
    if attempt.status == "completed":
        return {**base, "complete": True, "result": result(db, attempt)}
    item = _next_item(attempt, profile)
    if item is None:  # everything answered (e.g. the last answer was given just now)
        complete(db, attempt, profile)
        return {**base, "status": attempt.status, "complete": True, "result": result(db, attempt)}
    answered = len(attempt.path)
    return {**base, "complete": False, "item": _item_view(item, attempt, intro=answered == 0),
            "progress": {"answered": answered, "estimate": answered + _remaining(attempt, profile)},
            "can_go_back": answered > 0}


# ---------------- starting ----------------

def _current_instrument(db: Session, key: str) -> AssessmentInstrument:
    instruments = sync_instruments(db)
    if key not in instruments:
        raise AssessmentError(f"There's no assessment called '{key}'.", not_found=True)
    return instruments[key]


def _pick_form(db: Session, profile: StudentProfile, instrument: AssessmentInstrument) -> str | None:
    forms = spec_for(instrument.key).forms
    if not forms:
        return None
    used = [a.form for a in db.execute(
        select(AssessmentAttempt).where(AssessmentAttempt.student_profile_id == profile.id,
                                        AssessmentAttempt.instrument_id == instrument.id,
                                        AssessmentAttempt.status == "completed")
        .order_by(AssessmentAttempt.completed_at)).scalars()]
    if not used:
        return forms[0]
    # The form you've seen least; on a tie, not the one you saw last.
    return min(forms, key=lambda f: (used.count(f), f == used[-1], forms.index(f)))


def _prefill(db: Session, attempt: AssessmentAttempt, profile: StudentProfile) -> None:
    """What the profile already says doesn't need asking again (the academic profile's stream)."""
    stream = STREAMS.get((profile.stream or "").upper())
    item = next((i for i in attempt.instrument.items if i.key == "stream"), None)
    if stream and item is not None and _applies(item, attempt, profile, {}):
        attempt.responses.append(AssessmentResponse(item=item, answer={"option": stream}, interpreted_by="profile"))
        attempt.path = [*attempt.path, item.key]


def start(db: Session, profile: StudentProfile, key: str, language: str = "en", mode: str = "touch") -> dict:
    instrument = _current_instrument(db, key)
    language = language if language in ("en", "hi") else "en"
    open_attempts = db.execute(
        select(AssessmentAttempt).where(AssessmentAttempt.student_profile_id == profile.id,
                                        AssessmentAttempt.status == "in_progress")
        .join(AssessmentInstrument).where(AssessmentInstrument.key == key)
        .order_by(AssessmentAttempt.last_activity_at.desc())).scalars().all()
    for attempt in open_attempts:
        fresh = _now() - _aware(attempt.last_activity_at) < RESUME_WITHIN
        if fresh and attempt.instrument_id == instrument.id and attempt is open_attempts[0]:
            if not attempt.path:
                attempt.language = language  # nothing answered yet: switching language is free
            db.commit()
            return view(db, attempt, profile)
        attempt.status = "abandoned"
    attempt = AssessmentAttempt(student_profile_id=profile.id, instrument=instrument,
                                form=_pick_form(db, profile, instrument), language=language, mode=mode, path=[])
    db.add(attempt)
    _prefill(db, attempt, profile)
    db.commit()
    return view(db, attempt, profile)


# ---------------- answering ----------------

def get_attempt(db: Session, profile: StudentProfile, attempt_id: int) -> AssessmentAttempt:
    attempt = db.get(AssessmentAttempt, attempt_id)
    if attempt is None or attempt.student_profile_id != profile.id:
        raise AssessmentError("That assessment wasn't found.", not_found=True)
    return attempt


def _validate(item: AssessmentItem, answer: dict | None) -> dict:
    if not isinstance(answer, dict):
        raise AssessmentError("No answer was given.")
    if item.item_type == "marks":
        value = answer.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100:
            raise AssessmentError("Marks should be a percentage from 0 to 100.")
        return {"value": round(float(value), 1)}
    option = answer.get("option")
    if option not in {o["key"] for o in item.content.get("options", [])}:
        raise AssessmentError("That isn't one of the answers.")
    return {"option": option}


def answer(db: Session, profile: StudentProfile, attempt_id: int, item_key: str, answer: dict | None = None,
           skipped: bool = False, transcript: str | None = None, interpreted_by: str = "touch",
           response_ms: int | None = None) -> dict:
    attempt = get_attempt(db, profile, attempt_id)
    if attempt.status != "in_progress":
        raise AssessmentError("This assessment is already finished — start it again to retake it.")
    item = next((i for i in attempt.instrument.items if i.key == item_key), None)
    if item is None or not _applies(item, attempt, profile, _answers(attempt)):
        raise AssessmentError("That question isn't part of this assessment.")
    value = None if skipped else _validate(item, answer)
    response = next((r for r in attempt.responses if r.item_id == item.id), None)
    if response is None:
        response = AssessmentResponse(item=item)
        attempt.responses.append(response)
    response.answer, response.skipped = value, skipped
    response.transcript = (transcript or "")[:2000] or None
    response.interpreted_by = interpreted_by if interpreted_by in ("touch", "keywords", "llm") else "touch"
    response.response_ms = response_ms
    response.answered_at = _now()
    if item.key not in attempt.path:
        attempt.path = [*attempt.path, item.key]
    kind = "touch" if response.interpreted_by == "touch" else "voice"
    if not any(r is not response and r.interpreted_by != "profile" for r in attempt.responses):
        attempt.mode = kind
    elif attempt.mode != kind:
        attempt.mode = "mixed"
    attempt.last_activity_at = _now()
    db.flush()
    _drop_stale(db, attempt, profile)
    db.commit()
    return view(db, attempt, profile)


def back(db: Session, profile: StudentProfile, attempt_id: int) -> dict:
    """One step back: the last answered item comes up again, its answer shown, until it's answered again."""
    attempt = get_attempt(db, profile, attempt_id)
    if attempt.status != "in_progress":
        raise AssessmentError("This assessment is already finished.")
    if attempt.path:
        attempt.path = attempt.path[:-1]
        attempt.last_activity_at = _now()
        db.commit()
    return view(db, attempt, profile)


# ---------------- finishing ----------------

def _shown(attempt: AssessmentAttempt) -> list[scoring.Shown]:
    by_key = {r.item.key: r for r in attempt.responses}
    items = {i.key: i for i in attempt.instrument.items}
    return [scoring.Shown(items[k].content, by_key[k].answer, by_key[k].skipped) for k in attempt.path if k in by_key]


def complete(db: Session, attempt: AssessmentAttempt, profile: StudentProfile,
             completed_at: datetime | None = None) -> None:
    for old in list(attempt.scores):
        db.delete(old)
    attempt.scores = [AssessmentScore(dimension_key=s.dimension, score=s.score, n_items=s.n_items, detail=s.detail)
                      for s in scoring.score(attempt.instrument.scoring_method, _shown(attempt))]
    attempt.status = "completed"
    attempt.completed_at = completed_at or _now()
    if attempt.instrument.key == "academic":
        _record_marks(db, attempt, profile)
    db.flush()
    from app.assessment import alignment  # the directions depend on every instrument; imported late

    alignment.snapshot(db, profile)
    _note_on_timeline(db, attempt, profile)
    db.commit()


def _record_marks(db: Session, attempt: AssessmentAttempt, profile: StudentProfile) -> None:
    """The academic profile also fills in the student's academic record (and their stream)."""
    from app.models.student import AcademicRecord

    subject_marks = {s.dimension_key.split(":", 1)[1]: s.detail["percent"] for s in attempt.scores}
    stream = _answers(attempt).get("stream", {}).get("option")
    if stream and not profile.stream:
        profile.stream = {"pcm": "PCM", "pcb": "PCB", "pcmb": "PCMB"}.get(stream, stream)
    if subject_marks:
        year = _now().year
        db.add(AcademicRecord(student_profile_id=profile.id, academic_year=f"{year}-{str(year + 1)[-2:]}",
                              class_level=profile.class_level, subject_marks=subject_marks))


def _note_on_timeline(db: Session, attempt: AssessmentAttempt, profile: StudentProfile) -> None:
    """With the memory permission only — the timeline is part of what MAYA remembers."""
    from app.memory import consent

    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return
    db.add(StudentEvent(student_profile_id=profile.id, event_type="ASSESSMENT_COMPLETED", actor="student",
                        entity_type="assessment_attempt", entity_id=str(attempt.id),
                        payload={"instrument": attempt.instrument.key, "version": attempt.instrument.version,
                                 "title": attempt.instrument.title["en"]}))


def import_answers(db: Session, profile: StudentProfile, answers: dict[str, str], legacy_assessment_id: int | None = None,
                   completed_at: datetime | None = None) -> AssessmentAttempt:
    """A finished interests attempt from MAYA's original quiz answers ({question id: option id} —
    the same ids interests v1 uses): how old assessments, and the old endpoint, reach the new tables."""
    instrument = _current_instrument(db, "interests")
    attempt = AssessmentAttempt(student_profile_id=profile.id, instrument=instrument, language="en", mode="touch",
                                path=[], legacy_assessment_id=legacy_assessment_id)
    if completed_at is not None:
        attempt.started_at = attempt.last_activity_at = completed_at
    db.add(attempt)
    given: dict[str, dict] = {}
    for item in instrument.items:
        option = answers.get(item.key)
        if option is None or option not in {o["key"] for o in item.content["options"]} \
                or not _applies(item, attempt, profile, given):
            continue
        given[item.key] = {"option": option}
        attempt.responses.append(AssessmentResponse(item=item, answer={"option": option}, interpreted_by="touch"))
        attempt.path = [*attempt.path, item.key]
    complete(db, attempt, profile, completed_at=completed_at)
    return attempt


# ---------------- results ----------------

def _phrase(dim: str, s: AssessmentScore, method: str, lang: str) -> str:
    d = s.detail
    if method == "correct_answers":
        extra = (f", {d['skipped']} skipped" if lang == "en" else f", {d['skipped']} छोड़े") if d.get("skipped") else ""
        return f"{d['correct']} of {d['asked']} right{extra}" if lang == "en" else f"{d['asked']} में से {d['correct']} सही{extra}"
    if method == "anchored_levels":
        return f"level {d['level']} of {d['of']}" if lang == "en" else f"स्तर {d['of']} में से {d['level']}"
    if method == "marks":
        return f"{d['percent']:g}%"
    return f"{round(s.score * 100)}%"


def result(db: Session, attempt: AssessmentAttempt) -> dict:
    try:
        dims = spec_for(attempt.instrument.key, attempt.instrument.version).dimensions
    except KeyError:  # a version whose file is gone: fall back to the raw keys
        dims = {}
    method = attempt.instrument.scoring_method
    scores = []
    for s in sorted(attempt.scores, key=lambda s: -s.score):
        d = dims.get(s.dimension_key)
        scores.append({
            "dimension": s.dimension_key, "group": d.group if d else s.dimension_key.split(":")[0],
            "label": {"en": d.en, "hi": d.hi} if d else {"en": s.dimension_key, "hi": s.dimension_key},
            "score": s.score, "n_items": s.n_items, "detail": s.detail,
            "says": {"en": _phrase(s.dimension_key, s, method, "en"), "hi": _phrase(s.dimension_key, s, method, "hi")},
        })
    out = {"attempt_id": attempt.id, "instrument": attempt.instrument.key, "version": attempt.instrument.version,
           "title": attempt.instrument.title, "method": method, "form": attempt.form, "language": attempt.language,
           "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None, "scores": scores}
    if method == "correct_answers":
        out["review"] = _review(attempt)
    return out


def _review(attempt: AssessmentAttempt) -> list[dict]:
    """Each problem: what you picked, what was right, and why — for learning, after the test."""
    by_key = {r.item.key: r for r in attempt.responses}
    items = {i.key: i for i in attempt.instrument.items}
    review = []
    for key in attempt.path:
        item, response = items[key].content, by_key.get(key)
        picked = None if response is None or response.skipped or not response.answer else response.answer.get("option")
        review.append({"key": key, "prompt": item["prompt"], "code": item.get("code"),
                       "options": [{"key": o["key"], "label": o["label"]} for o in item["options"]],
                       "picked": picked, "answer": item["answer"], "right": picked == item["answer"],
                       "explanation": item.get("explanation")})
    return review


def instruments(db: Session, profile: StudentProfile) -> list[dict]:
    """Every assessment, with when you last took it and whether one is half-done."""
    out = []
    for key, row in sync_instruments(db).items():
        spec = spec_for(key)
        attempts = db.execute(
            select(AssessmentAttempt).join(AssessmentInstrument)
            .where(AssessmentAttempt.student_profile_id == profile.id, AssessmentInstrument.key == key,
                   AssessmentAttempt.status.in_(("completed", "in_progress")))
            .order_by(AssessmentAttempt.started_at.desc())).scalars().all()
        done = [a for a in attempts if a.status == "completed"]
        unfinished = next((a for a in attempts if a.status == "in_progress"
                           and a.instrument_id == row.id and _now() - _aware(a.last_activity_at) < RESUME_WITHIN), None)
        out.append({
            "key": key, "version": row.version, "category": row.category, "title": row.title,
            "about": spec.about.model_dump(), "est_minutes": row.est_minutes,
            "times_taken": len(done),
            "last_completed": ({"attempt_id": done[0].id, "completed_at": done[0].completed_at.isoformat()}
                               if done else None),
            "in_progress": ({"attempt_id": unfinished.id, "answered": len(unfinished.path)} if unfinished else None),
        })
    order = ["interests", "aptitude", "skills", "academic", "coding_check"]
    return sorted(out, key=lambda i: order.index(i["key"]) if i["key"] in order else len(order))


def history(db: Session, profile: StudentProfile, key: str) -> dict:
    """Every completed attempt at one assessment, oldest first, and how the latest compares with
    the first and with the one before — only changes bigger than the noise are called changes."""
    attempts = db.execute(
        select(AssessmentAttempt).join(AssessmentInstrument)
        .where(AssessmentAttempt.student_profile_id == profile.id, AssessmentInstrument.key == key,
               AssessmentAttempt.status == "completed")
        .order_by(AssessmentAttempt.completed_at)).scalars().all()
    results = [result(db, a) for a in attempts]
    out = {"instrument": key, "attempts": results, "since_first": None, "since_previous": None}
    if len(results) >= 2:
        out["since_first"] = compare(results[0], results[-1])
        out["since_previous"] = compare(results[-2], results[-1])
    return out


def compare(before: dict, after: dict) -> list[dict]:
    old = {s["dimension"]: s for s in before["scores"]}
    rows = []
    for s in after["scores"]:
        if s["dimension"] not in old:
            continue
        o = old[s["dimension"]]
        rows.append({"dimension": s["dimension"], "label": s["label"], "before": o["says"], "after": s["says"],
                     "before_score": o["score"], "after_score": s["score"],
                     "change": scoring.changed(after["method"], o, s),
                     "note": ("different language" if before["language"] != after["language"]
                              and s["dimension"] == "aptitude:verbal" else None)})
    return rows


def delete_attempt(db: Session, profile: StudentProfile, attempt_id: int) -> None:
    """A real delete: the answers, the scores, the directions worked out from them, and the
    timeline entry."""
    attempt = get_attempt(db, profile, attempt_id)
    for snap in db.execute(select(CareerAlignmentSnapshot)
                           .where(CareerAlignmentSnapshot.student_profile_id == profile.id)).scalars():
        if attempt.id in (snap.inputs or {}).values():
            db.delete(snap)
    for event in db.execute(select(StudentEvent).where(StudentEvent.student_profile_id == profile.id,
                                                       StudentEvent.entity_type == "assessment_attempt",
                                                       StudentEvent.entity_id == str(attempt.id))).scalars():
        db.delete(event)
    db.delete(attempt)
    db.commit()
