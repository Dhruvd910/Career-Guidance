"""Transparent, rule-based college/branch prediction engine (spec §27-28).

Deliberately NOT a black-box ML model yet — §27 explicitly says to start with a
transparent baseline. This module is written as a `PredictionEngine` so a future
statistical/ML implementation can replace `_gather_options`'s scoring without touching
any caller (routers, AI tools, preference-list generator all go through `predict()` /
`generate_preference_list()`).

Every result carries the actual historical closing ranks used and how many years/rounds
were considered, so a prediction is never an unexplained score (§28).
"""

from dataclasses import dataclass
from statistics import median

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.college import CollegeCourse
from app.models.cutoff import Cutoff
from app.schemas.prediction import (
    PredictionExplanation,
    PredictionRequest,
    PredictionResponse,
    PredictionResultItem,
    PreferenceListItem,
    PreferenceListRequest,
    PreferenceListResponse,
)
from app.services.exam_service import get_exam_by_code
from app.services.rank_estimates import EstimateError, estimate_rank
from app.seed.mcc import quota_open_to as mcc_quota_open_to

# Beyond this multiple of the median closing rank, an option is not shown at all —
# stretching further than this would be false hope rather than a "dream" option.
MAX_STRETCH_FACTOR = 1.3


@dataclass
class OptionStats:
    college_course: CollegeCourse
    quota: str
    years: list[int]
    closing_ranks_by_year: dict[int, int]
    min_closing: int
    median_closing: float
    max_closing: int
    rounds_considered: int
    last_verified: str | None = None
    matched_branch_pref: bool = False
    seat_type: str = "Gender-Neutral"
    matched_state_pref: bool = False
    category: str = "General"


JOSAA_QUOTAS = {"AI", "HS", "OS", "GO", "JK", "LA"}
MCC_QUOTAS = {"AIQ", "Open", "Deemed", "Delhi", "Puducherry"}
# Exams whose counselling allots every category by the overall (All-India) rank — MCC does;
# JoSAA uses category ranks for reserved seats.
OVERALL_RANK_EXAMS = {"NEET_UG"}
SPECIAL_QUOTAS = {"GO": "Goa", "JK": "Jammu and Kashmir", "LA": "Ladakh"}


def eligible_quota(quota: str, college_state: str, domicile_state: str | None) -> bool:
    """JoSAA quotas: All-India seats are open to everyone; home-state seats only to students
    domiciled in the institute's state, other-state seats only to everyone else; Goa, J&K and
    Ladakh have their own. Quotas from other systems (NEET's) aren't filtered here."""
    if quota in MCC_QUOTAS:
        return mcc_quota_open_to(quota, domicile_state)
    if quota not in JOSAA_QUOTAS or quota == "AI":
        return True
    if quota == "HS":
        return domicile_state is not None and domicile_state == college_state
    if quota == "OS":
        return domicile_state != college_state
    return domicile_state == SPECIAL_QUOTAS[quota] and college_state == SPECIAL_QUOTAS[quota]


# NIT/IIIT/GFTI architecture and planning seats are allotted on JEE Main Paper 2 ranks, a
# separate rank list from the B.Tech (Paper 1) rank students enter here. (IIT B.Arch uses the
# JEE Advanced rank plus the AAT, so it stays.)
PAPER_2_COURSES = {"B.Arch", "B.Plan"}


def uses_paper_2(cc: CollegeCourse) -> bool:
    return cc.exam.code == "JEE_MAIN" and cc.course.name in PAPER_2_COURSES


