"""What the student is aiming at, and what follows from it.

A NEET student shouldn't be offered engineering colleges, branches, or mock tests (and the
other way round), so every screen that could suggest one or the other asks here first. The
answer comes from the profile the backend stores, set when the exam is chosen in onboarding
or an exam profile is saved.
"""

from app.session import session

EXAM_TRACKS = {"JEE_MAIN": "engineering", "JEE_ADVANCED": "engineering", "NEET_UG": "medical"}
TRACK_EXAM_PAGES = {"engineering": "jee", "medical": "neet"}
TRACK_LABELS = {"engineering": "JEE", "medical": "NEET"}
EXPLORING = "careers"  # chosen "something else" — still deciding


def target_exam_code() -> str | None:
    return (session.profile or {}).get("target_exam_code")


def track() -> str | None:
    """'engineering', 'medical', or None while the student is still exploring."""
    return EXAM_TRACKS.get(target_exam_code() or "")


def shows_exam_page(page_name: str) -> bool:
    """Is this exam page (jee/neet) relevant to this student? Everything is, until they choose."""
    current = track()
    if current is None:
        return True
    return TRACK_EXAM_PAGES[current] == page_name


def default_exam_code(fallback: str = "") -> str:
    """What exam filters and forms should start on."""
    code = target_exam_code()
    return code if code in EXAM_TRACKS else fallback
