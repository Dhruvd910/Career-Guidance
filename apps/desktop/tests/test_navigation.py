"""Getting around: Back is always the screen you came from (never the first-run details form), Home is
one tap away and starts afresh, the home screen shows every part of MAYA, and the guide and Learn
screens lead where they say."""

from PySide6.QtWidgets import QPushButton

from app.main_window import MainWindow
from app.pages.dashboard import DashboardPage
from app.pages.guide import PARTS, GuidePage
from app.pages.learn import LearnPage
from app.pages.onboarding import OnboardingPage
from app.voice import Voice


class Page:
    def __init__(self, mode="history"):
        self.mode = mode

    def back_mode(self):
        return self.mode


class Window:
    """MainWindow's own navigation code, around a stand-in for the screens."""

    navigate = MainWindow.navigate
    go_back = MainWindow.go_back
    _go_home = MainWindow._go_home
    _entry = MainWindow.__dict__["_entry"]

    def __init__(self):
        self.pages = {name: Page() for name in ("dashboard", "careers", "direction", "learn", "onboarding", "setup")}
        self._history, self._current_page, self._current_kwargs, self._showing_depth = [], "dashboard", {}, 0
        self.shown = []

    def _show(self, name, kwargs):
        self._current_page, self._current_kwargs = name, kwargs
        self.shown.append((name, kwargs))

    def _home_available(self):
        return self._current_page != "dashboard"

    def refresh_back_button(self):
        pass


def test_back_returns_to_the_previous_item_of_the_same_screen():
    """Software engineering → a related career → Back used to skip straight past software engineering."""
    w = Window()
    w.navigate("careers")
    w.navigate("direction", key="cse")
    w.navigate("direction", key="ai_data")
    w.go_back()
    assert (w._current_page, w._current_kwargs["key"]) == ("direction", "cse")
    w.go_back()
    assert w._current_page == "careers"
    w.go_back()
    assert w._current_page == "dashboard"


def test_one_off_requests_are_not_replayed_on_the_way_back():
    w = Window()
    w.navigate("learn", career="cse", ask="Python kahan se seekhu?", fresh=True)
    w.navigate("careers")
    w.go_back()
    assert w._current_kwargs == {"career": "cse", "returning": True}


def test_home_is_one_tap_and_starts_afresh():
    w = Window()
    w.navigate("careers")
    w.navigate("direction", key="cse")
    w._go_home()
    assert w._current_page == "dashboard" and w._history == []
    w.navigate("learn")
    w.go_back()
    assert w._current_page == "dashboard", "not back into the screens before Home"


def test_back_on_onboarding_is_the_previous_screen_not_the_details_form(qapp):
    """It used to open "Your details" (name, class, category) from the first onboarding question."""
    page = OnboardingPage(type("Ctx", (), {"voice": Voice(), "navigate": lambda *a, **k: None})())
    for step in ("memory_permission", "career_exploration_assessment", "stream_assessment", "career_goal_question"):
        page._step = {"step": step}
        assert page.back_mode() == "history", step
    page._step = {"step": "exam_selection"}
    assert page.back_mode() == "page", "after 'do you know your career?', Back un-answers it"


class Ctx:
    def __init__(self):
        self.voice = Voice()
        self.went = []

    def navigate(self, name, **kwargs):
        self.went.append((name, kwargs))


def test_the_home_screen_shows_every_part_of_maya(qapp, monkeypatch):
    monkeypatch.setattr("app.pages.dashboard.session", type("S", (), {"profile": {"target_exam_code": "NEET_UG"}})())
    ctx = Ctx()
    page = DashboardPage(ctx)
    assert list(page.tiles) == ["assessment", "careers", "roadmap", "learn", "colleges", "exams", "mock_tests", "progress"]
    page.tiles["learn"].clicked.emit()
    page.tiles["exams"].clicked.emit()
    assert ctx.went == [("learn", {}), ("neet", {})], "Exams opens the student's own exam"


def test_the_guide_opens_each_part(qapp, monkeypatch):
    monkeypatch.setattr("app.pages.guide.session", type("S", (), {"profile": {}})())
    ctx = Ctx()
    page = GuidePage(ctx)
    opens = [b for b in page.findChildren(QPushButton) if b.text().startswith("Open")]
    assert len(opens) == len(PARTS)
    for button in opens:
        button.click()
    assert [name for name, _ in ctx.went] == ["assessment", "careers", "roadmap", "learn", "colleges", "jee", "mock_tests",
                                             "progress"]


PLAN = {
    "career": {"key": "ai_data", "name": {"en": "Data Science & AI", "hi": "डेटा साइंस"}}, "why": "focus",
    "careers": [{"key": "ai_data", "name": {"en": "Data Science & AI", "hi": "डेटा साइंस"}}],
    "steps": [{"skill": "skill:python", "name": {"en": "Python", "hi": "पाइथन"}, "status": "not_measured", "says": None,
               "try": [], "videos": [
                   {"lang": "hi", "title": "Python in Hindi | Class 9 & 10", "channel": "CodeWithHarry", "length": "10:00", "url": "https://youtu.be/hi"},
                   {"lang": "en", "title": "🔥Python Full Course 🛣️", "channel": "Programming with Mosh", "length": "6:00:00",
                    "url": "https://youtu.be/en"}],
               "search": {"en": "https://www.youtube.com/results?search_query=python", "hi": "https://x/hi"}}],
}


def test_learn_shows_each_topic_with_its_videos_in_the_students_language_first(qapp):
    ctx = Ctx()
    page = LearnPage(ctx)
    page._render(PLAN)
    texts = [b.text() for b in page.findChildren(QPushButton)]
    videos = [t for t in texts if t.startswith("▶")]
    assert videos[0].startswith("▶  English:  Python Full Course") and videos[1].startswith("▶  हिंदी:")
    assert videos[0].split("\n")[0] == "▶  English:  Python Full Course", "no emoji: the Pi draws them as boxes"
    assert "Class 9 && 10" in videos[1], "an & shows as written (Qt would take it for a shortcut marker)"
    assert any(t.startswith("More videos on this topic") for t in texts)
    assert "Data Science & AI" in page.career_label.text() and "your roadmap focus" in page.career_label.text()


def test_learn_without_a_career_points_to_the_tests(qapp):
    ctx = Ctx()
    page = LearnPage(ctx)
    page._render({**PLAN, "career": None, "why": "none", "steps": []})
    tests = next(b for b in page.findChildren(QPushButton) if b.text() == "Open My Tests")
    tests.click()
    assert ctx.went == [("assessment", {})]