def _gather_options(
    db: Session,
    exam_id: int,
    category: str | list[str],
    quota: str | None,
    preferred_branches: list[str],
    preferred_states: list[str],
    college_type_preference: str | None,
    seat_types: list[str] | None = None,
    domicile_state: str | None = None,
) -> list[OptionStats]:
    categories = [category] if isinstance(category, str) else category
    query = db.query(CollegeCourse).filter(CollegeCourse.exam_id == exam_id)
    college_courses = query.all()

    options: list[OptionStats] = []
    for cc in college_courses:
        if uses_paper_2(cc):
            continue
        if college_type_preference and college_type_preference != "any":
            # Deemed universities charge private fees, so "private" includes them.
            ownership = "private" if cc.college.ownership == "deemed" else cc.college.ownership
            if ownership != college_type_preference:
                continue
        if preferred_states and cc.college.state not in preferred_states:
            continue
        if preferred_branches and cc.branch is not None:
            branch_match = any(pb.lower() in cc.branch.name.lower() for pb in preferred_branches)
            if not branch_match:
                continue

        cutoff_query = db.query(Cutoff).filter(
            Cutoff.college_course_id == cc.id, Cutoff.category.in_(categories)
        )
        if quota:
            cutoff_query = cutoff_query.filter(Cutoff.quota == quota)
        if seat_types:
            cutoff_query = cutoff_query.filter(Cutoff.seat_type.in_(seat_types))
        cutoffs = [
            c for c in cutoff_query.all()
            if quota or eligible_quota(c.quota, cc.college.state, domicile_state)
        ]
        if not cutoffs:
            continue

        by_quota: dict[tuple[str, str, str], list[Cutoff]] = {}
        for c in cutoffs:
            by_quota.setdefault((c.category, c.quota, c.seat_type or GENDER_NEUTRAL), []).append(c)

        for (cutoff_category, quota_name, seat_type), rows in by_quota.items():
            by_year: dict[int, list[Cutoff]] = {}
            for r in rows:
                by_year.setdefault(r.year, []).append(r)
            # Representative closing rank per year = the latest round (closest to final result).
            closing_by_year = {
                year: max(year_rows, key=lambda r: r.round).closing_rank
                for year, year_rows in by_year.items()
            }
            closings = list(closing_by_year.values())
            latest_verified = max((r.last_verified for r in rows if r.last_verified), default=None)

            options.append(
                OptionStats(
                    college_course=cc,
                    quota=quota_name,
                    seat_type=seat_type,
                    category=cutoff_category,
                    years=sorted(closing_by_year.keys()),
                    closing_ranks_by_year=closing_by_year,
                    min_closing=min(closings),
                    median_closing=median(closings),
                    max_closing=max(closings),
                    rounds_considered=len(rows),
                    last_verified=latest_verified.date().isoformat() if latest_verified else None,
                    matched_branch_pref=bool(preferred_branches) and cc.branch is not None,
                    matched_state_pref=bool(preferred_states),
                )
            )
    return options


def _band_for_ratio(ratio: float) -> tuple[str, str, str] | None:
    """Returns (band, label, emoji) for predict(), or None if beyond the stretch factor."""
    if ratio <= 0.85:
        return "high_probability", "High Probability", "🟢"
    if ratio <= 1.05:
        return "possible", "Possible", "🟡"
    if ratio <= MAX_STRETCH_FACTOR:
        return "ambitious", "Ambitious/Dream", "🔴"
    return None


def _confidence_for(years_considered: int) -> str:
    if years_considered >= 3:
        return "High"
    if years_considered == 2:
        return "Medium"
    return "Low"


QUOTA_NAMES = {"AI": "All-India", "HS": "home-state", "OS": "other-state", "GO": "Goa", "JK": "J&K", "LA": "Ladakh",
               "AIQ": "All-India quota", "Open": "open (AIIMS/JIPMER)", "Deemed": "deemed-university",
               "Delhi": "Delhi-domicile", "Puducherry": "Puducherry-domicile"}


def _reasoning(rank: int, opt: OptionStats, band_label: str) -> str:
    which = "category rank" if opt.category != "General" else "rank"
    seats = f"{opt.category if opt.category != 'General' else 'OPEN'} {QUOTA_NAMES.get(opt.quota, opt.quota)} seats"
    if len(opt.years) == 1:
        return (
            f"In {opt.years[0]} (final round) this closed at {which} {opt.max_closing:,} for {seats}. "
            f"Your {which} is {rank:,}, which puts it in the \"{band_label}\" range. "
            f"That's one year of data, so treat it as a guide — cutoffs move every year."
        )
    years_str = ", ".join(str(y) for y in opt.years)
    return (
        f"For {seats}, your {which} ({rank:,}) compares against a median closing rank of "
        f"{round(opt.median_closing):,} across {len(opt.years)} years ({years_str}), "
        f"ranging from {opt.min_closing:,} to {opt.max_closing:,}. This places the option in "
        f"the \"{band_label}\" range."
    )


GENDER_NEUTRAL = "Gender-Neutral"
FEMALE_ONLY = "Female-only (including Supernumerary)"


def seat_types_for(gender: str | None) -> list[str]:
    """JoSAA reserves supernumerary seats for women; they can take either pool."""
    return [GENDER_NEUTRAL, FEMALE_ONLY] if (gender or "").lower() == "female" else [GENDER_NEUTRAL]


def resolve_rank(request: PredictionRequest) -> tuple[int, bool, str | None]:
    """(rank, whether it's an estimate, where the estimate came from)."""
    if request.rank:
        return request.rank, False, None
    try:
        rank, basis = estimate_rank(request.exam_code, request.percentile, request.score)
    except EstimateError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return rank, True, basis


def _categories_and_notes(request: PredictionRequest) -> tuple[list[str], list[str]]:
    """Which seat categories to consider. Everyone can take OPEN seats (compared with their
    overall rank); reserved-category seats are compared with the *category* rank, as JoSAA
    publishes them — so they're only included when the student has given one. MCC (NEET)
    allots every category by All-India Rank, so there it needs nothing extra."""
    if request.category in (None, "", "General"):
        return ["General"], []
    if request.exam_code in OVERALL_RANK_EXAMS:
        return ["General", request.category], []
    if request.category_rank:
        return ["General", request.category], []
    return ["General"], [
        f"Showing OPEN seats only. Add your {request.category} category rank to include "
        f"{request.category}-reserved seats — those are allotted by category rank, not overall rank."
    ]


