import os

# Never the background memory sweeper in tests: it would work on the real database.
os.environ["MEMORY_SWEEPER"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.db import Base, get_db
from app.main import app
from app.models.college import Branch, College, CollegeCourse, Course
from app.models.cutoff import Cutoff
from app.models.exam import Exam

# In-memory SQLite by default (fast). MAYA_TEST_DATABASE_URL=<postgres url> runs the same tests
# against PostgreSQL — what production uses since Phase 2.
TEST_DATABASE_URL = os.environ.get("MAYA_TEST_DATABASE_URL", "sqlite://")


@pytest.fixture()
def db_session():
    if TEST_DATABASE_URL.startswith("sqlite"):
        engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_jee(db_session):
    """A minimal, hand-controlled dataset so prediction-band assertions are exact."""
    exam = Exam(code="JEE_MAIN", name="JEE Main", category="engineering")
    db_session.add(exam)
    db_session.flush()

    course = Course(name="B.Tech", level="UG", duration_years=4)
    db_session.add(course)
    db_session.flush()

    branch = Branch(course_id=course.id, name="Computer Science and Engineering", code="CSE")
    db_session.add(branch)
    db_session.flush()

    college = College(
        canonical_name="Test Institute of Technology", college_type="NIT", ownership="government",
        state="TestState", city="TestCity", is_demo_data=True,
    )
    db_session.add(college)
    db_session.flush()

    college_course = CollegeCourse(
        college_id=college.id, course_id=course.id, branch_id=branch.id, exam_id=exam.id, total_seats=60,
    )
    db_session.add(college_course)
    db_session.flush()

    # Closing rank of 1000 (General, AI quota) across three years — deliberately exact
    # round numbers so the median/min/max math in the assertions is unambiguous.
    for year, closing in [(2023, 1000), (2024, 1000), (2025, 1000)]:
        db_session.add(
            Cutoff(
                college_course_id=college_course.id, year=year, round=1, category="General",
                quota="AI", seat_type="Gender-Neutral", opening_rank=800, closing_rank=closing,
                source="test", verification_status="unverified_demo",
            )
        )
    db_session.commit()
    return {"exam": exam, "college": college, "college_course": college_course}
