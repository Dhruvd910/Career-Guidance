from statistics import mean

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.college import Branch, College, CollegeCourse, Course
from app.models.cutoff import Cutoff
from app.models.exam import Exam
from app.models.review import CollegeReview
from app.models.student import StudentProfile
from app.schemas.college import (
    BranchOut,
    CollegeCompareResponse,
    CollegeCompareRow,
    CollegeCourseOut,
    CollegeDetail,
    CollegeReviewCreate,
    CollegeReviewOut,
    CollegeSummary,
    CutoffOut,
    ProvenanceOut,
)
from app.facts import discover, store, topics
from app.services import college_profiles


def _rating_stats(db: Session, college_id: int) -> tuple[float | None, int]:
    ratings = [r.rating for r in db.query(CollegeReview).filter(CollegeReview.college_id == college_id).all()]
    if not ratings:
        return None, 0
    return round(mean(ratings), 1), len(ratings)


def _nirf_rank(db: Session, college_id: int) -> int | None:
    from app.facts import store

    ranks = [v["value"]["rank"] for v in store.current(db, "college", college_id, prefix="ranking.nirf").values()
             if (v["value"] or {}).get("rank")]
    return min(ranks) if ranks else None


def sources_for(db: Session, college_id: int) -> list[dict]:
    """Every document behind this college's current facts: publisher and tier, address, when fetched."""
    seen, out = set(), []
    views = topics.facts(db, college_id).values()
    for view in [v for top in views for v in [top, *(top["conflict"] or [])]]:  # a conflict's sources too
        src = view["source"]
        key = (src["url"], src["document"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"document": src["document"], "publisher": src["name"], "tier": src["tier"], "kind": src["kind"],
                    "official": src["official"], "url": src["url"], "retrieved_at": view["retrieved_at"]})
    return sorted(out, key=lambda s: (s["tier"], s["publisher"], s["document"]))


def to_summary(db: Session, college: College, nirf: int | None = -1) -> CollegeSummary:
    """nirf: the college's NIRF rank when the caller already looked it up (-1: look it up here)."""
    avg_rating, count = _rating_stats(db, college.id)
    profile = college_profiles.profile_for(college.canonical_name)
    return CollegeSummary(
        id=college.id,
        canonical_name=college.canonical_name,
        college_type=college.college_type,
        ownership=college.ownership,
        state=college.state,
        city=college.city,
        is_demo_data=college.is_demo_data,
        average_rating=avg_rating,
        review_count=count,
        nirf_rank=(_nirf_rank(db, college.id) if nirf == -1 else nirf) or ((profile or {}).get("nirf") or {}).get("rank"),
        researched=profile is not None,
    )


def programs_of(db: Session, college_id: int) -> list[CollegeCourseOut]:
    """Its programmes from the official JoSAA/MCC lists, each with where that came from."""
    return [
        CollegeCourseOut(
            id=cc.id,
            course_name=cc.course.name,
            branch=BranchOut.model_validate(cc.branch) if cc.branch else None,
            exam_code=cc.exam.code,
            total_seats=cc.total_seats,
            provenance=ProvenanceOut.model_validate(cc),
        )
        for cc in db.query(CollegeCourse).filter(CollegeCourse.college_id == college_id).all()
    ]


def to_detail(db: Session, college: College) -> CollegeDetail:
    summary = to_summary(db, college)
    courses_offered = programs_of(db, college.id)
    profile = college_profiles.profile_for(college.canonical_name)
    return CollegeDetail(
        **summary.model_dump(),
        aliases=college.aliases,
        established_year=college.established_year or (profile or {}).get("established"),
        affiliated_university=college.affiliated_university,
        accreditation=college.accreditation,
        official_website=college.official_website or (profile or {}).get("website"),
        logo_url=college.logo_url,
        courses_offered=courses_offered,
        profile=profile,
        admission=college_profiles.admission_summary(db, college.id),
        facts=discover.grouped(topics.facts(db, college.id)),
        sources=sources_for(db, college.id),
    )


def get_college_or_404(db: Session, college_id: int) -> College:
    college = db.get(College, college_id)
    if college is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "College not found")
    return college


