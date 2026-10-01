from statistics import mean

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.college import Branch, College, CollegeCourse, Course
from app.models.cutoff import Cutoff
from app.models.exam import Exam
from app.models.fee import Fee
from app.models.hostel import Hostel
from app.models.nearby import NearbyPlace
from app.models.placement import Placement
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
    FeeOut,
    HostelOut,
    NearbyPlaceOut,
    PlacementOut,
    ProvenanceOut,
)
from app.services import college_profiles


def _rating_stats(db: Session, college_id: int) -> tuple[float | None, int]:
    ratings = [r.rating for r in db.query(CollegeReview).filter(CollegeReview.college_id == college_id).all()]
    if not ratings:
        return None, 0
    return round(mean(ratings), 1), len(ratings)


def to_summary(db: Session, college: College) -> CollegeSummary:
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
        nirf_rank=((profile or {}).get("nirf") or {}).get("rank"),
        researched=profile is not None,
    )


def to_detail(db: Session, college: College) -> CollegeDetail:
    summary = to_summary(db, college)
    college_courses = db.query(CollegeCourse).filter(CollegeCourse.college_id == college.id).all()
    courses_offered = [
        CollegeCourseOut(
            id=cc.id,
            course_name=cc.course.name,
            branch=BranchOut.model_validate(cc.branch) if cc.branch else None,
            exam_code=cc.exam.code,
            total_seats=cc.total_seats,
            provenance=ProvenanceOut.model_validate(cc),
        )
        for cc in college_courses
    ]
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

    summaries = [to_summary(db, c) for c in colleges]
    # Researched colleges first (best NIRF rank first), then the rest by name.
    summaries.sort(key=lambda s: (not s.researched, s.nirf_rank or 10_000, s.canonical_name.lower()))
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


def get_fees(db: Session, college_id: int) -> list[FeeOut]:
    fees = (
        db.query(Fee)
        .join(CollegeCourse, CollegeCourse.id == Fee.college_course_id)
        .filter(CollegeCourse.college_id == college_id)
        .all()
    )
    return [
        FeeOut(
            id=f.id,
            academic_year=f.academic_year,
            tuition_fee=f.tuition_fee,
            admission_fee=f.admission_fee,
            exam_fee=f.exam_fee,
            hostel_fee=f.hostel_fee,
            mess_fee=f.mess_fee,
            security_deposit=f.security_deposit,
            other_charges=f.other_charges,
            approximate_annual_cost=f.approximate_annual_cost,
            provenance=ProvenanceOut.model_validate(f),
        )
        for f in fees
    ]


def get_hostels(db: Session, college_id: int) -> list[HostelOut]:
    hostels = db.query(Hostel).filter(Hostel.college_id == college_id).all()
    return [
        HostelOut(
            id=h.id,
            hostel_type=h.hostel_type,
            capacity=h.capacity,
            room_types=h.room_types,
            fee_annual=h.fee_annual,
            facilities=h.facilities,
            rules=h.rules,
            distance_from_academic_block_km=h.distance_from_academic_block_km,
            provenance=ProvenanceOut.model_validate(h),
        )
        for h in hostels
    ]


def get_placements(db: Session, college_id: int) -> list[PlacementOut]:
    placements = db.query(Placement).filter(Placement.college_id == college_id).all()
    return [
        PlacementOut(
            id=p.id,
            academic_year=p.academic_year,
            placement_percentage=p.placement_percentage,
            average_package=p.average_package,
            median_package=p.median_package,
            highest_package=p.highest_package,
            major_recruiters=p.major_recruiters,
            extra=p.extra,
            provenance=ProvenanceOut.model_validate(p),
        )
        for p in placements
    ]


def get_nearby(db: Session, college_id: int) -> list[NearbyPlaceOut]:
    places = db.query(NearbyPlace).filter(NearbyPlace.college_id == college_id).all()
    return [NearbyPlaceOut.model_validate(p) for p in places]


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


def compare_colleges(db: Session, college_ids: list[int]) -> CollegeCompareResponse:
    rows = []
    for college_id in college_ids:
        college = get_college_or_404(db, college_id)
        cutoffs = get_cutoffs(db, college_id)
        fees = get_fees(db, college_id)
        hostels = get_hostels(db, college_id)
        placements = get_placements(db, college_id)

        lowest_closing = min((c.closing_rank for c in cutoffs), default=None)
        avg_cost = mean([f.approximate_annual_cost for f in fees]) if fees else None
        placement_pct = next((p.placement_percentage for p in placements if p.placement_percentage), None)
        avg_package = next((p.average_package for p in placements if p.average_package), None)
        avg_rating, _ = _rating_stats(db, college_id)
        profile = college_profiles.profile_for(college.canonical_name)
        if avg_cost is None and profile and profile.get("fees"):
            avg_cost = profile["fees"].get("tuition_per_year")

        rows.append(
            CollegeCompareRow(
                college=to_summary(db, college),
                lowest_closing_rank_seen=lowest_closing,
                approximate_annual_cost=avg_cost,
                hostel_available=len(hostels) > 0,
                placement_percentage=placement_pct,
                average_package=avg_package,
                average_rating=avg_rating,
                profile=profile,
                admission=college_profiles.admission_summary(db, college_id),
            )
        )
    return CollegeCompareResponse(rows=rows)
