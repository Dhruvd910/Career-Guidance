import subprocess
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from app.session import session
from app.voice import IDLE, SPEAKING, Voice
from app.theme import FOREGROUND
from app.widgets.brand import Clock, Logo, StepProgress
from app.widgets.icons import maya_face_icon
from app.widgets.svg_icons import svg_icon
from app.widgets.keyboard import OnScreenKeyboard
from app.widgets.touch import enable_touch_scrolling, scroll_to_top
from app.pages.setup import SetupPage
from app.pages.greeting import GreetingPage
from app.pages.onboarding import OnboardingPage
from app.pages.dashboard import DashboardPage
from app.pages.exam import ExamPage
from app.pages.mock_tests import MockTestsPage
from app.pages.careers import CareersPage
from app.pages.colleges import CollegesPage
from app.pages.college_detail import CollegeDetailPage
from app.pages.college_find import CollegeFindPage, CollegeSourcesPage
from app.pages.shortlist import ShortlistPage
from app.pages.where_we_are import WhereWeArePage
from app.pages.compare import ComparePage
from app.pages.progress import ProgressPage
from app.pages.roadmap import RoadmapChangesPage, RoadmapNodePage, RoadmapPage
from app.pages.study_plan import StudyPlanPage
from app.pages.maya import MayaPage
from app.pages.memory import MemoryPage
from app.pages.practice import PracticeTestPage
from app.pages.calibrate import CalibrationPage
from app.pages.assessments import AssessmentsPage
from app.pages.assessment_result import AssessmentHistoryPage, AssessmentResultPage
from app.pages.assessment_runner import AssessmentRunnerPage
from app.pages.directions import DirectionPage, DirectionsPage
from app.pages.streams import StreamExplorerPage
from app.pages.career_detail import CareerDetailPage
from app.pages.guide import GuidePage
from app.pages.learn import LearnPage
from app import touch_calibration

PAGE_TITLES = {
    "setup": "Your details", "onboarding": "Getting started", "dashboard": "Dashboard",
    "maya": "MAYA Assistant", "jee": "JEE", "neet": "NEET", "mock_tests": "Mock Tests", "practice_test": "Practice test",
    "careers": "Careers", "colleges": "Colleges", "college_detail": "College", "college_find": "Find colleges",
    "college_sources": "Sources", "where_we_are": "Where we are", "shortlist": "My shortlist",
    "compare": "Compare colleges", "roadmap": "My roadmap", "calibrate": "Touch calibration",
    "roadmap_node": "Roadmap step", "roadmap_changes": "What changed", "progress": "My progress",
    "study_plan": "Study plan",
    "assessment": "My Tests", "assessment_run": "Test", "assessment_result": "My result",
    "assessment_history": "How I've changed", "directions": "Career directions", "direction": "Career direction", "streams": "Stream explorer",
    "career_detail": "Career guide", "memory": "MAYA's memory", "learn": "Learn", "guide": "How MAYA works",
}
# Screens that belong to starting up, not to using the app: no top bar, no
# wake word, and never somewhere Back returns to.
STARTUP_PAGES = ("", "greeting", "calibrate")
HISTORY_LIMIT = 30
# One-off requests to a page ("wake up and listen", "ask this", "a result just in") that coming
# Back to it must not repeat.
TRANSIENT = ("wake", "greet", "ask", "returning", "fresh")
# The wake word starts listening once MAYA has been quiet this long — not in the gap between
# her asking a question and listening for the answer.
WAKE_WORD_IDLE_MS = 1500
# Extra scrollable space below a page while the keyboard is up.
KEYBOARD_CLEARANCE = 60


