"""Stream explorer: for a class 9–10 student choosing PCM, PCB, PCMB, commerce or humanities —
what each stream keeps open, what opens only if you add an optional subject, and what closes,
with the subject that decides it. From the career graph (the subjects each degree requires);
colleges can differ, so it says to check the official notice.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import LANGUAGES, preferred_language
from app.pages.base import BasePage
from app.pages.directions import link_button, words
from app.session import session
from app.widgets.common import Card, clear_layout, error_label, heading, muted, secondary_button, set_error, subtitle
from app.workers import run_async

STREAMS = (("pcm", "PCM"), ("pcb", "PCB"), ("pcmb", "PCMB"), ("commerce", "Commerce"), ("humanities", "Humanities"))
COLOURS = {"open": "#15803d", "if_you_add": "#4f46e5", "closed": "#64748b"}


class StreamExplorerPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("What does each stream keep open?"))
        layout.addWidget(subtitle("Pick a stream to see which careers stay open after class 12, which need one more "
                                  "subject, and which close."))
        chips = QHBoxLayout()
        self.stream_buttons = {}
        for key, label in STREAMS:
            button = secondary_button(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, k=key: self.show_stream(k))
            chips.addWidget(button)
            self.stream_buttons[key] = button
        chips.addStretch(1)
        layout.addLayout(chips)
        languages = QHBoxLayout()
        self.language_buttons = {}
        for code, label in LANGUAGES:
            button = secondary_button(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, c=code: self.set_language(c))
            languages.addWidget(button)
            self.language_buttons[code] = button
        languages.addStretch(1)
        layout.addLayout(languages)
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)
        self.stream = "pcm"
        self.data: dict | None = None

    def set_language(self, code: str) -> None:
        self.ctx.assessment_language = code
        for c, button in self.language_buttons.items():
            button.setChecked(c == code)
        if self.data is not None:
            self._render(self.data)

    def on_show(self, stream: str | None = None, returning: bool = False, **kwargs) -> None:
        self.set_language(preferred_language(self.ctx))
        if returning and self.data is not None:
            return
        own = ((session.profile or {}).get("stream") or "").lower()
        self.show_stream(stream or (own if own in dict(STREAMS) else "pcm"))

    def show_stream(self, stream: str) -> None:
        self.stream = stream
        for key, button in self.stream_buttons.items():
            button.setChecked(key == stream)
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Loading…"))
        run_async(api_client.career_stream, stream,
                  on_success=lambda data, s=stream: self.stream == s and self._render(data), on_error=self._failed)

    def _render(self, data: dict) -> None:
        self.data = data
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        sections = (
            ("open", words(lang, "Stays open", "खुला रहता है")),
            ("if_you_add", words(lang, "Opens if you add a subject", "एक विषय जोड़ने पर खुलता है")),
            ("closed", words(lang, "Closes", "बंद हो जाता है")),
        )
        for bucket, title in sections:
            rows = data.get(bucket) or []
            if not rows:
                continue
            card = Card()
            title_label = heading(f"{title} ({len(rows)})")
            title_label.setStyleSheet(f"color: {COLOURS[bucket]};")
            card.addWidget(title_label)
            for row in rows:
                text = row["career"]["name"][lang]
                if bucket == "open":
                    text += words(lang, f" — via {row['via']['name']['en']}", f" — {row['via']['name']['hi']} से")
                elif row["missing"]:
                    needs = ", ".join(m["name"][lang] for m in row["missing"])
                    text += words(lang, f" — needs {needs}", f" — {needs} चाहिए")
                button = link_button(text + "  ›")
                button.clicked.connect(lambda _c=False, k=row["career"]["key"].split(":", 1)[1]:
                                       self.ctx.navigate("direction", key=k))
                card.addWidget(button)
                for note in row.get("notes") or []:
                    card.addWidget(muted(f"{note['name'][lang]}: {note['note']}"))
            self.body_layout.addWidget(card)
        self.body_layout.addWidget(muted(words(
            lang, "From the class 11–12 subjects each degree usually requires. Colleges can differ — check the official "
                  "admission notice.",
            "हर डिग्री के लिए आम तौर पर ज़रूरी 11वीं–12वीं के विषयों के आधार पर। कॉलेजों में फ़र्क हो सकता है — आधिकारिक "
            "प्रवेश सूचना ज़रूर देखें।")))

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