def search_colleges(
    db: Session,
    q: str | None = None,
    exam_code: str | None = None,
    state: str | None = None,
    city: str | None = None,
    ownership: str | None = None,
    college_type: str | None = None,
    course_name: str | None = None,
) -> list[CollegeSummary]:
    query = db.query(College)

    if state:
        query = query.filter(College.state == state)
    if city:
        query = query.filter(College.city == city)
    if ownership:
        query = query.filter(College.ownership == ownership)
    if college_type:
        query = query.filter(College.college_type == college_type)
    if exam_code or course_name:
        query = query.join(CollegeCourse, CollegeCourse.college_id == College.id)
        if exam_code:
            query = query.join(Exam, Exam.id == CollegeCourse.exam_id).filter(Exam.code == exam_code.upper())
        if course_name:
            query = query.join(Course, Course.id == CollegeCourse.course_id).filter(
                Course.name.ilike(f"%{course_name}%")
            )

    colleges = query.distinct().all()

    if q:
        # Students type "IIT Bombay" or "NIT Trichy", not the official names.
        needles = college_profiles.search_variants(q)
        # Aliases (§26 canonical/alias normalization — e.g. "NIT Warangal" for "National
        # Institute of Engineering, Warangal") live in a JSON column, so this match runs
        # in Python rather than via DB-specific JSON query syntax — fine at this dataset
        # size, and stays portable if this moves to PostgreSQL later.
        colleges = [
            c for c in colleges
            if any(
                needle in c.canonical_name.lower()
                or needle in c.city.lower()
                or needle in c.state.lower()
                or any(needle in alias.lower() for alias in c.aliases)
                for needle in needles
            )
        ]

    exact = set()
    if q:
        wanted = " ".join(q.lower().split())
        exact = {c.id for c in colleges if wanted == c.canonical_name.lower() or any(wanted == a.lower() for a in c.aliases)}
    ranks = {i: min((v["value"]["rank"] for v in views.values() if (v["value"] or {}).get("rank")), default=None)
             for i, views in store.current_many(db, "college", [c.id for c in colleges], prefixes=["ranking.nirf"]).items()}
    summaries = [to_summary(db, c, nirf=ranks.get(c.id)) for c in colleges]
    # What they typed exactly ("IIT BHU") first; then researched colleges (best NIRF rank first), then by name.
    summaries.sort(key=lambda s: (s.id not in exact, not s.researched, s.nirf_rank or 10_000, s.canonical_name.lower()))
    return summaries


def get_cutoffs(
    db: Session, college_id: int, category: str | None = None, branch_name: str | None = None
) -> list[CutoffOut]:
    query = (
        db.query(Cutoff)
        .join(CollegeCourse, CollegeCourse.id == Cutoff.college_course_id)
        .filter(CollegeCourse.college_id == college_id)
    )
    if category:
        query = query.filter(Cutoff.category == category)
    if branch_name:
        query = query.join(Branch, Branch.id == CollegeCourse.branch_id).filter(
            Branch.name.ilike(f"%{branch_name}%")
        )
    cutoffs = query.order_by(Cutoff.year.desc(), Cutoff.round, Cutoff.closing_rank).all()
    return [
        CutoffOut(
            id=c.id,
            program=college_profiles.program_name(c.college_course),
            year=c.year,
            round=c.round,
            category=c.category,
            quota=c.quota,
            seat_type=c.seat_type,
            opening_rank=c.opening_rank,
            closing_rank=c.closing_rank,
            provenance=ProvenanceOut.model_validate(c),
        )
        for c in cutoffs
    ]


def add_review(
    db: Session, college_id: int, profile: StudentProfile, payload: CollegeReviewCreate
) -> CollegeReviewOut:
    get_college_or_404(db, college_id)
    review = CollegeReview(
        college_id=college_id, student_profile_id=profile.id, **payload.model_dump()
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return CollegeReviewOut.model_validate(review)


def get_reviews(db: Session, college_id: int) -> list[CollegeReviewOut]:
    reviews = db.query(CollegeReview).filter(CollegeReview.college_id == college_id).all()
    return [CollegeReviewOut.model_validate(r) for r in reviews]


COMPARE = ("fee.tuition.annual", "fee.hostel.annual", "fee.mess.annual", "facility.hostel", "facility.medical",
           "near.railway_station", "near.airport", "near.hospital", "ranking.nirf.engineering", "ranking.nirf.medical",
           "admission.route")


def compare_colleges(db: Session, college_ids: list[int]) -> CollegeCompareResponse:
    rows = []
    for college_id in college_ids:
        college = get_college_or_404(db, college_id)
        cutoffs = get_cutoffs(db, college_id)
        known = topics.facts(db, college_id)

        lowest_closing = min((c.closing_rank for c in cutoffs), default=None)
        avg_cost = discover.yearly_fee(known.get("fee.tuition.annual"))  # ₹62,500 a semester is ₹1,25,000 a year
        hostel_available = discover.has_facility(known.get("facility.hostel"))
        avg_rating, _ = _rating_stats(db, college_id)
        profile = college_profiles.profile_for(college.canonical_name)
        if avg_cost is None and profile and profile.get("fees"):
            avg_cost = profile["fees"].get("tuition_per_year")

        rows.append(
            CollegeCompareRow(
                college=to_summary(db, college),
                lowest_closing_rank_seen=lowest_closing,
                approximate_annual_cost=avg_cost,
                hostel_available=hostel_available,
                placement_percentage=None,
                average_package=None,
                facts={a: discover.brief(a, known.get(a)) for a in COMPARE},
                average_rating=avg_rating,
                profile=profile,
                admission=college_profiles.admission_summary(db, college_id),
            )
        )
    return CollegeCompareResponse(rows=rows)
