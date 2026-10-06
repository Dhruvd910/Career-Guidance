"""Taking one assessment: a question at a time, by voice or by touch, in English or Hindi.

The server says which question comes next and what MAYA should say for it; this page shows it,
reads it out and listens. A spoken answer is matched here first (app/answer_matching.py) — in
English, Hindi or Hinglish — and only if that fails does the server's interpreter get a look
(never for marks or a problem's answer: those are taken as heard, or tapped); if neither is
sure, MAYA asks once more and then leaves it to a tap. "Go back" / "peeche" and
"skip" / "chhodo" work by voice too. Leaving midway is fine: it picks up where you stopped.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.answer_matching import match_answer
from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.voice import IDLE
from app.widgets.common import clear_layout, error_label, heading, muted, primary_button, secondary_button, set_error
from app.widgets.icons import mic_icon
from app.workers import run_async

RETRIES = 1
MEASURED = ("problem", "marks")  # answered as heard or tapped — never interpreted (see the API's interpret.py)
LETTERS = "ABCDEFGH"
WORDS = {
    "en": {"question": "Question {n} of about {total}", "sorry": "Sorry, I didn't catch that.",
           "hint": "Tap an answer, or just say it. You can say “go back” or “skip”.",
           "no_voice": "Voice isn't available right now — tap an answer instead.",
           "tap": "No problem — tap an answer, or tap Answer by voice to try again.",
           "checking": "Let me check what you meant…", "next": "Next", "skip": "Skip", "back": "Previous question"},
    "hi": {"question": "सवाल {n} / लगभग {total}", "sorry": "माफ़ कीजिए, मैं ठीक से सुन नहीं पाई।",
           "hint": "जवाब पर टैप कीजिए, या बोलिए। आप “पीछे” या “छोड़ो” भी कह सकते हैं।",
           "no_voice": "अभी आवाज़ काम नहीं कर रही — जवाब पर टैप कीजिए।",
           "tap": "कोई बात नहीं — जवाब पर टैप कीजिए, या दोबारा बोलने के लिए 'Answer by voice' दबाइए।",
           "checking": "देखती हूँ आपका मतलब क्या था…", "next": "आगे", "skip": "छोड़ें", "back": "पिछला सवाल"},
}


def _wrapping_button(text: str, selected: bool) -> QPushButton:
    """An answer button whose text wraps — the skill levels are a full sentence each."""
    button = QPushButton()
    button.setProperty("variant", "choice")
    button.setProperty("selected", "true" if selected else "false")
    button.setCursor(Qt.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    inner = QVBoxLayout(button)
    inner.setContentsMargins(12, 8, 12, 8)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAttribute(Qt.WA_TransparentForMouseEvents)
    label.setStyleSheet("background: transparent;")
    inner.addWidget(label)
    button.setMinimumHeight(max(44, inner.sizeHint().height() + 4))
    button.style().unpolish(button)
    button.style().polish(button)
    return button


class AssessmentRunnerPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.voice = ctx.voice
        self.view: dict | None = None
        self.item: dict | None = None
        self.language = "en"
        self._token = 0  # bumped for every new item: late voice or server answers for an old one are dropped
        self._busy = False
        self._misses = 0
        self._shown_at = 0.0
        self._typed = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.progress_label = muted("")
        top.addWidget(self.progress_label, 1)
        self.voice_btn = secondary_button("  Answer by voice")
        self.voice_btn.setIcon(mic_icon())
        self.voice_btn.setIconSize(QSize(16, 16))
        self.voice_btn.clicked.connect(lambda: self._ask())
        top.addWidget(self.voice_btn)
        layout.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setObjectName("AssessmentProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        self.prompt = heading("")
        layout.addWidget(self.prompt)
        self.prompt_en = muted("")  # the English, small, under a Hindi question
        layout.addWidget(self.prompt_en)
        self.code = QLabel("")
        self.code.setObjectName("CodeBlock")
        self.code.setTextFormat(Qt.PlainText)
        self.code.setStyleSheet("QLabel#CodeBlock { font-family: 'DejaVu Sans Mono', monospace; font-size: 15px; "
                                "background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 10px; }")
        layout.addWidget(self.code)
        self.hint = muted("")
        layout.addWidget(self.hint)

        self.options_holder = QWidget()
        self.options_grid = QGridLayout(self.options_holder)
        self.options_grid.setContentsMargins(0, 0, 0, 0)
        self.options_grid.setSpacing(8)
        layout.addWidget(self.options_holder)

        self.error = error_label()
        layout.addWidget(self.error)

        nav = QHBoxLayout()
        self.back_btn = secondary_button("←  Back")
        self.back_btn.clicked.connect(self.go_back)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        self.skip_btn = secondary_button("Skip")
        self.skip_btn.clicked.connect(lambda: self._submit(None, skipped=True))
        nav.addWidget(self.skip_btn)
        layout.addLayout(nav)
        layout.addStretch(1)

        self.voice.state_changed.connect(lambda state: self.voice_btn.setEnabled(state == IDLE and self.item is not None))

    def _words(self, key: str) -> str:
        return WORDS.get(self.language, WORDS["en"])[key]

    # ---------------- starting ----------------

    def on_show(self, key: str | None = None, language: str = "en", returning: bool = False, **kwargs) -> None:
        if returning:
            if self.view and self.view.get("complete"):
                self.ctx.navigate("assessment")  # back from the result: the hub, not a finished test
            elif self.item is not None:
                self._ask()
            return
        if not key:
            self.ctx.navigate("assessment")
            return
        self.language = language if language in ("en", "hi") else "en"
        self.view = self.item = None
        self._busy = False
        set_error(self.error, None)
        clear_layout(self.options_grid)
        self.code.setVisible(False)
        self.prompt_en.setVisible(False)
        self.prompt.setText("Getting MAYA's questions ready…" if self.language == "en" else "सवाल तैयार हो रहे हैं…")
        run_async(api_client.assessment_start, key, self.language, on_success=self._render, on_error=self._failed)

    # ---------------- showing an item ----------------

    def _render(self, view: dict) -> None:
        self._busy = False
        self._token += 1
        self.view = view
        if view.get("complete"):
            self.item = None
            self.voice.cancel()
            self.ctx.navigate("assessment_result", result=view["result"], fresh=True)
            return
        item = self.item = view["item"]
        self.language = view.get("language", self.language)
        progress = view["progress"]
        n, total = progress["answered"] + 1, max(progress["estimate"], progress["answered"] + 1)
        self.progress_label.setText(self._words("question").format(n=n, total=total)
                                    + f" · {item['section'][self.language]}")
        self.progress.setMaximum(total)
        self.progress.setValue(n - 1)
        self.prompt.setText(item["prompt"][self.language])
        # Under a Hindi question, the English — except for problems, whose Hindi is its own test.
        show_en = self.language == "hi" and item["type"] != "problem"
        self.prompt_en.setText(item["prompt"]["en"] if show_en else "")
        self.prompt_en.setVisible(show_en)
        self.code.setText(item.get("code") or "")
        self.code.setVisible(bool(item.get("code")))
        self.hint.setText(self._words("hint"))
        self.back_btn.setText("←  " + self._words("back"))
        self.back_btn.setEnabled(bool(view.get("can_go_back")))
        self.back_btn.setVisible(bool(view.get("can_go_back")))  # on the first question it would do nothing
        self.skip_btn.setText(self._words("skip"))
        set_error(self.error, None)
        self._build_answers(item)
        self._misses = 0
        self._shown_at = time.monotonic()
        if hasattr(self.ctx, "refresh_back_button"):
            self.ctx.refresh_back_button()  # the header's Back now steps through these questions
        self._ask()

    def _build_answers(self, item: dict) -> None:
        clear_layout(self.options_grid)
        chosen = (item.get("answer") or {}).get("option")
        options = item.get("options") or []
        if item["type"] == "marks":
            self._build_marks_pad((item.get("answer") or {}).get("value"))
            return
        labels = []
        for n, option in enumerate(options):
            label = option["label"][self.language]
            if item["type"] == "problem":
                label = f"{LETTERS[n]}    {label}"
            elif item["type"] == "anchored":
                label = f"{n + 1}.  {label}"
            labels.append(label)
        columns = 2 if item["type"] == "choice" and len(options) >= 4 and max(map(len, labels)) <= 24 else 1
        for n, (option, label) in enumerate(zip(options, labels)):
            button = _wrapping_button(label, option["key"] == chosen)
            button.clicked.connect(lambda _c=False, k=option["key"]: self._choose(k))
            self.options_grid.addWidget(button, n // columns, n % columns)

    def _build_marks_pad(self, value: float | None) -> None:
        self._typed = "" if value is None else f"{value:g}"
        self.marks_display = heading("")
        self.marks_display.setAlignment(Qt.AlignCenter)
        self.options_grid.addWidget(self.marks_display, 0, 0, 1, 3)
        keys = ["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "⌫"]
        for n, key in enumerate(keys):
            button = secondary_button(key)
            button.setMinimumHeight(44)
            button.clicked.connect(lambda _c=False, k=key: self._type(k))
            self.options_grid.addWidget(button, 1 + n // 3, n % 3)
        self.marks_next = primary_button(self._words("next") + "  →")
        self.marks_next.setMinimumHeight(44)
        self.marks_next.clicked.connect(self._submit_marks)
        self.options_grid.addWidget(self.marks_next, 5, 0, 1, 3)
        self._show_typed()

    def _type(self, key: str) -> None:
        if key == "⌫":
            self._typed = self._typed[:-1]
        elif key == "." and "." in self._typed:
            return
        elif len(self._typed) < 5:
            self._typed += key
        self._show_typed()

    def _typed_value(self) -> float | None:
        try:
            value = float(self._typed)
        except ValueError:
            return None
        return value if 0 <= value <= 100 else None

    def _show_typed(self) -> None:
        self.marks_display.setText((self._typed or "–") + " %")
        self.marks_next.setEnabled(self._typed_value() is not None)

    def _submit_marks(self) -> None:
        value = self._typed_value()
        if value is not None:
            self.voice.cancel()
            self._submit({"value": value})

    # ---------------- answering ----------------

    def _choose(self, option_key: str) -> None:
        self.voice.cancel()
        self._submit({"option": option_key})

    def _submit(self, answer: dict | None, skipped: bool = False, transcript: str | None = None,
                by: str = "touch") -> None:
        if self._busy or self.view is None or self.item is None:
            return
        self._busy = True
        self._token += 1
        self.voice.cancel()
        response_ms = int((time.monotonic() - self._shown_at) * 1000)
        run_async(api_client.assessment_answer, self.view["attempt_id"], self.item["key"], answer, skipped,
                  transcript, by, response_ms, on_success=self._render, on_error=self._failed)

    def back_mode(self) -> str:
        """The top Back leaves the test (it picks up where you stopped next time); "Previous question"
        below the answers steps back inside it."""
        return "history"

    def go_back(self) -> None:
        if self._busy or self.view is None or not self.view.get("can_go_back"):
            return
        self._busy = True
        self._token += 1
        self.voice.cancel()
        run_async(api_client.assessment_back, self.view["attempt_id"], on_success=self._render, on_error=self._failed)

    # ---------------- voice ----------------

    def _ask(self, retry: bool = False) -> None:
        if self.item is None or not self.isVisible():
            return
        token = self._token
        text = (self._words("sorry") + " " if retry else "") + self.item["say"]
        self.voice.ask(text, on_answer=lambda t: self._heard(token, t),
                       on_no_answer=lambda reason: self._missed(token, reason), language=self.language)

    def _heard(self, token: int, transcript: str) -> None:
        if token != self._token or self.item is None:
            return
        matched = match_answer(transcript, self.item)
        if matched is not None:
            self._act(matched, transcript, "keywords")
            return
        if self.item["type"] in MEASURED:
            self._missed(token, "unclear")  # a mark or a problem's answer is never left to a model's reading
            return
        # Not something the Pi could place: one quick look by the server's interpreter.
        self.hint.setText(self._words("checking"))
        item_key = self.item["key"]
        run_async(api_client.assessment_interpret, self.view["attempt_id"], item_key, transcript,
                  on_success=lambda result: self._interpreted(token, transcript, result),
                  on_error=lambda _e: self._missed(token, "unclear"))

    def _interpreted(self, token: int, transcript: str, result: dict) -> None:
        if token != self._token:
            return
        if result.get("answer"):
            self._submit(result["answer"], transcript=transcript, by="llm")
        elif result.get("skip"):
            self._submit(None, skipped=True, transcript=transcript, by="llm")
        else:
            self._missed(token, "unclear")

    def _act(self, matched: dict, transcript: str, by: str) -> None:
        if matched.get("back"):
            self.go_back()
        elif matched.get("skip"):
            self._submit(None, skipped=True, transcript=transcript, by=by)
        else:
            self._submit(matched, transcript=transcript, by=by)

    def _missed(self, token: int, reason: str) -> None:
        if token != self._token:
            return
        if reason in ("no_mic", "error"):
            self.hint.setText(self._words("no_voice"))
            return
        self._misses += 1
        if self._misses <= RETRIES:
            self._ask(retry=True)
        else:
            self.hint.setText(self._words("tap"))

    # ---------------- trouble ----------------

    def _failed(self, err: Exception) -> None:
        self._busy = False
        set_error(self.error, err.message if isinstance(err, ApiError) else
                  "Couldn't reach MAYA's server just now — your answers so far are saved. Try again in a moment.")