class MainWindow(QMainWindow):
    def __init__(self, wake_word: bool = True):
        super().__init__()
        self.setWindowTitle("MAYA — AI Career Guide")
        # Never open larger than the display — this runs on small panels (the kiosk
        # touchscreen is 800x480) as well as regular monitors.
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1280, available.width()), min(820, available.height()))

        self.pages: dict[str, QWidget] = {}
        self._holders: dict[str, QScrollArea] = {}
        self._history: list[tuple[str, dict]] = []
        self._current_page = ""
        self._current_kwargs: dict = {}
        self._showing_depth = 0
        # The keyboard announces itself just *before* it shows (so the layout can make room),
        # so its own isVisible() is still False when that arrives — this is the truth instead.
        self._keyboard_shown = False

        # Created before any page: session.bootstrap() below navigates straight to the
        # greeting or setup page, and both start speaking immediately.
        self.voice = Voice()

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)

        self.header = self._build_header()
        outer.addWidget(self.header)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, stretch=1)

        self.keyboard = OnScreenKeyboard(self.voice)
        outer.addWidget(self.keyboard)
        # With the keyboard's 195px up on the 480px panel, the top bar steps aside while typing.
        self._compact_height = available.height() < 700
        self.keyboard.visibility_changed.connect(self._on_keyboard_visibility)

        self.wake_listener = self._start_wake_word() if wake_word else None

        self._register_pages()

        session.logged_in.connect(self._on_logged_in)
        session.needs_setup.connect(self._on_needs_setup)
        # A panel that has never been calibrated puts taps in the wrong place — including on
        # the setup screen's buttons — so that comes before anything else.
        if touch_calibration.needs_calibration():
            self._show("calibrate", {"first_run": True})
        else:
            self.start_session()

    def start_session(self) -> None:
        session.bootstrap()

    # ---------------- top bar ----------------
    #
    # One bar, four arrangements, as in the design:
    #   flow   (MAYA's questions)  Back · logo · progress
    #   home   (dashboard)         logo · "Welcome back, Dhruv!" · date/time · settings
    #   inner  (everything else)   Back · logo · page title · MAYA's wake button
    # and the two-tap Exit on the right of all of them.

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("Header")
        header.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 8, 12, 4)
        row.setSpacing(10)

        self.back_btn = QPushButton("  Back")
        self.back_btn.setObjectName("BackButton")
        self.back_btn.setIcon(svg_icon("arrow-left", FOREGROUND, 16))
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.go_back)
        row.addWidget(self.back_btn)

        # Home, one tap from anywhere — the logo does it too, but nobody guesses that.
        self.home_btn = QPushButton()
        self.home_btn.setObjectName("IconButton")
        self.home_btn.setIcon(svg_icon("home", FOREGROUND, 22))
        self.home_btn.setIconSize(QSize(22, 22))
        self.home_btn.setToolTip("Home")
        self.home_btn.setCursor(Qt.PointingHandCursor)
        self.home_btn.clicked.connect(self._go_home)
        row.addWidget(self.home_btn)

        self.logo = Logo(34)
        self.logo.clicked.connect(self._go_home)
        self._lead_stretch = QWidget()  # centres the logo in flow mode
        self._lead_stretch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self._lead_stretch)
        row.addWidget(self.logo)

        self.title_label = QLabel("")
        self.title_label.setObjectName("HeaderTitle")
        row.addWidget(self.title_label, stretch=1)

        self.welcome_label = QLabel("")
        self.welcome_label.setObjectName("HeaderWelcome")
        self.welcome_label.setAlignment(Qt.AlignCenter)
        row.addWidget(self.welcome_label, stretch=1)

        self._trail_stretch = QWidget()
        self._trail_stretch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self._trail_stretch)

        self.progress = StepProgress()
        row.addWidget(self.progress)
        self.step_pill = QLabel("")
        self.step_pill.setObjectName("StepPill")
        row.addWidget(self.step_pill)

        self.wake_hint = QLabel('Say "Hey Maya"')
        self.wake_hint.setObjectName("WakeHint")
        self.wake_hint.setVisible(False)
        row.addWidget(self.wake_hint)

        # MAYA's face is the wake button: tap it (or say her name) and she listens.
        self.wake_btn = QPushButton("  MAYA")
        self.wake_btn.setObjectName("WakeButton")
        self.wake_btn.setIcon(maya_face_icon(30))
        self.wake_btn.setIconSize(QSize(30, 30))
        self.wake_btn.setCursor(Qt.PointingHandCursor)
        self.wake_btn.clicked.connect(self.wake_maya)
        row.addWidget(self.wake_btn)

        self.clock = Clock()
        row.addWidget(self.clock)

        self.help_btn = QPushButton()
        self.help_btn.setObjectName("IconButton")
        self.help_btn.setIcon(svg_icon("help", FOREGROUND, 26, 1.8))
        self.help_btn.setIconSize(QSize(26, 26))
        self.help_btn.setToolTip("How MAYA works")
        self.help_btn.setCursor(Qt.PointingHandCursor)
        self.help_btn.clicked.connect(lambda: self.navigate("guide"))
        row.addWidget(self.help_btn)

        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("IconButton")
        self.settings_btn.setIcon(svg_icon("settings", FOREGROUND, 26, 1.8))
        self.settings_btn.setIconSize(QSize(26, 26))
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._open_settings)
        row.addWidget(self.settings_btn)

        self._exit_armed = False
        self.exit_btn = QPushButton()
        self.exit_btn.setCursor(Qt.PointingHandCursor)
        self.exit_btn.clicked.connect(self._exit_tapped)
        self._disarm_exit()
        row.addWidget(self.exit_btn)

        header.setVisible(False)
        return header

    def _header_mode(self) -> str:
        if self._current_page in ("setup", "onboarding"):
            return "flow"
        if self._current_page == "dashboard":
            return "home"
        return "inner"

    def _arrange_header(self) -> None:
        mode = self._header_mode()
        flow, home, inner = mode == "flow", mode == "home", mode == "inner"
        self.back_btn.setVisible(not home)
        self.home_btn.setVisible(inner and bool((session.profile or {}).get("onboarding_completed")))
        self.help_btn.setVisible(home)
        self._lead_stretch.setVisible(flow)
        self.title_label.setVisible(inner)
        self.welcome_label.setVisible(home)
        self._trail_stretch.setVisible(flow)
        self.progress.setVisible(flow and self._progress_kind == "bar")
        self.step_pill.setVisible(flow and self._progress_kind == "pill")
        self.wake_btn.setVisible(inner)
        self.wake_hint.setVisible(inner and self._wake_word_available)
        self.clock.setVisible(home)
        self.settings_btn.setVisible(home)
        self.title_label.setText(PAGE_TITLES.get(self._current_page, ""))
        first = (session.profile or {}).get("name", "").split(" ")[0]
        self.welcome_label.setText(f"Welcome back, <b>{first}!</b>" if first else "Welcome back!")

    _progress_kind = "bar"
    _wake_word_available = False

    def set_progress(self, text: str, filled: int, total: int) -> None:
        """For MAYA's question screens: "1/6" (or "Almost done") over the segment bar."""
        self._progress_kind = "bar"
        self.progress.set_progress(text, filled, total)
        self._arrange_header()

    def set_step_pill(self, text: str) -> None:
        """For a question that needs a note instead of a count ("Choose 1 or more")."""
        self._progress_kind = "pill"
        self.step_pill.setText(text)
        self._arrange_header()

    def _go_home(self) -> None:
        """Home is where every journey starts: going there starts Back's history afresh."""
        if self._home_available():
            self._history.clear()
            self._show("dashboard", {})

    def _open_settings(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: white; border: 1px solid #dde6f3; border-radius: 10px; padding: 6px; }"
            "QMenu::item { padding: 10px 22px; font-size: 14px; border-radius: 8px; }"
            "QMenu::item:selected { background: #e8f0fe; color: #0f1f3d; }")
        # Settings only: every part of MAYA itself is a tile on the home screen.
        menu.addAction("Edit my details", lambda: self.navigate("setup", edit=True))
        menu.addAction("Change my goal", self.pages["dashboard"].change_goal)
        menu.addAction("What MAYA remembers (privacy)", lambda: self.navigate("memory"))
        menu.addAction("How MAYA works", lambda: self.navigate("guide"))
        menu.addAction("Calibrate touch", lambda: self.navigate("calibrate"))
        below = self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomRight())
        menu.exec(below - QPoint(menu.sizeHint().width(), 0))

    # Two taps, so a stray touch on the panel can't shut her down.
    EXIT_CONFIRM_MS = 4000

    def _exit_tapped(self) -> None:
        """Full screen covers the desktop and its Stop icon, so the way out has to be in here."""
        if not self._exit_armed:
            self._exit_armed = True
            self.exit_btn.setText("Tap again")
            self.exit_btn.setIcon(QIcon())
            self.exit_btn.setStyleSheet(
                "QPushButton { background:#dc2626; color:white; font-weight:700; border:none;"
                " border-radius:17px; padding:0 14px; min-height:34px; }")
            QTimer.singleShot(self.EXIT_CONFIRM_MS, self._disarm_exit)
            return
        self._close_maya()

    def _disarm_exit(self) -> None:
        self._exit_armed = False
        self.exit_btn.setText("")
        self.exit_btn.setIcon(svg_icon("x", "#ffffff", 16, 2.6))
        self.exit_btn.setStyleSheet(
            "QPushButton { background:#1e293b; border:none; border-radius:17px; padding:0;"
            " min-width:34px; max-width:34px; min-height:34px; }")

    def _close_maya(self) -> None:
        """Stops the backend too when started by start.sh (stop.sh finds it by pidfile)."""
        stop_script = Path(__file__).resolve().parents[3] / "stop.sh"
        if stop_script.exists():
            subprocess.Popen([str(stop_script)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        QApplication.quit()

    # ---------------- page registry ----------------

    def _register_pages(self) -> None:
        self.pages["setup"] = SetupPage(self)
        self.pages["greeting"] = GreetingPage(self)
        self.pages["onboarding"] = OnboardingPage(self)
        self.pages["dashboard"] = DashboardPage(self)
        self.pages["jee"] = ExamPage(self, exam_codes=["JEE_MAIN", "JEE_ADVANCED"], title="JEE Guidance & Prediction")
        self.pages["neet"] = ExamPage(self, exam_codes=["NEET_UG"], title="NEET-UG Guidance & Prediction")
        self.pages["mock_tests"] = MockTestsPage(self)
        self.pages["careers"] = CareersPage(self)
        self.pages["colleges"] = CollegesPage(self)
        self.pages["college_detail"] = CollegeDetailPage(self)
        self.pages["college_find"] = CollegeFindPage(self)
        self.pages["where_we_are"] = WhereWeArePage(self)
        self.pages["shortlist"] = ShortlistPage(self)
        self.pages["college_sources"] = CollegeSourcesPage(self)
        self.pages["compare"] = ComparePage(self)
        self.pages["roadmap"] = RoadmapPage(self)
        self.pages["roadmap_node"] = RoadmapNodePage(self)
        self.pages["roadmap_changes"] = RoadmapChangesPage(self)
        self.pages["progress"] = ProgressPage(self)
        self.pages["study_plan"] = StudyPlanPage(self)
        self.pages["maya"] = MayaPage(self)
        self.pages["practice_test"] = PracticeTestPage(self)
        self.pages["calibrate"] = CalibrationPage(self)
        self.pages["assessment"] = AssessmentsPage(self)
        self.pages["assessment_run"] = AssessmentRunnerPage(self)
        self.pages["assessment_result"] = AssessmentResultPage(self)
        self.pages["assessment_history"] = AssessmentHistoryPage(self)
        self.pages["directions"] = DirectionsPage(self)
        self.pages["direction"] = DirectionPage(self)
        self.pages["streams"] = StreamExplorerPage(self)
        self.pages["career_detail"] = CareerDetailPage(self)
        self.pages["memory"] = MemoryPage(self)
        self.pages["learn"] = LearnPage(self)
        self.pages["guide"] = GuidePage(self)
        for name, page in self.pages.items():
            # Every page scrolls. When the keyboard takes the bottom ~195px of the 480px panel,
            # a page taller than what's left scrolls instead of forcing the window taller than
            # the screen (which pushed the keyboard's bottom rows off the display).
            holder = QScrollArea()
            holder.setWidgetResizable(True)
            holder.setFrameShape(QScrollArea.NoFrame)
            holder.setWidget(page)
            self._holders[name] = holder
            self.stack.addWidget(holder)
        # Drag anywhere to scroll: the panel has no wheel, and a 12px scrollbar is a hard
        # target for a finger.
        enable_touch_scrolling(self)

    # ---------------- navigation ----------------

    @staticmethod
    def _entry(name: str, kwargs: dict) -> tuple[str, dict]:
        return name, {k: v for k, v in kwargs.items() if k not in TRANSIENT}

    def navigate(self, name: str, **kwargs) -> None:
        # A page that redirects from its own on_show() (dashboard -> onboarding) replaces
        # the screen being opened rather than stacking another entry onto the history.
        redirect = self._showing_depth > 0
        here = self._entry(self._current_page, self._current_kwargs)
        # One career to a related one, one college to another: the same page with something else
        # in it is a new screen too — Back returns to the one before.
        if not redirect and self._current_page not in STARTUP_PAGES and here != self._entry(name, kwargs):
            self._history.append(here)
            del self._history[:-HISTORY_LIMIT]
        self._show(name, kwargs)

    def _show(self, name: str, kwargs: dict) -> None:
        page = self.pages[name]
        # Leaving a page ends whatever MAYA was saying or listening for there — she
        # shouldn't keep asking the previous screen's question over the next one.
        self.keyboard.hide_keyboard()
        self._keyboard_shown = self.keyboard.isVisible()
        self.voice.cancel()
        self._current_page = name
        self._current_kwargs = kwargs
        self.stack.setCurrentWidget(self._holders[name])
        scroll_to_top(self._holders[name])
        enable_touch_scrolling(page)  # pages that build lists later get them registered too
        self._showing_depth += 1
        try:
            page.on_show(**kwargs)
        finally:
            self._showing_depth -= 1
        self._sync_chrome()  # after on_show: whether setup shows the header depends on its edit flag
        self.refresh_back_button()
        self._schedule_wake_word()

    def go_back(self) -> None:
        page = self.pages.get(self._current_page)
        if page is None:
            return
        mode = page.back_mode()
        if mode == "page":
            page.go_back()
        elif mode == "history":
            here = self._entry(self._current_page, self._current_kwargs)
            while self._history:
                name, kwargs = self._history.pop()
                if (name, kwargs) != here:
                    # Pages keep what they were showing when you come back to them.
                    self._show(name, {**kwargs, "returning": True})
                    return
            if self._home_available():
                self._show("dashboard", {})
        self.refresh_back_button()

    def clear_history(self) -> None:
        self._history.clear()
        self.refresh_back_button()

    def _home_available(self) -> bool:
        return self._current_page != "dashboard" and bool((session.profile or {}).get("onboarding_completed"))

    def refresh_back_button(self) -> None:
        page = self.pages.get(self._current_page)
        if page is None:
            self.back_btn.setEnabled(False)
            return
        mode = page.back_mode()
        self.back_btn.setEnabled(mode == "page" or (mode == "history" and (bool(self._history) or self._home_available())))

    def _sync_chrome(self, keyboard_shown: bool | None = None) -> None:
        if keyboard_shown is None:
            keyboard_shown = self.keyboard.isVisible()
        typing_on_small_screen = self._compact_height and keyboard_shown
        in_app = self._current_page not in STARTUP_PAGES
        # A paper in progress gets the whole screen, the way an exam hall has no posters.
        taking_test = self._current_page == "practice_test" and self.pages["practice_test"].attempt is not None
        self.header.setVisible(in_app and not typing_on_small_screen and not taking_test)
        self._arrange_header()

    def refresh_chrome(self) -> None:
        """For a page whose own state decides what belongs around it (a test in progress)."""
        self._sync_chrome()
        self.refresh_back_button()

    def _on_keyboard_visibility(self, shown: bool) -> None:
        self._keyboard_shown = shown
        # Room to scroll past the end of a page, so the last box on it can still sit above
        # the keyboard instead of hard against its top edge.
        for holder in self._holders.values():
            holder.setViewportMargins(0, 0, 0, KEYBOARD_CLEARANCE if shown else 0)
        self._sync_chrome(keyboard_shown=shown)
        self._schedule_wake_word()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_to_screen)

    def _fit_to_screen(self) -> None:
        """Qt grows a window to satisfy its layout but never shrinks it back afterwards, so if
        anything pushes it past the display, pull it back inside — as long as the layout can
        actually fit, or this would fight Qt's minimum-size enforcement forever."""
        if self.isFullScreen():
            return
        available = self.screen().availableGeometry()
        too_big = self.width() > available.width() or self.height() > available.height()
        needed = self.minimumSizeHint()
        if too_big and needed.width() <= available.width() and needed.height() <= available.height():
            self.resize(min(self.width(), available.width()), min(self.height(), available.height()))

    def enter_kiosk_mode(self) -> None:
        """Full screen on the kiosk. The X session there runs no window manager, so
        showFullScreen()'s _NET_WM_STATE_FULLSCREEN hint has nobody to honor it: the geometry
        is set explicitly, and fixed, so nothing a page does can grow the window past the
        panel and push the keyboard's bottom rows off screen."""
        geometry = self.screen().geometry()
        self.setGeometry(geometry)
        self.setFixedSize(geometry.size())
        self.showFullScreen()

    # ---------------- waking MAYA ----------------

    def wake_maya(self, greet: bool = True) -> None:
        """MAYA's wake button, and what hearing "Hey Maya" does: open her page and listen."""
        if self._current_page in STARTUP_PAGES or (self._current_page == "setup" and not self.pages["setup"].editing):
            return
        if self._current_page == "maya":
            self.keyboard.hide_keyboard()
            self.pages["maya"].wake(greet=greet)
        else:
            self.navigate("maya", wake=True, greet=greet)

    def _start_wake_word(self):
        try:
            from app.wake_word import WakeWordListener
        except Exception:  # noqa: BLE001 — no vosk or no audio stack: tap-to-wake still works
            return None
        listener = WakeWordListener()
        listener.detected.connect(self._on_wake_word)
        listener.available_changed.connect(self._on_wake_word_available)
        self._wake_timer = QTimer(self)
        self._wake_timer.setSingleShot(True)
        self._wake_timer.setInterval(WAKE_WORD_IDLE_MS)
        self._wake_timer.timeout.connect(self._sync_wake_word)
        # Pause the moment MAYA starts doing anything — above all speaking, or she'd hear her
        # own name and wake herself up.
        self.voice.state_changed.connect(lambda _state: self._schedule_wake_word())
        return listener

    def _wake_word_wanted(self) -> bool:
        if self._current_page in STARTUP_PAGES or self._keyboard_shown:
            return False
        if self.voice.speaking:
            # While she talks, "Hey Maya" / "Stop Maya" interrupts her — on any screen,
            # first-run setup included, where it means "stop reading, I'll answer now". In a
            # streamed reply she already hears anyone talking over her, name or not.
            return not (self.voice.listens_while_speaking and self.voice.state == SPEAKING
                        and self._current_page == "maya")
        return self.voice.state == IDLE and self._current_page != "setup"

    def _interruptible_now(self) -> bool:
        return self.voice.speaking

    def _schedule_wake_word(self) -> None:
        if self.wake_listener is None:
            return
        if self._wake_word_wanted() and self._interruptible_now():
            self._wake_timer.stop()
            self.wake_listener.resume()  # straight away: an interruption can't wait 1.5s
        elif self._wake_word_wanted():
            self._wake_timer.start()
        else:
            self._wake_timer.stop()
            self.wake_listener.pause()

    def _sync_wake_word(self) -> None:
        if self._wake_word_wanted():
            self.wake_listener.resume()
        else:
            self.wake_listener.pause()

    def _on_wake_word_available(self, available: bool) -> None:
        self._wake_word_available = available
        self._arrange_header()
        self._schedule_wake_word()

    def _on_wake_word(self) -> None:
        self.wake_listener.pause()
        if not self._wake_word_wanted():
            return
        if self.voice.speaking:
            from app.wake_word import is_wake_phrase

            spoken = "".join(c if c.isalnum() or c.isspace() else " " for c in self.voice.current_text.lower())
            if is_wake_phrase(spoken.split()):
                return  # the mic heard her own "…Hey Maya…" through the speaker
            # Interrupted mid-sentence. A question she was asking goes straight to listening
            # for the answer; anything else (a chat reply, a read-aloud) stops, and she listens.
            if self.voice.interrupt():
                return
            self.wake_maya(greet=False)  # they're already talking: no "Yes?", just listen
            return
        self.wake_maya()

    # ---------------- session events ----------------

    def _on_logged_in(self, profile: dict) -> None:
        next_target = "onboarding" if not profile.get("onboarding_completed") else "dashboard"
        self.clear_history()
        self._show("greeting", {"next_target": next_target})

    def _on_needs_setup(self) -> None:
        self.clear_history()
        self._show("setup", {})
