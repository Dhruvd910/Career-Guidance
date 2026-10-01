from app.schemas.prediction import PredictionRequest
from app.services.prediction_service import predict


def _result_for(db_session, rank):
    response = predict(
        db_session, PredictionRequest(exam_code="JEE_MAIN", rank=rank, category="General")
    )
    return response.results[0] if response.results else None


def test_high_probability_band(db_session, seeded_jee):
    # rank 800 vs median closing rank 1000 -> ratio 0.8 <= 0.85
    result = _result_for(db_session, 800)
    assert result is not None
    assert result.band == "high_probability"
    assert result.band_emoji == "🟢"


def test_possible_band(db_session, seeded_jee):
    # rank 900 vs median closing rank 1000 -> ratio 0.9, in (0.85, 1.05]
    result = _result_for(db_session, 900)
    assert result is not None
    assert result.band == "possible"
    assert result.band_emoji == "🟡"


def test_ambitious_band(db_session, seeded_jee):
    # rank 1200 vs median closing rank 1000 -> ratio 1.2, in (1.05, 1.3]
    result = _result_for(db_session, 1200)
    assert result is not None
    assert result.band == "ambitious"
    assert result.band_emoji == "🔴"


def test_beyond_stretch_factor_is_excluded(db_session, seeded_jee):
    # rank 1400 vs median closing rank 1000 -> ratio 1.4, beyond MAX_STRETCH_FACTOR (1.3)
    result = _result_for(db_session, 1400)
    assert result is None


def test_explanation_cites_real_historical_data(db_session, seeded_jee):
    result = _result_for(db_session, 800)
    assert result.explanation.years_considered == [2023, 2024, 2025]
    assert result.explanation.historical_closing_ranks == {"2023": 1000, "2024": 1000, "2025": 1000}
    assert "1,000" in result.explanation.reasoning
    assert result.confidence == "High"  # 3 years of data


def test_prediction_never_claims_certainty(db_session, seeded_jee):
    response = predict(db_session, PredictionRequest(exam_code="JEE_MAIN", rank=800, category="General"))
    assert "not a guarantee" in response.disclaimer.lower()


def test_reserved_category_students_can_still_take_open_seats(db_session, seeded_jee):
    # Only OPEN (General) cutoffs were seeded. An OBC student competes for those too — by
    # overall rank — and is told how to include OBC seats.
    response = predict(db_session, PredictionRequest(exam_code="JEE_MAIN", rank=800, category="OBC"))
    assert [r.category for r in response.results] == ["General"]
    assert response.notes and "category rank" in response.notes[0]


def test_reserved_seats_are_compared_with_the_category_rank(db_session, seeded_jee):
    from app.models.cutoff import Cutoff

    cc = seeded_jee["college_course"]
    db_session.add(Cutoff(college_course_id=cc.id, year=2025, round=1, category="OBC", quota="AI",
                          seat_type="Gender-Neutral", opening_rank=100, closing_rank=300,
                          source="test", verification_status="unverified_demo"))
    db_session.commit()
    # Overall rank 5,000 is far beyond the OPEN closing rank (1,000) — but OBC rank 200 is well
    # inside the OBC closing rank (300).
    response = predict(db_session, PredictionRequest(
        exam_code="JEE_MAIN", rank=5000, category="OBC", category_rank=200))
    obc = [r for r in response.results if r.category == "OBC"]
    assert obc and obc[0].band == "high_probability"
    assert all(r.category != "General" for r in response.results), "5,000 overall is out of OPEN range"
    assert not response.notes


def test_home_state_seats_only_for_students_from_that_state():
    from app.services.prediction_service import eligible_quota

    assert eligible_quota("HS", "Karnataka", "Karnataka")
    assert not eligible_quota("HS", "Karnataka", "Kerala")
    assert eligible_quota("OS", "Karnataka", "Kerala")
    assert not eligible_quota("OS", "Karnataka", "Karnataka")
    assert eligible_quota("AI", "Karnataka", None)
    assert not eligible_quota("HS", "Karnataka", None), "unknown domicile: no home-state seats assumed"
    assert eligible_quota("GO", "Goa", "Goa") and not eligible_quota("GO", "Goa", "Kerala")


# ---------------- estimated ranks and seat pools ----------------

from app.services.rank_estimates import (  # noqa: E402
    EstimateError, jee_main_rank_from_percentile, neet_rank_from_score,
)


def test_jee_main_percentile_becomes_a_rank():
    assert jee_main_rank_from_percentile(99) == 15_385  # 1% of 15,38,468
    assert jee_main_rank_from_percentile(100) == 1
    assert jee_main_rank_from_percentile(90) > jee_main_rank_from_percentile(95)


def test_neet_score_becomes_a_rank_and_higher_is_better():
    assert neet_rank_from_score(600) == 10_469  # an actual 2026 data point
    ranks = [neet_rank_from_score(s) for s in (700, 650, 600, 550, 500, 400)]
    assert ranks == sorted(ranks), "more marks, better (smaller) rank"
    assert neet_rank_from_score(720) == 1


def test_impossible_inputs_are_refused():
    import pytest

    with pytest.raises(EstimateError):
        neet_rank_from_score(800)
    with pytest.raises(EstimateError):
        jee_main_rank_from_percentile(101)


def test_prediction_without_a_rank_uses_the_estimate(client, seeded_jee):
    response = client.post("/api/predict/jee", json={"exam_code": "JEE_MAIN", "percentile": 99.95, "category": "General"})
    assert response.status_code == 200
    body = response.json()
    assert body["rank_estimated"] is True and "15,38,468" in body["rank_basis"]
    assert body["student_rank"] == jee_main_rank_from_percentile(99.95)


def test_prediction_with_nothing_to_go_on_says_what_to_enter(client, seeded_jee):
    response = client.post("/api/predict/jee", json={"exam_code": "JEE_MAIN", "category": "General"})
    assert response.status_code == 400
    assert "percentile" in response.json()["detail"]


def test_nit_architecture_seats_are_not_matched_against_a_btech_rank(db_session, seeded_jee):
    # NIT B.Arch seats are allotted on JEE Main Paper 2 ranks — a different list.
    from app.models.college import CollegeCourse, Course
    from app.models.cutoff import Cutoff

    arch = Course(name="B.Arch", level="UG", duration_years=5)
    db_session.add(arch)
    db_session.flush()
    cc = CollegeCourse(college_id=seeded_jee["college"].id, course_id=arch.id, branch_id=None,
                       exam_id=seeded_jee["exam"].id)
    db_session.add(cc)
    db_session.flush()
    db_session.add(Cutoff(college_course_id=cc.id, year=2025, round=1, category="General", quota="AI",
                          seat_type="Gender-Neutral", opening_rank=10, closing_rank=5000,
                          source="test", verification_status="unverified_demo"))
    db_session.commit()
    response = predict(db_session, PredictionRequest(exam_code="JEE_MAIN", rank=800, category="General"))
    assert [r.course_name for r in response.results] == ["B.Tech"]
