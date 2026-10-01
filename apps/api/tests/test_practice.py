"""Practice papers: what gets asked, what gets marked, and what a student can't see."""

import pytest

from app.models.exam import Exam
from app.models.practice import Question, QuestionExam, TestAttempt
from app.services.practice_service import CORRECT_MARKS, WRONG_MARKS


def make_question(db, exams, subject, correct_index=0, stem=None):
    question = Question(
        subject=subject,
        topic=f"{subject} basics",
        stem=stem or f"A {subject} question about option {correct_index}?",
        options=["A", "B", "C", "D"],
        correct_index=correct_index,
        explanation="Because that's how it works.",
    )
    db.add(question)
    db.flush()
    for exam in exams:
        db.add(QuestionExam(question_id=question.id, exam_id=exam.id))
    return question


@pytest.fixture()
def bank(db_session):
    """A NEET bank with a deliberately uneven number of questions per subject."""
    neet = Exam(code="NEET_UG", name="NEET-UG", category="medical")
    jee = Exam(code="JEE_MAIN", name="JEE Main", category="engineering")
    db_session.add_all([neet, jee])
    db_session.flush()

    questions = {"Physics": [], "Chemistry": [], "Biology": [], "Maths": []}
    for i in range(9):
        questions["Physics"].append(make_question(db_session, [neet, jee], "Physics", i % 4))
    for i in range(9):
        questions["Chemistry"].append(make_question(db_session, [neet, jee], "Chemistry", i % 4))
    for i in range(18):
        questions["Biology"].append(make_question(db_session, [neet], "Biology", i % 4))
    for i in range(5):
        questions["Maths"].append(make_question(db_session, [jee], "Maths", i % 4))
    db_session.commit()
    return {"neet": neet, "jee": jee, "questions": questions}


@pytest.fixture()
def student(client):
    client.post("/api/auth/register", json={
        "email": "practice@example.com", "password": "pw-for-tests-123", "name": "Riya", "class_level": 12,
    })
    token = client.post("/api/auth/login", json={
        "email": "practice@example.com", "password": "pw-for-tests-123",
    }).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def answers_for(db_session, questions, right=0, wrong=0):
    """Answer `right` correctly, `wrong` incorrectly, leave the rest blank."""
    out = []
    for i, q in enumerate(questions):
        correct = db_session.get(Question, q["id"]).correct_index
        if i < right:
            out.append({"question_id": q["id"], "selected_index": correct})
        elif i < right + wrong:
            out.append({"question_id": q["id"], "selected_index": (correct + 1) % 4})
        else:
            out.append({"question_id": q["id"], "selected_index": None})
    return out


def test_options_report_what_can_be_practised(client, student, bank):
    options = client.get("/api/practice/options?exam_code=NEET_UG", headers=student).json()
    subjects = {s["subject"]: s for s in options["subjects"]}
    assert set(subjects) == {"Physics", "Chemistry", "Biology"}, "Maths is not a NEET subject"
    assert subjects["Biology"]["available_questions"] == 18
    assert subjects["Biology"]["question_count"] == 10  # a subject test asks 10
    # The full paper keeps NEET's 45/45/90 shape, scaled to the smallest stocked subject.
    assert options["full_test_breakdown"] == {"Physics": 9, "Chemistry": 9, "Biology": 18}
    assert options["full_test_questions"] == 36
    assert options["real_paper_questions"] == 180, "the real paper's size is stated, not implied"


def test_a_subject_test_only_asks_that_subject(client, student, bank, db_session):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Biology",
    }).json()
    assert len(attempt["questions"]) == 10
    assert {q["subject"] for q in attempt["questions"]} == {"Biology"}
    assert attempt["duration_seconds"] > 0


def test_a_full_paper_covers_every_subject(client, student, bank):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "full",
    }).json()
    counts: dict[str, int] = {}
    for q in attempt["questions"]:
        counts[q["subject"]] = counts.get(q["subject"], 0) + 1
    assert counts == {"Physics": 9, "Chemistry": 9, "Biology": 18}


