"""The setup questions' logic: which questions get asked, what each answer does, and what
finally gets saved. The page is never shown here, so MAYA stays silent (_ask() does nothing
for a hidden page) and no network calls happen."""

import pytest

from app.pages.setup import CATEGORY, CLASS, COLLEGE_YEAR, DOMICILE, DOMICILE_SAME, NAME, REVIEW, SKIPPED, SetupPage
from app.voice_parsing import COLLEGE
from app.voice import Voice


class FakeWindow:
    """Stands in for MainWindow — the page only ever calls these."""

    def __init__(self):
        self.voice = Voice()
        self.navigated: list[tuple] = []
        self.back_refreshes = 0
        self.progress: tuple | None = None

    def navigate(self, name, **kwargs):
        self.navigated.append((name, kwargs))

    def clear_history(self):
        pass

    def refresh_back_button(self):
        self.back_refreshes += 1

    def go_back(self):
        pass

    def set_progress(self, text, filled, total):
        self.progress = (text, filled, total)


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr("app.pages.setup.session", type("S", (), {"profile": None})())
    return SetupPage(FakeWindow())


def answer_all(page, class_level=12):
    page.answers = {"name": "Riya", "class_level": class_level, "school_board": "CBSE", "state": "Karnataka"}
    if class_level >= 11:
        page.answers |= {"domicile_same": True, "category": "OBC"}
    return page


def test_class_8_is_not_asked_about_domicile_or_category(page):
    page.answers = {"class_level": 9}
    assert page._steps() == [NAME, CLASS, "board", "state", REVIEW]


def test_class_11_is_asked_about_domicile_and_category(page):
    page.answers = {"class_level": 11}
    assert page._steps() == [NAME, CLASS, "board", "state", DOMICILE_SAME, CATEGORY, REVIEW]


def test_a_different_domicile_adds_a_question(page):
    page.answers = {"class_level": 12, "domicile_same": False}
    assert DOMICILE in page._steps()


def test_name_and_class_in_one_answer_skips_the_class_question(page):
    page._show_step(NAME)
    assert page._heard_name("I'm Riya and I'm in class 12")
    assert page.answers["name"] == "Riya" and page.answers["class_level"] == 12
    assert page._step == "board"  # the class question was already answered


def test_naming_another_state_answers_the_domicile_question(page):
    answer_all(page)
    del page.answers["domicile_same"], page.answers["category"]
    page._show_step(DOMICILE_SAME)
    assert page._heard_domicile_same("No, it's Maharashtra")
    assert page.answers["domicile_same"] is False
    assert page.answers["domicile_state"] == "Maharashtra"
    assert page._step == CATEGORY  # the domicile state is known, so that question is skipped


def test_unrecognized_answer_is_not_accepted(page):
    answer_all(page)
    del page.answers["domicile_same"]
    page._show_step(DOMICILE_SAME)
    assert not page._heard_domicile_same("I've no idea what that means")
    assert "domicile_same" not in page.answers


def test_back_steps_through_the_questions(page):
    answer_all(page)
    page._show_step(CATEGORY)
    assert page.back_mode() == "page"
    page.go_back()
    assert page._step == DOMICILE_SAME


def test_first_question_of_a_first_run_has_nowhere_to_go_back_to(page):
    page.editing = False
    page._show_step(NAME)
    assert page.back_mode() == "blocked"


def test_junior_details_use_the_home_state_and_no_category(page):
    answer_all(page, class_level=9)
    page.answers["category"] = "General"  # answered earlier, before the class was changed
    assert page._details() == {
        "name": "Riya", "class_level": 9, "education_stage": "class_9", "school_board": "CBSE",
        "state": "Karnataka", "domicile_state": "Karnataka", "category": None,
    }


def test_a_different_domicile_state_is_saved(page):
    answer_all(page)
    page.answers |= {"domicile_same": False, "domicile_state": "Maharashtra"}
    assert page._details()["domicile_state"] == "Maharashtra"


def test_a_skipped_category_saves_nothing(page):
    answer_all(page)
    page.answers["category"] = SKIPPED
    assert page._details()["category"] is None


def test_submitting_with_a_missing_answer_asks_that_question_instead(page):
    answer_all(page)
    del page.answers["school_board"]
    page._show_step(REVIEW)
    page._submit()
    assert page._step == "board"


def test_top_bar_counts_the_questions_then_says_almost_done(page):
    page.on_show()
    assert page.ctx.progress == ("1/4", 1, 5)  # name, class, board, state — and the review
    page.answers.update(name="Asha", class_level=9, school_board="CBSE", state="Delhi")
    page._show_step("review")
    assert page.ctx.progress == ("Almost done", 4, 5)


def test_class_6_and_7_can_set_up(page):
    page._show_step(CLASS)
    assert page._heard_class("main saatvi mein hoon")
    assert page.answers["class_level"] == 7 and page._steps() == [NAME, CLASS, "board", "state", REVIEW]
    page._pick(CLASS, 6)
    assert page.answers["class_level"] == 6


def test_a_college_student_is_asked_their_year_instead_of_the_school_board(page):
    page.answers = {"name": "Arjun"}
    page._show_step(CLASS)
    assert page._heard_class("I'm doing B.Tech")
    assert page.answers["class_level"] == COLLEGE
    assert page._steps() == [NAME, CLASS, COLLEGE_YEAR, "state", REVIEW], "no board, no domicile or category"
    assert page._step == COLLEGE_YEAR
    assert page._heard_college_year("third year")
    page.answers |= {"state": "Bihar"}
    assert page._details() == {"name": "Arjun", "class_level": 12, "education_stage": "ug_y3",
                               "state": "Bihar", "domicile_state": "Bihar", "category": None}
    assert page._display_value(COLLEGE_YEAR) == "3rd year" and page._display_value(CLASS) == "College"
    assert "at college, 3rd year" in page._spoken_review()


def test_class_and_year_in_one_answer(page):
    page.answers = {"name": "Arjun"}
    page._show_step(CLASS)
    assert page._heard_class("second year BSc")
    assert page.answers["education_stage"] == "ug_y2" and page._step == "state"


def test_editing_a_college_students_details_starts_from_their_stage(page, monkeypatch):
    monkeypatch.setattr("app.pages.setup.session", type("S", (), {"profile": {
        "name": "Arjun", "class_level": 12, "education_stage": "ug_y2", "state": "Bihar", "domicile_state": "Bihar",
        "school_board": None}})())
    answers = page._answers_from_profile()
    assert answers["class_level"] == COLLEGE and answers["education_stage"] == "ug_y2"
