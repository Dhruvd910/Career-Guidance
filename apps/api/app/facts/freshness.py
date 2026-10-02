"""How long each kind of fact stays current (spec §16, doc 06 §4), and the label a student sees.

Policies live here, reviewed like code. The longest matching attribute prefix wins. A fee belongs
to an academic year: it stays current until the next year's admissions begin (1 August after
its year starts) — then, with no newer fact, it's stale. Everything else ages by days since it
was last checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

CYCLE_TURNS = (8, 1)  # a new admission cycle is under way from 1 August


@dataclass(frozen=True)
class Policy:
    prefix: str
    refresh_days: int  # how often the refresh job looks again
    stale_after_days: int  # since last checked
    by_academic_year: bool = False  # also stale once its academic year's cycle has passed


POLICIES = (
    Policy("admission.", refresh_days=7, stale_after_days=30),
    Policy("fee.", refresh_days=60, stale_after_days=400, by_academic_year=True),
    Policy("facility.", refresh_days=180, stale_after_days=400),
    Policy("placement.", refresh_days=180, stale_after_days=400, by_academic_year=True),
    Policy("ranking.", refresh_days=90, stale_after_days=400),
    Policy("near.", refresh_days=365, stale_after_days=400),
    Policy("location.website", refresh_days=90, stale_after_days=400),
    Policy("location.", refresh_days=365, stale_after_days=3 * 365),
    Policy("academic.", refresh_days=365, stale_after_days=5 * 365),
)
DEFAULT = Policy("", refresh_days=180, stale_after_days=400)


def policy_for(attribute: str) -> Policy:
    matches = [p for p in POLICIES if attribute.startswith(p.prefix)]
    return max(matches, key=lambda p: len(p.prefix)) if matches else DEFAULT


def _as_date(moment: datetime | date | None) -> date | None:
    if moment is None:
        return None
    if isinstance(moment, datetime):
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).date()
    return moment


def cycle_over(academic_year: str | None, today: date) -> bool:
    """'2026-27' → its fees are superseded once the 2027-28 cycle starts (1 Aug 2027)."""
    if not academic_year or len(academic_year) < 4 or not academic_year[:4].isdigit():
        return False
    start = int(academic_year[:4])
    return today >= date(start + 1, *CYCLE_TURNS)


def is_stale(attribute: str, verified_at: datetime | date | None, academic_year: str | None, today: date) -> bool:
    policy = policy_for(attribute)
    checked = _as_date(verified_at)
    if checked is None:
        return False  # never checked is "needs verification", not stale
    if (today - checked).days > policy.stale_after_days:
        return True
    return policy.by_academic_year and cycle_over(academic_year, today)


def is_due(attribute: str, verified_at: datetime | date | None, today: date) -> bool:
    checked = _as_date(verified_at)
    return checked is None or (today - checked).days >= policy_for(attribute).refresh_days


def label(status: str, attribute: str, verified_at: datetime | date | None, academic_year: str | None,
          today: date) -> dict:
    """{"en": "Verified 7 days ago", "hi": "7 दिन पहले जाँचा गया", "state": "fresh"} and so on."""
    checked = _as_date(verified_at)
    when = checked.strftime("%-d %b %Y") if checked else None
    if status == "not_available":
        return {"en": f"Not found (looked {when})" if when else "Not found",
                "hi": f"नहीं मिला ({when} को देखा)" if when else "नहीं मिला", "state": "not_available"}
    if status in ("unverified",) or checked is None:
        return {"en": "Needs verification", "hi": "जाँच बाक़ी", "state": "unverified"}
    if is_stale(attribute, verified_at, academic_year, today):
        return {"en": f"Stale — as of {when}", "hi": f"पुराना — {when} तक का", "state": "stale"}
    days = (today - checked).days
    if days <= 0:
        return {"en": "Verified today", "hi": "आज जाँचा गया", "state": "fresh"}
    if days == 1:
        return {"en": "Verified yesterday", "hi": "कल जाँचा गया", "state": "fresh"}
    return {"en": f"Verified {days} days ago", "hi": f"{days} दिन पहले जाँचा गया", "state": "fresh"}


def stale_at(attribute: str, verified_at: datetime | date | None, academic_year: str | None) -> datetime | None:
    """The instant a value becomes stale (OKF's `stale_after`): its policy's age limit, or the
    start of the next admission cycle for values tied to an academic year — whichever is first."""
    checked = _as_date(verified_at)
    if checked is None:
        return None
    policy = policy_for(attribute)
    limit = checked.toordinal() + policy.stale_after_days + 1
    candidates = [date.fromordinal(limit)]
    if policy.by_academic_year and academic_year and academic_year[:4].isdigit():
        candidates.append(date(int(academic_year[:4]) + 1, *CYCLE_TURNS))
    first = min(candidates)
    return datetime(first.year, first.month, first.day, tzinfo=timezone.utc)