def test_questions_never_carry_the_answer(client, student, bank):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Physics",
    }).json()
    for question in attempt["questions"]:
        assert "correct_index" not in question
        assert "explanation" not in question


def test_marking_follows_the_real_scheme(client, student, bank, db_session):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Biology",
    }).json()
    payload = answers_for(db_session, attempt["questions"], right=6, wrong=3)  # 1 left blank

    result = client.post(f"/api/practice/{attempt['attempt_id']}/submit", headers=student, json={
        "answers": payload, "seconds_taken": 300,
    }).json()

    assert (result["correct"], result["wrong"], result["unanswered"]) == (6, 3, 1)
    assert result["score"] == 6 * CORRECT_MARKS + 3 * WRONG_MARKS
    assert result["max_score"] == 10 * CORRECT_MARKS
    assert result["accuracy"] == 60.0


def test_review_shows_the_answer_and_why(client, student, bank, db_session):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Chemistry",
    }).json()
    payload = answers_for(db_session, attempt["questions"], right=2, wrong=1)
    result = client.post(f"/api/practice/{attempt['attempt_id']}/submit", headers=student, json={
        "answers": payload,
    }).json()

    review = result["review"]
    assert len(review) == len(attempt["questions"])
    assert review[0]["is_correct"] is True and review[0]["selected_index"] == review[0]["correct_index"]
    assert review[2]["is_correct"] is False
    assert review[-1]["selected_index"] is None and review[-1]["is_correct"] is None
    assert all(item["explanation"] for item in review)


def test_a_finished_paper_shows_up_in_score_history(client, student, bank, db_session):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Physics",
    }).json()
    client.post(f"/api/practice/{attempt['attempt_id']}/submit", headers=student, json={
        "answers": answers_for(db_session, attempt["questions"], right=4),
    })

    history = client.get("/api/mock-tests/history", headers=student).json()
    assert len(history) == 1
    assert history[0]["total_score"] == 4 * CORRECT_MARKS
    assert "practice test" in history[0]["test_name"]


def test_a_paper_cannot_be_submitted_twice(client, student, bank):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Physics",
    }).json()
    first = client.post(f"/api/practice/{attempt['attempt_id']}/submit", headers=student, json={"answers": []})
    second = client.post(f"/api/practice/{attempt['attempt_id']}/submit", headers=student, json={"answers": []})
    assert first.status_code == 200
    assert second.status_code == 409


def test_one_student_cannot_open_another_students_paper(client, student, bank):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Physics",
    }).json()
    client.post("/api/auth/register", json={
        "email": "someone-else@example.com", "password": "pw-for-tests-123", "name": "Asha", "class_level": 12,
    })
    other = client.post("/api/auth/login", json={
        "email": "someone-else@example.com", "password": "pw-for-tests-123",
    }).json()["access_token"]

    response = client.post(
        f"/api/practice/{attempt['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {other}"}, json={"answers": []},
    )
    assert response.status_code == 404


def test_an_option_that_does_not_exist_is_rejected(client, student, bank):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Physics",
    }).json()
    response = client.post(f"/api/practice/{attempt['attempt_id']}/submit", headers=student, json={
        "answers": [{"question_id": attempt["questions"][0]["id"], "selected_index": 7}],
    })
    assert response.status_code == 400


def test_a_subject_with_no_questions_says_so(client, student, bank):
    response = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Maths",
    })
    assert response.status_code == 404


def test_an_unsubmitted_paper_has_no_summary(client, student, bank, db_session):
    attempt = client.post("/api/practice/start", headers=student, json={
        "exam_code": "NEET_UG", "mode": "subject", "subject": "Physics",
    }).json()
    assert db_session.get(TestAttempt, attempt["attempt_id"]).submitted_at is None
    assert client.get(f"/api/practice/attempts/{attempt['attempt_id']}", headers=student).status_code == 409