def _rank_for(request: PredictionRequest, opt: OptionStats) -> int:
    """The rank this seat is actually allotted by."""
    if opt.category == "General" or request.exam_code in OVERALL_RANK_EXAMS:
        return request.rank
    return request.category_rank


def predict(db: Session, request: PredictionRequest) -> PredictionResponse:
    exam = get_exam_by_code(db, request.exam_code)
    rank, estimated, basis = resolve_rank(request)
    request = request.model_copy(update={"rank": rank})
    categories, notes = _categories_and_notes(request)
    options = _gather_options(
        db,
        exam.id,
        categories,
        request.quota,
        request.preferred_branches,
        request.preferred_states,
        request.college_type_preference,
        seat_types_for(request.gender),
        request.domicile_state,
    )

    scored_results: list[tuple[int, float, PredictionResultItem]] = []
    band_order = {"high_probability": 0, "possible": 1, "ambitious": 2}
    for opt in options:
        compare_rank = _rank_for(request, opt)
        ratio = compare_rank / opt.median_closing
        band_info = _band_for_ratio(ratio)
        if band_info is None:
            continue
        band, band_label, emoji = band_info
        cc = opt.college_course

        item = PredictionResultItem(
                college_id=cc.college_id,
                college_name=cc.college.canonical_name,
                college_type=cc.college.college_type,
                city=cc.college.city,
                state=cc.college.state,
                course_name=cc.course.name,
                branch_name=cc.branch.name if cc.branch else None,
                category=opt.category,
                quota=opt.quota,
                seat_type=opt.seat_type,
                band=band,
                band_label=band_label,
                band_emoji=emoji,
                confidence=_confidence_for(len(opt.years)),
                explanation=PredictionExplanation(
                    years_considered=opt.years,
                    historical_closing_ranks={str(y): r for y, r in opt.closing_ranks_by_year.items()},
                    rounds_considered=opt.rounds_considered,
                    data_freshness=opt.last_verified,
                    reasoning=_reasoning(compare_rank, opt, band_label),
                ),
                is_demo_data=cc.college.is_demo_data,
            )
        scored_results.append((band_order[band], opt.median_closing, item))

    # One entry per college and course: a student eligible for several seat pools there (OPEN
    # and OBC, home-state and All-India…) sees the pool that gives them the best chance.
    best: dict[tuple, tuple[int, float, float, PredictionResultItem]] = {}
    for band_rank, median_closing, item in scored_results:
        ratio_rank = band_rank
        key = (item.college_id, item.course_name, item.branch_name)
        current = best.get(key)
        if current is None or (ratio_rank, -median_closing) < (current[0], -current[1]):
            best[key] = (ratio_rank, median_closing, median_closing, item)
    ordered = sorted(best.values(), key=lambda t: (t[0], t[2]))
    results = [item for *_rest, item in ordered]

    return PredictionResponse(
        exam_code=exam.code, student_rank=rank, rank_estimated=estimated, rank_basis=basis, results=results,
        notes=notes,
    )


_PREFERENCE_LABELS = [
    (0.60, "Safe"),
    (0.85, "Good Chance"),
    (1.05, "Possible"),
    (1.20, "Ambitious"),
    (MAX_STRETCH_FACTOR, "Dream"),
]


def _preference_label(ratio: float) -> str | None:
    for threshold, label in _PREFERENCE_LABELS:
        if ratio <= threshold:
            return label
    return None


def generate_preference_list(db: Session, request: PreferenceListRequest) -> PreferenceListResponse:
    exam = get_exam_by_code(db, request.exam_code)
    rank, _estimated, _basis = resolve_rank(request)
    request = request.model_copy(update={"rank": rank})
    categories, _notes = _categories_and_notes(request)
    options = _gather_options(
        db,
        exam.id,
        categories,
        request.quota,
        request.preferred_branches,
        request.preferred_states,
        request.college_type_preference,
        seat_types_for(request.gender),
        request.domicile_state,
    )

    scored = []
    for opt in options:
        compare_rank = _rank_for(request, opt)
        ratio = compare_rank / opt.median_closing
        label = _preference_label(ratio)
        if label is None:
            continue
        scored.append((ratio, label, opt))

    # Dream (most aspirational, highest ratio) first, descending down to Safe —
    # matching the counselling choice-filling convention in §21.
    scored.sort(key=lambda t: t[0], reverse=True)

    items = []
    for i, (ratio, label, opt) in enumerate(scored, start=1):
        cc = opt.college_course
        items.append(
            PreferenceListItem(
                position=i,
                college_id=cc.college_id,
                college_name=cc.college.canonical_name,
                course_name=cc.course.name,
                branch_name=cc.branch.name if cc.branch else None,
                label=label,
                explanation=_reasoning(request.rank, opt, label),
            )
        )

    return PreferenceListResponse(items=items)
