from datetime import datetime

from pydantic import BaseModel, Field


class ProvenanceOut(BaseModel):
    source: str
    source_url: str | None
    academic_year: str | None
    last_verified: datetime | None
    verification_status: str  # verified | partially_verified | unverified_demo

    model_config = {"from_attributes": True}


class BranchOut(BaseModel):
    id: int
    name: str
    code: str

    model_config = {"from_attributes": True}


class CollegeCourseOut(BaseModel):
    id: int
    course_name: str
    branch: BranchOut | None
    exam_code: str
    total_seats: int | None
    provenance: ProvenanceOut


class CollegeSummary(BaseModel):
    """The §36 college card shape."""

    id: int
    canonical_name: str
    college_type: str
    ownership: str
    state: str
    city: str
    is_demo_data: bool
    average_rating: float | None = None
    review_count: int = 0
    nirf_rank: int | None = None  # NIRF's own ranking pages (facts), else the researched profile
    researched: bool = False  # has a hand-researched profile

    model_config = {"from_attributes": True}


class SourceOut(BaseModel):
    name: str
    url: str | None = None


class NirfOut(BaseModel):
    year: int
    category: str
    rank: int
    source: SourceOut | None = None


class ProfileFeesOut(BaseModel):
    summary: str
    tuition_per_year: int | None = None
    waivers: str | None = None
    living: str | None = None
    source: SourceOut | None = None


class ProfilePlacementsOut(BaseModel):
    period: str | None = None
    median_lpa: float | None = None
    average_lpa: float | None = None
    highest: str | None = None
    source_note: str | None = None
    note: str | None = None  # medicine: why there are no campus placements
    source: SourceOut | None = None


class SurroundingsOut(BaseModel):
    area: str | None = None
    airport: str | None = None
    railway: str | None = None
    local_transport: str | None = None
    daily_needs: str | None = None


class CollegeProfileOut(BaseModel):
    """Researched facts for the colleges students compare most (app/seed/data/college_profiles.json)."""

    website: str | None = None
    established: int | None = None
    hospital: str | None = None
    nirf: NirfOut | None = None
    fees: ProfileFeesOut | None = None
    placements: ProfilePlacementsOut | None = None
    surroundings: SurroundingsOut | None = None
    sources: list[SourceOut] = Field(default_factory=list)


class ProgramCutoffOut(BaseModel):
    program: str
    closing_rank: int
    quota: str


class AdmissionSummaryOut(BaseModel):
    """Closing ranks for open, gender-neutral, all-India seats in the latest year loaded."""

    exam_code: str
    year: int
    round: int
    source: str
    source_url: str | None = None
    program_count: int
    toughest: ProgramCutoffOut
    easiest: ProgramCutoffOut
    programs: list[ProgramCutoffOut]


class CollegeDetail(CollegeSummary):
    aliases: list[str]
    established_year: int | None
    affiliated_university: str | None
    accreditation: str | None
    official_website: str | None
    logo_url: str | None
    courses_offered: list[CollegeCourseOut] = Field(default_factory=list)
    profile: CollegeProfileOut | None = None
    admission: AdmissionSummaryOut | None = None
    # Phase 6: everything known from outside, grouped (Academic, Financial, Campus, Location,
    # Admissions), each a FactView with its source and freshness; and the documents behind them.
    facts: dict[str, dict[str, dict]] = Field(default_factory=dict)
    sources: list[dict] = Field(default_factory=list)


class CutoffOut(BaseModel):
    id: int
    program: str | None = None  # "Computer Science and Engineering (B.Tech)", "MBBS"
    year: int
    round: int
    category: str
    quota: str
    seat_type: str
    opening_rank: int | None
    closing_rank: int
    provenance: ProvenanceOut


class CollegeReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list)


class CollegeReviewOut(CollegeReviewCreate):
    id: int
    college_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CollegeCompareRequest(BaseModel):
    college_ids: list[int] = Field(min_length=2, max_length=4)


class CollegeCompareRow(BaseModel):
    college: CollegeSummary
    lowest_closing_rank_seen: int | None
    approximate_annual_cost: float | None
    hostel_available: bool | None  # None: not known — never guessed
    placement_percentage: float | None
    average_package: float | None
    average_rating: float | None
    profile: CollegeProfileOut | None = None
    admission: AdmissionSummaryOut | None = None
    facts: dict[str, dict | None] = Field(default_factory=dict)  # comparison cells, each with source and freshness


class CollegeCompareResponse(BaseModel):
    rows: list[CollegeCompareRow]
    ai_summary: str | None = None
