"""What MAYA knows of the student's assessments, for every reply (docs/design/12-phase3-plan.md
Step 6): a few lines — what they've taken and when, what stood out, the directions by band,
and what's left to take. Details come from tools when the conversation needs them.

Assessment results are account data, like class and marks (decision P3-7): they're here whether
or not MAYA may remember conversations.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment import alignment, service
from app.assessment.loader import instrument_files
from app.models.assessment import AssessmentAttempt, AssessmentInstrument, CareerAlignmentSnapshot
from app.models.student import StudentProfile

HEADER = ("The student's assessments — their own results, measured on the day, not verdicts. Use them, and say "
          "where they came from; never present one career as the answer:")
NONE_YET = ("The student hasn't taken any assessment yet. If they're unsure what suits them or ask what they're good "
            "at, don't guess their strengths: call suggest_assessment for \"interests\" (\"What you enjoy\", about six "
            "minutes) right away — it only puts a Start button on their screen, they decide whether to tap it — and "
            "say so in a sentence.")
BUDGET_CHARS = 1400  # ~350 tokens
SHOWN_PER_BAND = 3


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = (now - when).days
    return "today" if days < 1 else "yesterday" if days < 2 else f"{days} days ago"


def assessment_context(db: Session, profile: StudentProfile) -> str:
    now = datetime.now(timezone.utc)
    latest = alignment.latest_attempts(db, profile)
    attempts_by_key: dict[str, list] = {}
    for attempt in db.execute(select(AssessmentAttempt).join(AssessmentInstrument)
                              .where(AssessmentAttempt.student_profile_id == profile.id,
                                     AssessmentAttempt.status == "completed")).scalars():
        attempts_by_key.setdefault(attempt.instrument.key, []).append(attempt)
    lines: list[str] = []
    for key, attempt in latest.items():
        title = attempt.instrument.title["en"]
        scores = sorted(attempt.scores, key=lambda s: -s.score)
        if attempt.instrument.scoring_method == "weighted_options":
            labels = alignment.dimension_labels()

            def top(groups, n):
                return [labels[s.dimension_key]["en"] for s in scores if s.score >= 0.66
                        and labels.get(s.dimension_key, {}).get("group") in groups][:n]

            enjoys, values = top({"subject", "riasec", "work_style"}, 5), top({"values"}, 3)
            shown = "enjoys " + (", ".join(enjoys) if enjoys else "nothing strongly")
            if values:
                shown += "; matters to them: " + ", ".join(values)
        else:
            shown = "; ".join(f"{r['label']['en']} {r['says']['en']}" for r in service.result(db, attempt)["scores"])
        times = sum(1 for a in attempts_by_key.get(key, []))
        retaken = f", taken {times} times — compare_assessments shows the change" if times > 1 else ""
        lines.append(f"- {title} [{key}] ({_ago(attempt.completed_at, now)}{retaken}): {shown}")

    open_attempt = db.execute(
        select(AssessmentAttempt).join(AssessmentInstrument)
        .where(AssessmentAttempt.student_profile_id == profile.id, AssessmentAttempt.status == "in_progress")
        .order_by(AssessmentAttempt.last_activity_at.desc()).limit(1)).scalar_one_or_none()
    if open_attempt is not None and open_attempt.path:
        lines.append(f"- Unfinished: {open_attempt.instrument.title['en']}, {len(open_attempt.path)} answered — "
                     "they can pick it up where they stopped.")
    if not lines:
        return NONE_YET

    snap = db.execute(select(CareerAlignmentSnapshot)
                      .where(CareerAlignmentSnapshot.student_profile_id == profile.id)
                      .order_by(CareerAlignmentSnapshot.id.desc()).limit(1)).scalar_one_or_none()
    if snap is not None and snap.results.get("ready"):
        names = {c["career_key"]: c["name"] for d in snap.results["domains"] for c in d["careers"]}
        bands = []
        for band in ("strong", "potential", "explore"):
            keys = snap.results["summary"].get(band, [])
            if keys:
                more = f" (+{len(keys) - SHOWN_PER_BAND} more)" if len(keys) > SHOWN_PER_BAND else ""
                bands.append(f"{alignment.BAND_LABELS[band]['en'].lower()}: "
                             + ", ".join(names[k] for k in keys[:SHOWN_PER_BAND]) + more)
        if bands:  # first, so the length budget never cuts it
            lines.insert(0, "- Career directions — " + "; ".join(bands)
                         + ". explain_direction gives the reasons for any one.")
    not_taken = [spec.title.en for key, (spec, _) in instrument_files().items() if key not in latest]
    if not_taken:
        lines.append("- Not taken yet: " + ", ".join(not_taken) + ".")
    text = HEADER + "\n" + "\n".join(lines)
    return text if len(text) <= BUDGET_CHARS else text[:BUDGET_CHARS].rsplit("\n", 1)[0]
