"""MAYA's first-run questions, one at a time: name, class (6 to 12, or college — then which year
instead of the school board), board, where you live, and — for classes 11/12, where admission
prediction needs them — domicile and category.

Every question can be answered by voice (MAYA asks it out loud and listens), by tapping one
of the choices, or by typing on the on-screen keyboard. Back and Next move between questions,
and a last review screen lets you change any answer before it's saved.

The same page edits details later (edit=True): it starts from the saved profile and jumps
to the first question that still has no answer, or straight to the review.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.api_client import ApiError
from app.pages.base import BasePage
from app.pages.greeting import salutation
from app.session import session
from app.voice import IDLE
from app.voice_parsing import (
    BOARDS, COLLEGE, STATES, extract_name, is_unsure, matching_states, parse_board, parse_category, parse_class,
    parse_college_year, parse_state, parse_yes_no, wants_to_go_back, wants_to_skip,
)
from app.config import PORTRAIT_RATIO
from app.theme import FOREGROUND, PRIMARY
from app.widgets.common import Card, arrow_button, clear_layout, error_label, secondary_button, set_error
from app.widgets.maya_status import MayaStatus
from app.widgets.svg_icons import icon_pixmap, svg_icon
from app.workers import run_async

NAME, CLASS, COLLEGE_YEAR, BOARD, STATE, DOMICILE_SAME, DOMICILE, CATEGORY, REVIEW = (
    "name", "class", "college_year", "board", "state", "domicile_same", "domicile", "category", "review",
)
ANSWER_KEYS = {
    NAME: "name", CLASS: "class_level", COLLEGE_YEAR: "education_stage", BOARD: "school_board", STATE: "state",
    DOMICILE_SAME: "domicile_same", DOMICILE: "domicile_state", CATEGORY: "category",
}
CLASSES = (6, 7, 8, 9, 10, 11, 12)
COLLEGE_YEARS = [("1st year", "ug_y1"), ("2nd year", "ug_y2"), ("3rd year", "ug_y3"), ("4th year", "ug_y4"),
                 ("5th year", "ug_y5"), ("Finished", "graduate")]
SKIPPED = ""  # the category answer for "I'd rather not say"
SENIOR_CLASS = 11  # domicile and category only matter for JEE/NEET admission prediction

MASCOT_HEIGHT = 250

# How many times MAYA re-asks after not catching an answer before suggesting tapping or typing.
RETRIES = 1

QUESTIONS = {
    NAME: "What's your name?",
    CLASS: "Which class are you in?",
    COLLEGE_YEAR: "Which year of college are you in?",
    BOARD: "Which board is your school?",
    STATE: "Where do you live?",
    DOMICILE_SAME: "Is {state} your domicile state too?",
    DOMICILE: "Which state is your domicile?",
    CATEGORY: "Which category are you in?",
    REVIEW: "Did I get everything right?",
}
HINTS = {
    NAME: "Say your name, or tap the box to type it.",
    CLASS: "Say it, or tap your class — or College.",
    COLLEGE_YEAR: "Say it, or tap your year.",
    BOARD: "Say it, or tap your board.",
    STATE: "Say your state or city — or type it and tap a suggestion.",
    DOMICILE_SAME: "Domicile is the state you're officially a resident of. It decides which state-quota seats you can get.",
    DOMICILE: "Say it, or type it and tap a suggestion.",
    CATEGORY: "Only used to predict admission chances from past cutoffs. You can skip it.",
    REVIEW: "Say yes or tap Looks good — or tap Change next to anything that's wrong.",
}
FALLBACKS = {
    NAME: "type your name", STATE: "type your state", DOMICILE: "type your domicile state",
    REVIEW: "tap Looks good",
}


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ChoiceGrid(QWidget):
    """Big tap targets for a question with a fixed set of answers."""

    def __init__(self, options: list[tuple[str, object]], columns: int, on_pick):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self._buttons: dict[object, QPushButton] = {}
        for i, (label, value) in enumerate(options):
            btn = QPushButton(label)
            btn.setProperty("variant", "choice")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(46)
            btn.clicked.connect(lambda _checked=False, v=value: on_pick(v))
            grid.addWidget(btn, i // columns, i % columns)
            self._buttons[value] = btn

    def set_selected(self, value) -> None:
        for option, btn in self._buttons.items():
            btn.setProperty("selected", "true" if value is not None and option == value else "false")
            _repolish(btn)


class StateField(QWidget):
    """A state box with tap-to-pick suggestions — typing "Chhattisgarh" on a touchscreen is no fun."""

    def __init__(self, placeholder: str, on_pick, on_submit):
        super().__init__()
        self._on_pick = on_pick
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.textEdited.connect(self._suggest)
        self.input.returnPressed.connect(on_submit)
        layout.addWidget(self.input)
        suggestions = QWidget()
        self._grid = QGridLayout(suggestions)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        layout.addWidget(suggestions)

    def _suggest(self, text: str) -> None:
        while self._grid.count():
            self._grid.takeAt(0).widget().deleteLater()
        for i, state in enumerate(matching_states(text, limit=4)):
            btn = secondary_button(state)
            btn.setToolTip(state)
            # Long union-territory names get clipped rather than widening the whole card.
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _checked=False, s=state: self._on_pick(s))
            self._grid.addWidget(btn, i // 2, i % 2)

    def set_value(self, state: str | None) -> None:
        self.input.setText(state or "")
        self._suggest("")

    def value(self) -> str | None:
        text = self.input.text().strip()
        return text if text in STATES else parse_state(text)


class SetupPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.voice = ctx.voice
        self.editing = False
        self.answers: dict = {}
        self._step = NAME
        self._came_from: str | None = None
        self._misses = 0

        # The design: MAYA on the left with "Answer by voice" under her; the question card
        # on the right with Next under it. Back and the progress live in the top bar.
        grid = QGridLayout(self)
        grid.setContentsMargins(16, 6, 20, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)

        self.status = MayaStatus(self.voice, QSize(int(MASCOT_HEIGHT * PORTRAIT_RATIO), MASCOT_HEIGHT),
                                 show_text=False, portrait=True)
        grid.addWidget(self.status, 0, 0, alignment=Qt.AlignCenter)

        self.voice_btn = QPushButton("  Answer by voice")
        self.voice_btn.setProperty("variant", "pill")
        self.voice_btn.setIcon(svg_icon("mic-badge", PRIMARY, 34))
        self.voice_btn.setIconSize(QSize(34, 34))
        self.voice_btn.setCursor(Qt.PointingHandCursor)
        self.voice_btn.clicked.connect(self._answer_by_voice)
        # On the review screen the same corner holds a Back button instead, as in the design.
        self.back_btn = secondary_button("  Back")
        self.back_btn.setIcon(svg_icon("arrow-left", FOREGROUND, 16))
        self.back_btn.setMinimumHeight(40)
        self.back_btn.clicked.connect(lambda: self.ctx.go_back())
        corner = QVBoxLayout()
        corner.addWidget(self.voice_btn, alignment=Qt.AlignLeft)
        corner.addWidget(self.back_btn, alignment=Qt.AlignLeft)
        grid.addLayout(corner, 1, 0)

        card = Card()
        card.layout_.setContentsMargins(20, 16, 20, 16)
        card.layout_.setSpacing(6)
        self.question = QLabel("")
        self.question.setProperty("role", "question")
        self.question.setWordWrap(True)
        card.addWidget(self.question)
        self.hint = QLabel("")
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)
        card.addWidget(self.hint)
        card.layout_.addSpacing(8)

        self.name_input = QLineEdit()
        self.name_input.setProperty("variant", "big")
        self.name_input.setPlaceholderText("Your name")
        self.name_input.returnPressed.connect(self._next)
        self.class_choices = ChoiceGrid([(f"{c}th", c) for c in CLASSES] + [("College", COLLEGE)], 4,
                                        lambda v: self._pick(CLASS, v))
        self.year_choices = ChoiceGrid(COLLEGE_YEARS, 3, lambda v: self._pick(COLLEGE_YEAR, v))
        self.board_choices = ChoiceGrid([(b, b) for b in BOARDS], 2, lambda v: self._pick(BOARD, v))
        self.state_field = StateField("Your state", lambda v: self._pick(STATE, v), self._next)
        self.domicile_same_choices = ChoiceGrid(
            [("Yes, same state", True), ("No, a different one", False)], 2, lambda v: self._pick(DOMICILE_SAME, v),
        )
        self.domicile_field = StateField("Your domicile state", lambda v: self._pick(DOMICILE, v), self._next)
        self.category_choices = ChoiceGrid(
            [(c, c) for c in ("General", "EWS", "OBC", "SC", "ST")] + [("Skip", SKIPPED)], 3,
            lambda v: self._pick(CATEGORY, v),
        )
        self.review = QWidget()
        self.review_rows = QVBoxLayout(self.review)
        self.review_rows.setContentsMargins(0, 0, 0, 0)
        self.review_rows.setSpacing(0)

        self._inputs = {
            NAME: self.name_input, CLASS: self.class_choices, COLLEGE_YEAR: self.year_choices,
            BOARD: self.board_choices, STATE: self.state_field,
            DOMICILE_SAME: self.domicile_same_choices, DOMICILE: self.domicile_field,
            CATEGORY: self.category_choices, REVIEW: self.review,
        }
        for widget in self._inputs.values():
            card.addWidget(widget)

        self.error = error_label()
        card.addWidget(self.error)
        grid.addWidget(card, 0, 1, alignment=Qt.AlignTop)

        self.next_btn = arrow_button("Next")
        self.next_btn.clicked.connect(self._next)
        grid.addWidget(self.next_btn, 1, 1, alignment=Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)

        self.voice.state_changed.connect(lambda state: self.voice_btn.setEnabled(state == IDLE))

    # ---------------- entering the page ----------------

    def on_show(self, edit: bool = False, **kwargs) -> None:
        self.editing = edit
        self.answers = self._answers_from_profile() if edit else {}
        self.name_input.setText(self.answers.get("name", ""))
        self.state_field.set_value(self.answers.get("state"))
        self.domicile_field.set_value(self.answers.get("domicile_state"))
        self.next_btn.setEnabled(True)
        set_error(self.error, None)
        start = self._first_unanswered() if edit else NAME
        self._show_step(start)
        # Deferred: on first boot this runs while the window is still being constructed.
        QTimer.singleShot(400, lambda: self._ask("first" if edit else "intro") if self._step == start else None)

    def _answers_from_profile(self) -> dict:
        profile = session.profile or {}
        answers = {key: profile[key] for key in ANSWER_KEYS.values() if profile.get(key) is not None}
        if "school_board" in answers and answers["school_board"] not in BOARDS:
            answers["school_board"] = "Other"
        if profile.get("state") and profile.get("domicile_state"):
            answers["domicile_same"] = profile["domicile_state"] == profile["state"]
        stage = profile.get("education_stage") or ""
        if stage.startswith("ug_") or stage in ("pg", "graduate"):
            answers["class_level"] = COLLEGE
        else:
            answers.pop("education_stage", None)
        return answers

    def _in_college(self) -> bool:
        return self.answers.get("class_level") == COLLEGE

    def _school_class(self) -> int:
        level = self.answers.get("class_level")
        return level if isinstance(level, int) else 0

    # ---------------- steps ----------------

    def _steps(self) -> list[str]:
        steps = [NAME, CLASS, COLLEGE_YEAR, STATE] if self._in_college() else [NAME, CLASS, BOARD, STATE]
        if self._school_class() >= SENIOR_CLASS:
            steps.append(DOMICILE_SAME)
            if self.answers.get("domicile_same") is False:
                steps.append(DOMICILE)
            steps.append(CATEGORY)
        return steps + [REVIEW]

    def _answered(self, step: str) -> bool:
        return step == REVIEW or self.answers.get(ANSWER_KEYS[step]) is not None

    def _first_unanswered(self) -> str:
        return next((s for s in self._steps() if not self._answered(s)), REVIEW)

    def _show_step(self, step: str) -> None:
        self._came_from, self._step = self._step, step
        self._misses = 0
        set_error(self.error, None)
        for name, widget in self._inputs.items():
            widget.setVisible(name == step)

        questions = self._steps()[:-1]
        total = len(questions) + 1  # a segment for the review too, left empty until it's done
        if step in questions:
            number = questions.index(step) + 1
            self.ctx.set_progress(f"{number}/{len(questions)}", number, total)
        else:
            self.ctx.set_progress("Almost done", total - 1, total)
        on_review = step == REVIEW
        self.voice_btn.setVisible(not on_review)
        self.back_btn.setVisible(on_review)
        first_run_intro = step == NAME and not self.editing
        self.question.setText("Hi, I'm MAYA! What's your name?" if first_run_intro else
                              QUESTIONS[step].format(state=self.answers.get("state", "that")))
        self.hint.setText(HINTS[step])

        self.class_choices.set_selected(self.answers.get("class_level"))
        self.year_choices.set_selected(self.answers.get("education_stage"))
        self.board_choices.set_selected(self.answers.get("school_board"))
        self.domicile_same_choices.set_selected(self.answers.get("domicile_same"))
        self.category_choices.set_selected(self.answers.get("category"))
        if step == REVIEW:
            self._render_review()

        self._set_next_text("Looks good" if step == REVIEW else "Next")
        self.back_btn.setEnabled(self.back_mode() != "blocked")
        self.ctx.refresh_back_button()

    def _advance(self) -> None:
        step = self._first_unanswered()
        self._show_step(step)
        self._ask("first")

    def _pick(self, step: str, value) -> None:
        self.answers[ANSWER_KEYS[step]] = value
        if step in (STATE, DOMICILE):
            (self.state_field if step == STATE else self.domicile_field).set_value(value)
        self._advance()

    def _next(self) -> None:
        step = self._step
        if step == REVIEW:
            self._submit()
            return
        if step == NAME:
            name = " ".join(self.name_input.text().split())
            if not name:
                set_error(self.error, "Tell me your name so I know what to call you.")
                return
            self.answers["name"] = name
        elif step in (STATE, DOMICILE):
            field = self.state_field if step == STATE else self.domicile_field
            state = field.value()
            if state is None:
                set_error(self.error, "I don't know that state — type a bit of it and tap one of the suggestions.")
                return
            self._pick(step, state)
            return
        elif not self._answered(step):
            set_error(self.error, "Tap one of the options — or just say it.")
            return
        self._advance()

    # ---------------- back navigation (MainWindow's Back button calls these too) ----------------

    def back_mode(self) -> str:
        steps = self._steps()
        if self._step in steps and steps.index(self._step) > 0:
            return "page"
        profile = session.profile or {}
        needed = ("state", "domicile_state") if self._in_college() else ("state", "domicile_state", "school_board")
        details_saved = all(profile.get(k) for k in needed)
        return "history" if self.editing and details_saved else "blocked"

    def go_back(self) -> None:
        steps = self._steps()
        index = steps.index(self._step) if self._step in steps else len(steps)
        if index > 0:
            self._show_step(steps[index - 1])
            self._ask("again")

    # ---------------- review ----------------

    REVIEW_ROWS = {
        NAME: ("user", "Name"), CLASS: ("class", "Class"), COLLEGE_YEAR: ("class", "Year"), BOARD: ("board", "Board"), STATE: ("pin", "Lives in"),
        DOMICILE_SAME: ("home", "Domicile"), DOMICILE: ("home", "Domicile state"), CATEGORY: ("users", "Category"),
    }

    def _render_review(self) -> None:
        """The design's table: icon, what it is, your answer, and Change."""
        clear_layout(self.review_rows)
        for step in self._steps()[:-1]:
            icon_name, key = self.REVIEW_ROWS[step]
            row = QFrame()
            row.setObjectName("ReviewRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(2, 3, 0, 3)
            line.setSpacing(10)
            icon = QLabel()
            icon.setPixmap(icon_pixmap(icon_name, FOREGROUND, 16))
            icon.setFixedWidth(20)
            line.addWidget(icon)
            label = QLabel(key)
            label.setProperty("role", "review-key")
            label.setFixedWidth(104)
            line.addWidget(label)
            value = QLabel(self._display_value(step))
            value.setProperty("role", "review-value")
            line.addWidget(value, stretch=1)
            change = QPushButton("Change")
            change.setProperty("variant", "link")
            change.setCursor(Qt.PointingHandCursor)
            change.clicked.connect(lambda _checked=False, s=step: self._change(s))
            line.addWidget(change)
            self.review_rows.addWidget(row)

    def _display_value(self, step: str) -> str:
        value = self.answers.get(ANSWER_KEYS[step])
        if step == CLASS:
            return "College" if value == COLLEGE else f"Class {value}"
        if step == COLLEGE_YEAR:
            return dict((v, k) for k, v in COLLEGE_YEARS).get(value, str(value))
        if step == DOMICILE_SAME:
            return "Same as where I live" if value else "A different state"
        if step == CATEGORY:
            return value or "Not shared"
        return str(value)

    def _change(self, step: str) -> None:
        self._show_step(step)
        self._ask("again")

    # ---------------- voice ----------------

    def _answer_by_voice(self) -> None:
        self._misses = 0
        self._ask("again")

    def _ask(self, kind: str) -> None:
        if not self.isVisible():
            return
        self.voice.ask(self._spoken(self._step, kind), on_answer=self._heard, on_no_answer=self._missed)

    def _spoken(self, step: str, kind: str) -> str:
        first = (self.answers.get("name") or "").split(" ")[0]
        state = self.answers.get("state", "")
        sorry = "Sorry, I didn't catch that. "
        if step == NAME:
            if kind == "intro":
                return f"{salutation()}! I'm MAYA, your career guide. Let's get you set up. What's your name?"
            return (sorry if kind == "retry" else "") + "What's your name?"
        if step == CLASS:
            if kind == "retry":
                return "Sorry, which class are you in? Anything from six to twelve — or say college."
            if kind == "first" and self._came_from == NAME and first:
                return f"Nice to meet you, {first}! Which class are you in?"
            return "Which class are you in?"
        if step == COLLEGE_YEAR:
            if kind == "retry":
                return "Sorry, which year — first, second, third, fourth? Or say finished."
            return "Which year of college are you in?"
        if step == BOARD:
            if kind == "retry":
                return sorry + "Is it CBSE, ICSE, or a state board?"
            # Name and class in one breath ("I'm Dhruv, class 11") skips the class question.
            greet = f"Nice to meet you, {first}! " if kind == "first" and self._came_from == NAME and first else ""
            return greet + "Which board is your school — CBSE, ICSE, or a state board?"
        if step == STATE:
            return "Sorry, which state do you live in?" if kind == "retry" else "Where do you live? Just tell me your state."
        if step == DOMICILE_SAME:
            if kind == "retry":
                return f"Sorry — is your domicile state {state}? Yes or no?"
            return f"Is {state} also your domicile state — the state you're officially a resident of?"
        if step == DOMICILE:
            return (sorry if kind == "retry" else "") + "Which state is your domicile?"
        if step == CATEGORY:
            if kind == "retry":
                return sorry + "General, EWS, OBC, SC, or ST — or say skip."
            return ("Which category are you in — General, EWS, OBC, SC, or ST? "
                    "I only use it to predict admission chances, and you can say skip.")
        return self._spoken_review()

    def _spoken_review(self) -> str:
        a = self.answers
        board = {"State Board": "a state board", "Other": "another board"}.get(a.get("school_board"), f"{a.get('school_board')} board")
        first = a.get('name', '').split(' ')[0]
        if self._in_college():
            year = self._display_value(COLLEGE_YEAR).lower()
            parts = [f"{first}, at college, {'finished' if year == 'finished' else year}, living in {a.get('state')}"]
        else:
            parts = [f"{first}, class {a.get('class_level')}, {board}, living in {a.get('state')}"]
        if self._school_class() >= SENIOR_CLASS:
            if a.get("domicile_same") is False:
                parts.append(f"domicile {a.get('domicile_state')}")
            if a.get("category"):
                parts.append(f"{a['category']} category")
        return f"Let me check I've got this right: {', '.join(parts)}. Is that right?"

    def _heard(self, transcript: str) -> None:
        if wants_to_go_back(transcript) and self.back_mode() == "page":
            self.go_back()
            return
        handlers = {
            NAME: self._heard_name, CLASS: self._heard_class, COLLEGE_YEAR: self._heard_college_year, BOARD: self._heard_board,
            STATE: self._heard_state, DOMICILE_SAME: self._heard_domicile_same, DOMICILE: self._heard_domicile,
            CATEGORY: self._heard_category, REVIEW: self._heard_review,
        }
        if not handlers[self._step](transcript):
            self._missed("unclear")

    def _heard_name(self, transcript: str) -> bool:
        name = extract_name(transcript)
        if not name:
            return False
        self.answers["name"] = name
        self.name_input.setText(name)
        level = parse_class(transcript)  # "I'm Dhruv and I'm in class 11" answers two questions
        if level:
            self.answers["class_level"] = level
        self._advance()
        return True

    def _heard_class(self, transcript: str) -> bool:
        level = parse_class(transcript)
        if level == COLLEGE and (year := parse_college_year(transcript)):
            self.answers["education_stage"] = year  # "second year B.Tech" answers both
        if level:
            self._pick(CLASS, level)
        return level is not None

    def _heard_college_year(self, transcript: str) -> bool:
        year = parse_college_year(transcript)
        if year:
            self._pick(COLLEGE_YEAR, year)
        return year is not None

    def _heard_board(self, transcript: str) -> bool:
        board = parse_board(transcript)
        if board:
            self._pick(BOARD, board)
        return board is not None

    def _heard_state(self, transcript: str) -> bool:
        state = parse_state(transcript)
        if state:
            self._pick(STATE, state)
        return state is not None

    def _heard_domicile_same(self, transcript: str) -> bool:
        if is_unsure(transcript):
            return False  # "I don't know" isn't a no — ask again, and the hint explains domicile
        named = parse_state(transcript)
        if named and named != self.answers.get("state"):  # "No, it's Karnataka"
            self.answers["domicile_state"] = named
            self.domicile_field.set_value(named)
            self._pick(DOMICILE_SAME, False)
            return True
        answer = True if named else parse_yes_no(transcript)
        if answer is None:
            return False
        self._pick(DOMICILE_SAME, answer)
        return True

    def _heard_domicile(self, transcript: str) -> bool:
        state = parse_state(transcript)
        if state:
            self._pick(DOMICILE, state)
        return state is not None

    def _heard_category(self, transcript: str) -> bool:
        category = SKIPPED if wants_to_skip(transcript) else parse_category(transcript)
        if category is not None:
            self._pick(CATEGORY, category)
        return category is not None

    def _heard_review(self, transcript: str) -> bool:
        answer = parse_yes_no(transcript)
        if answer is True:
            self._submit()
        elif answer is False:
            self.hint.setText("Okay — tap Change next to whatever needs fixing.")
            self.voice.say("Okay. Tap Change next to whatever needs fixing.")
        return answer is not None

    def _missed(self, reason: str) -> None:
        fallback = FALLBACKS.get(self._step, "tap your answer")
        if reason in ("no_mic", "error"):
            problem = "No microphone found" if reason == "no_mic" else "I can't hear you right now"
            self.hint.setText(f"{problem} — {fallback} instead.")
            return
        if self._step == REVIEW:
            return  # no answer is fine here; Looks good is right there
        self._misses += 1
        if self._misses <= RETRIES:
            self._ask("retry")
            return
        self.hint.setText(f"No problem — {fallback} instead, or tap Answer by voice to try again.")
        self.voice.say(f"No problem. You can {fallback} instead.")

    # ---------------- saving ----------------

    def _details(self) -> dict:
        a = self.answers
        senior = self._school_class() >= SENIOR_CLASS
        details = {
            "name": a["name"],
            # A college student has finished class 12; where they are now is education_stage.
            "class_level": 12 if self._in_college() else a["class_level"],
            "education_stage": a["education_stage"] if self._in_college() else f"class_{a['class_level']}",
            "state": a["state"],
            "domicile_state": a["domicile_state"] if senior and a.get("domicile_same") is False else a["state"],
            "category": (a.get("category") or None) if senior else None,
        }
        if not self._in_college():
            details["school_board"] = a["school_board"]
        return details

    def _set_next_text(self, text: str) -> None:
        self.next_btn.setText(f"{text}  ")

    def _submit(self) -> None:
        missing = self._first_unanswered()
        if missing != REVIEW:
            self._show_step(missing)
            self._ask("first")
            return
        self.voice.cancel()
        set_error(self.error, None)
        self.next_btn.setEnabled(False)
        self._set_next_text("One moment…")
        save = session.save_details if self.editing else session.complete_setup
        run_async(save, self._details(), on_success=self._saved, on_error=self._failed)

    def _saved(self, _result) -> None:
        self.next_btn.setEnabled(True)
        self._set_next_text("Looks good")
        if self.editing:
            done = (session.profile or {}).get("onboarding_completed")
            self.ctx.navigate("dashboard" if done else "onboarding")
            self.ctx.clear_history()
        # First run: session.logged_in takes it from here (MAYA greets you, then onboarding).

    def _failed(self, err: Exception) -> None:
        self.next_btn.setEnabled(True)
        self._set_next_text("Looks good")
        message = err.message if isinstance(err, ApiError) else "Something went wrong. Please try again."
        set_error(self.error, message)
