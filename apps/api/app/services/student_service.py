from sqlalchemy.orm import Session

from app.models.student import AcademicRecord, StudentProfile
from app.schemas.student import AcademicRecordCreate, NextOnboardingStep, StudentProfileUpdate


def update_profile(db: Session, profile: StudentProfile, payload: StudentProfileUpdate) -> StudentProfile:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


def add_academic_record(db: Session, profile: StudentProfile, payload: AcademicRecordCreate) -> AcademicRecord:
    record = AcademicRecord(student_profile_id=profile.id, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# Which world a target exam belongs to. Used to keep suggestions on the student's own track.
EXAM_TRACKS = {"JEE_MAIN": "engineering", "JEE_ADVANCED": "engineering", "NEET_UG": "medical"}
TRACK_LABELS = {"engineering": "engineering", "medical": "medical"}


def in_college(profile: StudentProfile) -> bool:
    stage = profile.education_stage or ""
    return stage.startswith("ug_") or stage in ("pg", "graduate")


def stage_label(profile: StudentProfile) -> str:
    """'Class 7', 'College, year 2', 'Graduated' — what to call where the student is."""
    stage = profile.education_stage or ""
    if stage.startswith("ug_y"):
        return f"College, year {stage[4:]}"
    return {"pg": "Postgraduate", "graduate": "Graduated", "dropper": f"Class {profile.class_level} done, taking a year"}.get(
        stage, f"Class {profile.class_level}")


def student_track(profile: StudentProfile) -> str | None:
    """'engineering', 'medical', or None while the student is still exploring."""
    return EXAM_TRACKS.get(profile.target_exam_code or "")


def get_next_onboarding_step(profile: StudentProfile, db: Session | None = None) -> NextOnboardingStep:
    """Progressive profiling (§3/§33): only ask for what's still missing, and branch by
    class + the "do you know your career?" answer, per the §55 core user flow. With `db`, the
    memory permission is asked once, right after the basics: without it MAYA can't pick up where
    she left off (spec §6), and it's off until someone decides."""

    college = in_college(profile)
    missing_basic = [  # a school board means little once at college
        f for f in ("state", "domicile_state", "school_board") if getattr(profile, f) is None and not (college and f == "school_board")
    ]
    if missing_basic:
        return NextOnboardingStep(
            step="basic_info",
            missing_fields=missing_basic,
            prompt="Let's start with a few basics about you and your school.",
        )

    if db is not None:
        from app.memory import consent

        if consent.current(db, profile, consent.LONG_TERM_MEMORY) is None:
            return NextOnboardingStep(
                step="memory_permission",
                missing_fields=[consent.LONG_TERM_MEMORY],
                prompt="Can I remember what we talk about, so next time we can pick up where we left off? "
                       + ("A parent or guardian decides this for students under 18." if consent.is_minor(profile)
                          else "You can see or delete anything I remember."),
            )

    if college:
        return NextOnboardingStep(
            step="skills_assessment",
            missing_fields=[],
            prompt="Let's see where your skills stand and where your degree can lead — projects, internships, jobs.",
        )

    if profile.class_level <= 9:
        return NextOnboardingStep(
            step="career_exploration_assessment",
            missing_fields=[],
            prompt="Let's explore your interests and strengths — no career decisions needed yet.",
        )

    if profile.class_level == 10:
        return NextOnboardingStep(
            step="stream_assessment",
            missing_fields=[],
            prompt="Let's figure out which stream (PCM/PCB/Commerce/Arts) may suit you best.",
        )

    # class 11/12
    if profile.knows_career_goal is None:
        return NextOnboardingStep(
            step="career_goal_question",
            missing_fields=["knows_career_goal"],
            prompt="Do you already know what career or exam you want to prepare for?",
        )

    if profile.knows_career_goal:
        return NextOnboardingStep(
            step="exam_selection",
            missing_fields=[],
            prompt="Which exam or path are you preparing for — JEE, NEET, or something else?",
        )

    return NextOnboardingStep(
        step="career_counselling_assessment",
        missing_fields=[],
        prompt="Let's run a structured career counselling conversation to find what may fit you.",
    )
