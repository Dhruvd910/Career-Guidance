"""Sitting a practice paper, without a backend: what answering, clearing and the clock do."""

import pytest

from app.pages.practice import PracticeTestPage, _clock
from app.voice import Voice


class FakeWindow:
    def __init__(self):
        self.voice = Voice()
        self.navigated = []

    def navigate(self, name, **kwargs):
        self.navigated.append((name, kwargs))

    def refresh_chrome(self):
        pass

    def refresh_back_button(self):
        pass


def make_attempt(count=3, subject="Physics"):
    return {
        "attempt_id": 7,
        "exam_code": "NEET_UG",
        "mode": "subject",
        "subject": subject,
        "duration_seconds": 300,
        "correct_marks": 4.0,
        "wrong_marks": -1.0,
        "questions": [
            {"id": 100 + i, "subject": subject, "topic": "Topic", "difficulty": "easy",
             "stem": f"Question {i}?", "options": ["one", "two", "three", "four"]}
            for i in range(count)
        ],
    }


@pytest.fixture()
def page(qapp):
    page = PracticeTestPage(FakeWindow())
    page.on_show(attempt=make_attempt())
    return page


def test_clock_formats_minutes_and_seconds():
    assert _clock(0) == "00:00"
    assert _clock(59) == "00:59"
    assert _clock(605) == "10:05"
    assert _clock(-5) == "00:00", "a clock that has run out reads zero, not a negative time"


def test_answering_records_the_choice_and_moves_on(page):
    page._choose(2)
    assert page.answers == {100: 2}
    assert page.index == 1, "the next question comes up by itself"


def test_the_last_question_stays_put_so_submit_is_within_reach(page):
    page._go_to(2)
    page._choose(1)
    assert page.index == 2
    assert page.answers == {102: 1}


def test_changing_an_answer_replaces_it(page):
    page._choose(0)
    page._go_to(0)
    page._choose(3)
    assert page.answers == {100: 3}


def test_clearing_leaves_the_question_unanswered(page):
    page._choose(1)
    page._go_to(0)
    page._clear_answer()
    assert page.answers == {}
    assert not page.clear_btn.isEnabled()


def test_the_palette_tracks_which_questions_are_answered(page):
    page._choose(0)  # question 1, then moves to question 2
    states = [btn.property("state") for btn in page.palette_buttons]
    assert states == ["answered", "current", "blank"]


def test_jumping_from_the_palette_closes_it(page):
    # isHidden() rather than isVisible(): the page has no window of its own in a test.
    page._toggle_palette()
    assert not page.palette.isHidden()
    page._jump(2)
    assert page.index == 2 and page.palette.isHidden()


def test_running_out_of_time_submits_the_paper(page, monkeypatch):
    submitted = []
    monkeypatch.setattr(page, "_submit", lambda: submitted.append(True))
    page._started_at -= 301  # 300-second paper, 301 seconds ago
    page._tick()
    assert submitted == [True]
    assert page.timer_label.text().endswith("00:00")


def test_the_clock_warns_near_the_end(page):
    page._started_at -= 200  # 100 seconds left on a 300-second paper
    page._tick()
    assert page.timer_label.property("warning") == "true"


def test_leaving_needs_the_test_to_be_in_progress(page):
    assert page.back_mode() == "page", "Back asks before abandoning a paper"
    page.attempt = None
    assert page.back_mode() == "history"


def test_the_weakest_subject_is_the_lowest_share_not_the_lowest_score():
    summary = {"subject_scores": [
        {"subject": "Physics", "score": 20.0, "max_score": 40.0, "correct": 5, "wrong": 0, "unanswered": 5},
        {"subject": "Biology", "score": 30.0, "max_score": 80.0, "correct": 8, "wrong": 2, "unanswered": 10},
    ]}
    assert PracticeTestPage._weakest_subject(summary) == "Biology"


def test_no_weakest_subject_for_a_single_subject_test():
    summary = {"subject_scores": [
        {"subject": "Physics", "score": 20.0, "max_score": 40.0, "correct": 5, "wrong": 0, "unanswered": 5},
    ]}
    assert PracticeTestPage._weakest_subject(summary) is None


def test_the_result_shows_the_score_and_every_review(page, qapp):
    page._show_result({
        "attempt_id": 7, "title": "NEET_UG Physics practice test", "score": 11.0, "max_score": 40.0,
        "correct": 3, "wrong": 1, "unanswered": 6, "accuracy": 30.0, "seconds_taken": 120,
        "duration_seconds": 300, "subject_scores": [], "review": [
            {"position": 0, "question_id": 100, "subject": "Physics", "topic": "t", "stem": "Question 0?",
             "options": ["one", "two", "three", "four"], "correct_index": 1, "selected_index": 1,
             "is_correct": True, "explanation": "Because two."},
            {"position": 1, "question_id": 101, "subject": "Physics", "topic": "t", "stem": "Question 1?",
             "options": ["one", "two", "three", "four"], "correct_index": 0, "selected_index": None,
             "is_correct": None, "explanation": "Because one."},
        ],
    })
    from PySide6.QtWidgets import QLabel

    text = " ".join(label.text() for label in page.result_view.findChildren(QLabel))
    assert "11 / 40" in text
    assert "3 correct" in text and "1 wrong" in text and "6 unanswered" in text
    assert "Because two." in text and "Because one." in text
    assert "left this blank" in text, "an unanswered question says so rather than looking wrong"
    assert page.attempt is None, "the paper is over"
