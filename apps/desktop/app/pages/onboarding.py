from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout

from app.api_client import ApiError, api_client
from app.pages.base import BasePage
from app.session import session
from app.voice_parsing import parse_exam_choice, parse_yes_no
from app.config import PORTRAIT_RATIO
from app.widgets.common import Card, arrow_button, clear_layout, error_label, muted, set_error
from app.widgets.maya_status import MayaStatus
from app.widgets.svg_icons import svg_icon
from app.workers import run_async

# Steps that come after answering "do you know what you want to do?" — Back from these
# un-answers it, so the question gets asked again.
AFTER_CAREER_GOAL = ("exam_selection", "career_counselling_assessment")
MASCOT_HEIGHT = 280


class OnboardingPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        # Same shape as MAYA's setup questions: MAYA on the left, the question card on the
        # right, Next (when a step needs one) under it.
        grid = QGridLayout(self)
        grid.setContentsMargins(16, 6, 20, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)

        self.status = MayaStatus(ctx.voice, QSize(int(MASCOT_HEIGHT * PORTRAIT_RATIO), MASCOT_HEIGHT),
                                 show_text=False, portrait=True)
        grid.addWidget(self.status, 0, 0, 2, 1, alignment=Qt.AlignCenter)

        card = Card()
        card.layout_.setContentsMargins(22, 18, 22, 18)
        card.layout_.setSpacing(6)
        self.title = QLabel("")
        self.title.setProperty("role", "question")
        self.title.setWordWrap(True)
        self.subtitle_label = QLabel("")
        self.subtitle_label.setProperty("role", "hint")
        self.subtitle_label.setStyleSheet("font-size: 14px;")
        self.subtitle_label.setWordWrap(True)
        card.addWidget(self.title)
        card.addWidget(self.subtitle_label)
        card.layout_.addSpacing(10)

        self.error = error_label()
        card.addWidget(self.error)

        self.content_holder = QVBoxLayout()
        self.content_holder.setSpacing(10)
        card.layout_.addLayout(self.content_holder)
        grid.addWidget(card, 0, 1, alignment=Qt.AlignTop)

        self.next_btn = arrow_button("Next")
        self.next_btn.clicked.connect(self._exams_chosen)
        grid.addWidget(self.next_btn, 1, 1, alignment=Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)

        self._step = None
        self._exams: set[str] = set()
        self._exam_buttons: dict[str, QPushButton] = {}

    def on_show(self, **kwargs) -> None:
        set_error(self.error, None)
        self._step = None
        self._exams = set()
        self._load_step()

    def _first_name(self) -> str:
        return (session.profile or {}).get("name", "").split(" ")[0]

    # ---------------- back ----------------

    def back_mode(self) -> str:
        return "page"

    def go_back(self) -> None:
        """Back from a later step un-answers "do you know your career?"; from the first
        question it goes to your details (name, class, board…) to change them."""
        step = (self._step or {}).get("step")
        self.ctx.voice.cancel()
        if step in AFTER_CAREER_GOAL:
            run_async(
                api_client.update_profile_fields, {"knows_career_goal": None},
                on_success=lambda _r: self._load_step(), on_error=self._failed,
            )
        else:
            self.ctx.navigate("setup", edit=True)

    def _clear_content(self) -> None:
        clear_layout(self.content_holder)

    def _load_step(self) -> None:
        run_async(api_client.onboarding_next_step, on_success=self._render_step, on_error=self._failed)

    def _render_step(self, step: dict) -> None:
        self._step = step
        first = self._first_name()
        self.title.setText(f"Hi {first}, let's get started!" if first else "Let's get started!")
        self.subtitle_label.setText(step.get("prompt", ""))
        self._clear_content()
        name = step["step"]
        self.next_btn.setVisible(name == "exam_selection")
        if name == "exam_selection":
            self.ctx.set_step_pill("Choose 1 or more")
        else:
            self.ctx.set_progress("Ready!", 6, 6)

        if name == "basic_info":
            # Details are collected by MAYA's step-by-step questions; this only happens for a
            # profile that skipped some of them.
            self.ctx.navigate("setup", edit=True)
            return
        if name == "career_exploration_assessment":
            self._render_redirect_card("Start Exploration", "class8_9_exploration",
                                        "We'll ask about your interests, favorite subjects, and the kind of work "
                                        "you imagine enjoying — no pressure to decide anything yet.")
        elif name == "stream_assessment":
            self._render_redirect_card("Start Stream Assessment", "class10_stream",
                                        "A short set of questions to recommend PCM, PCB, Commerce, or Arts.")
        elif name == "career_goal_question":
            self._render_career_goal_question()
        elif name == "exam_selection":
            self._render_exam_selection()
        elif name == "career_counselling_assessment":
            self._render_redirect_card("Start Career Counselling", "class11_12_career",
                                        "Let's run a structured conversation about your strengths, interests, and "
                                        "goals to find career paths that may fit.")

        self._speak_step(name, step.get("prompt", ""))

    # ---------------- voice ----------------

    def _speak_step(self, name: str, prompt: str) -> None:
        """MAYA reads each step out. Single-answer questions also listen for a spoken reply;
        the multi-field basic-info form doesn't, since every box there already has the
        keyboard's mic key for dictation."""
        if not prompt or not self.isVisible():
            return
        voice = self.ctx.voice
        if name == "career_goal_question":
            voice.ask(prompt, on_answer=self._heard_career_goal, on_no_answer=self._voice_fallback)
        elif name == "exam_selection":
            voice.ask(
                "Which exam are you preparing for — JEE, NEET, or something else?",
                on_answer=self._heard_exam, on_no_answer=self._voice_fallback,
            )
        else:
            voice.say(prompt)

    def _heard_career_goal(self, transcript: str) -> None:
        answer = parse_yes_no(transcript)
        if answer is None:
            self._voice_fallback("unclear")
            return
        self._answer_career_goal(answer)

    def _heard_exam(self, transcript: str) -> None:
        choice = parse_exam_choice(transcript)
        if choice is None:
            self._voice_fallback("unclear")
            return
        self._exams = {choice if choice in ("jee", "neet") else "other"}
        self._paint_exams()
        self._finish_to(choice)

    def _voice_fallback(self, reason: str) -> None:
        if reason in ("silence", "unclear"):
            self.ctx.voice.say("You can also just tap one of the options on the screen.")

    def _render_redirect_card(self, button_text: str, assessment_type: str, blurb: str) -> None:
        self.content_holder.addWidget(muted(blurb))
        btn = arrow_button(button_text)
        btn.clicked.connect(lambda: self._finish_to_careers(assessment_type))
        self.content_holder.addWidget(btn)

    def _render_career_goal_question(self) -> None:
        """Two big answers, stacked: "✓ Yes, I know" and "Not sure yet"."""
        yes_btn = QPushButton("  Yes, I know")
        yes_btn.setProperty("variant", "next")
        yes_btn.setIcon(svg_icon("check", "#ffffff", 22, 2.6))
        yes_btn.setIconSize(QSize(22, 22))
        yes_btn.setMinimumHeight(52)
        yes_btn.setCursor(Qt.PointingHandCursor)
        yes_btn.clicked.connect(lambda: self._answer_career_goal(True))
        no_btn = QPushButton("Not sure yet")
        no_btn.setProperty("variant", "soft")
        no_btn.setMinimumHeight(52)
        no_btn.setCursor(Qt.PointingHandCursor)
        no_btn.clicked.connect(lambda: self._answer_career_goal(False))
        self.content_holder.addWidget(yes_btn)
        self.content_holder.addWidget(no_btn)

    def _answer_career_goal(self, knows: bool) -> None:
        self.ctx.voice.cancel()  # tapped or spoken, answer once — stop listening for a second one
        run_async(
            api_client.update_profile, knows_career_goal=knows,
            on_success=lambda _r: self._load_step(), on_error=self._failed,
        )

    # The design's six paths. The app has full tracks for JEE and NEET; the others lead to
    # career exploration, where MAYA can still talk them through.
    EXAMS = [("JEE\n(Engineering)", "jee"), ("NEET\n(Medical)", "neet"), ("CUET", "cuet"),
             ("UPSC", "upsc"), ("SSC", "ssc"), ("Other", "other")]

    def _render_exam_selection(self) -> None:
        self.title.setText("Which exam or path are you preparing for?")
        self.subtitle_label.setText("Select all that apply.")
        grid = QGridLayout()
        grid.setSpacing(10)
        self._exam_buttons = {}
        for i, (label, key) in enumerate(self.EXAMS):
            btn = QPushButton(label)
            btn.setProperty("variant", "choice")
            btn.setStyleSheet("font-size: 13px;")
            btn.setMinimumHeight(52)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self._toggle_exam(k))
            grid.addWidget(btn, i // 3, i % 3)
            self._exam_buttons[key] = btn
        self.content_holder.addLayout(grid)
        self._paint_exams()

    def _toggle_exam(self, key: str) -> None:
        self._exams ^= {key}
        set_error(self.error, None)
        self._paint_exams()

    def _paint_exams(self) -> None:
        for key, btn in self._exam_buttons.items():
            btn.setProperty("selected", "true" if key in self._exams else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _exams_chosen(self) -> None:
        """JEE or NEET gets its own track; anything else goes on to career exploration."""
        if not self._exams:
            set_error(self.error, "Tap at least one — or Other if it isn't listed.")
            return
        self._finish_to("jee" if "jee" in self._exams else "neet" if "neet" in self._exams else "careers")

    def _finish_to_careers(self, assessment_type: str) -> None:
        self.ctx.voice.cancel()
        run_async(
            api_client.update_profile, onboarding_completed=True, target_exam_code="careers",
            on_success=lambda _r: self._complete_and_navigate("careers", type=assessment_type),
            on_error=self._failed,
        )

    # What picking an exam means for the rest of the app: the student's target, which keeps
    # college, mock test, and MAYA's suggestions on their own track.
    TARGET_EXAMS = {"jee": "JEE_MAIN", "neet": "NEET_UG", "careers": "careers"}

    def _finish_to(self, page_name: str) -> None:
        self.ctx.voice.cancel()
        run_async(
            api_client.update_profile, onboarding_completed=True,
            target_exam_code=self.TARGET_EXAMS.get(page_name),
            on_success=lambda _r: self._complete_and_navigate(page_name),
            on_error=self._failed,
        )

    def _complete_and_navigate(self, page_name: str, **kwargs) -> None:
        session.refresh_profile()
        self.ctx.navigate(page_name, **kwargs)
        self.ctx.clear_history()  # onboarding is done — Back shouldn't lead into it again

    def _failed(self, err: Exception) -> None:
        message = err.message if isinstance(err, ApiError) else "Something went wrong. Please try again."
        set_error(self.error, message)
