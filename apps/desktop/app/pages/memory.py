"""MAYA's memory: what she remembers about the student, their journey, and the permissions.

Three tabs on one screen (800x480): what she remembers — every item deletable, the student's own
private ones included; the journey (the timeline); and the permissions, with the notice in
English or Hindi and, for anyone under 18, the parent's or guardian's agreement.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.widgets.common import (
    Card, clear_layout, danger_button, error_label, ghost_button, heading, muted, primary_button, secondary_button,
    set_error, subtitle,
)
from app.workers import run_async

TABS = (("remembers", "What she remembers"), ("journey", "My journey"), ("permissions", "Permissions"))
RELATIONSHIPS = ("Mother", "Father", "Guardian", "Other family member")
CONFIRM_MS = 4000


def _date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%-d %b")
    except ValueError:
        return ""


class MemoryPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("MAYA's memory"))
        layout.addWidget(subtitle("What MAYA remembers about you — and your say over it."))

        tabs = QHBoxLayout()
        self.tab_buttons: dict[str, QPushButton] = {}
        for key, label in TABS:
            button = secondary_button(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, k=key: self.show_tab(k))
            tabs.addWidget(button)
            self.tab_buttons[key] = button
        layout.addLayout(tabs)

        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)

        self.tab = "remembers"
        self.consent: dict | None = None
        self.notice_language = "en"

    def on_show(self, tab: str = "remembers", **kwargs) -> None:
        self.show_tab(tab)

    def show_tab(self, tab: str) -> None:
        self.tab = tab
        for key, button in self.tab_buttons.items():
            button.setChecked(key == tab)
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Loading…"))
        loaders = {"remembers": (api_client.get_memory, self._show_memory),
                   "journey": (api_client.timeline, self._show_journey),
                   "permissions": (api_client.get_consent, self._show_permissions)}
        fetch, show = loaders[tab]
        run_async(fetch, on_success=lambda data, t=tab: self.tab == t and show(data), on_error=self._failed)

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's memory.")

    # ---------------- what she remembers ----------------

    def _show_memory(self, data: dict) -> None:
        clear_layout(self.body_layout)
        if not data.get("enabled"):
            card = Card()
            card.addWidget(heading("Memory is off"))
            card.addWidget(muted("MAYA forgets each conversation when it ends, so every time starts from zero. "
                                 "Turn memory on and she'll pick up where you left off."))
            turn_on = primary_button("Turn memory on")
            turn_on.clicked.connect(lambda: self.show_tab("permissions"))
            card.addWidget(turn_on)
            self.body_layout.addWidget(card)
            return
        sections = [
            ("Topics you're working through", "thread", [
                (t["id"], f"{t['title']} — {t['decision_status']}" + (f". Next: {t['next_step']}" if t.get("next_step") else ""), False)
                for t in data["threads"] if t["status"] != "resolved"]),
            ("Interests", "interest", [(i["id"], i["text"], False) for i in data["interests"]]),
            ("Goals", "goal", [(g["id"], g["text"], False) for g in data["goals"]]),
            ("Things to keep in mind", "constraint", [(c["id"], c["text"], c["sensitive"]) for c in data["constraints"]]),
            ("Things you've told her", "memory", [(m["id"], m["text"], m["sensitive"]) for m in data["memories"]]),
        ]
        empty = True
        for title, kind, items in sections:
            if not items:
                continue
            empty = False
            card = Card()
            card.addWidget(heading(title))
            for item_id, text, sensitive in items:
                card.addWidget(self._item_row(kind, item_id, text, sensitive))
            self.body_layout.addWidget(card)
        if data.get("recent_sessions"):
            card = Card()
            card.addWidget(heading("Recent conversations"))
            for s in data["recent_sessions"][:5]:
                card.addWidget(muted(f"{_date(s['created_at'])} — {s['summary']}"))
            self.body_layout.addWidget(card)
        if empty and not data.get("recent_sessions"):
            self.body_layout.addWidget(muted("Nothing yet — MAYA writes her notes when a conversation ends."))
            return
        forget_all = danger_button("Forget everything")
        forget_all.clicked.connect(lambda: self._confirm(forget_all, "Tap again to forget everything",
                                                         lambda: run_async(api_client.forget_everything,
                                                                           on_success=lambda _r: self.show_tab("remembers"),
                                                                           on_error=self._failed)))
        self.body_layout.addWidget(forget_all)

    def _item_row(self, kind: str, item_id: int, text: str, sensitive: bool) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        label = QLabel(("<i>Private</i> · " if sensitive else "") + text)
        label.setWordWrap(True)
        line.addWidget(label, stretch=1)
        delete = ghost_button("Delete")
        delete.clicked.connect(lambda: self._confirm(delete, "Sure?", lambda: run_async(
            api_client.forget, kind, item_id, on_success=lambda _r: row.hide(), on_error=self._failed)))
        line.addWidget(delete)
        return row

    @staticmethod
    def _confirm(button: QPushButton, prompt: str, action) -> None:
        """Two taps, so a stray touch can't delete anything."""
        if button.property("armed"):
            button.setProperty("armed", False)
            action()
            return
        original = button.text()
        button.setProperty("armed", True)
        button.setText(prompt)

        def disarm() -> None:
            if button.property("armed"):
                button.setProperty("armed", False)
                button.setText(original)

        QTimer.singleShot(CONFIRM_MS, disarm)

    # ---------------- the journey ----------------

    def _show_journey(self, events: list) -> None:
        clear_layout(self.body_layout)
        if not events:
            self.body_layout.addWidget(muted("Your journey starts with your first conversation with MAYA."))
            return
        card = Card()
        for event in events:
            row = QLabel(f"<b>{_date(event['occurred_at'])}</b> &nbsp; {event['description']}")
            row.setWordWrap(True)
            card.addWidget(row)
        self.body_layout.addWidget(card)

    # ---------------- permissions ----------------

    def _show_permissions(self, consent: dict) -> None:
        self.consent = consent
        clear_layout(self.body_layout)
        card = Card()
        switch = ghost_button("हिंदी में पढ़ें" if self.notice_language == "en" else "Read in English")
        switch.clicked.connect(self._switch_notice_language)
        card.addWidget(switch)
        notice = QLabel(consent["notice"][self.notice_language])
        notice.setWordWrap(True)
        card.addWidget(notice)
        self.body_layout.addWidget(card)

        choices = Card()
        self.memory_box = QCheckBox("Remember our conversations")
        self.memory_box.setChecked(consent["long_term_memory"]["granted"])
        self.signals_box = QCheckBox("Notice how I'm feeling, to talk more kindly")
        self.signals_box.setChecked(consent["emotion_signals"]["granted"])
        choices.addWidget(self.memory_box)
        choices.addWidget(self.signals_box)
        self.guardian_fields: dict[str, QWidget] = {}
        if consent["is_minor"]:
            choices.addWidget(muted("You're under 18, so a parent or guardian has to agree to turn these on."))
            self.guardian_fields["name"] = QLineEdit()
            self.guardian_fields["name"].setPlaceholderText("Parent's or guardian's name")
            relationship = QComboBox()
            relationship.addItems(RELATIONSHIPS)
            self.guardian_fields["relationship"] = relationship
            self.guardian_fields["contact"] = QLineEdit()
            self.guardian_fields["contact"].setPlaceholderText("Their phone number or email")
            for field in self.guardian_fields.values():
                choices.addWidget(field)
            self.guardian_agrees = QCheckBox("I am this student's parent or guardian, I have read the notice, "
                                             "and I agree")
            choices.addWidget(self.guardian_agrees)
        save = primary_button("Save")
        save.clicked.connect(self._save_permissions)
        choices.addWidget(save)
        self.saved_note = muted("")
        choices.addWidget(self.saved_note)
        self.body_layout.addWidget(choices)

    def _switch_notice_language(self) -> None:
        self.notice_language = "hi" if self.notice_language == "en" else "en"
        if self.consent:
            self._show_permissions(self.consent)

    def _guardian(self) -> dict | None:
        if not self.guardian_fields:
            return None
        relationship = self.guardian_fields["relationship"].currentText()
        return {"name": self.guardian_fields["name"].text().strip(), "relationship": relationship,
                "contact": self.guardian_fields["contact"].text().strip()}

    def _save_permissions(self) -> None:
        set_error(self.error, None)
        wanted = {"long_term_memory": self.memory_box.isChecked(), "emotion_signals": self.signals_box.isChecked()}
        changes = {k: v for k, v in wanted.items() if v != self.consent[k]["granted"]}
        if not changes:
            self.saved_note.setText("Nothing to change.")
            return
        guardian = self._guardian()
        if any(changes.values()) and guardian is not None:
            if not (guardian["name"] and guardian["contact"]):
                set_error(self.error, "Please add your parent's or guardian's name and phone number or email.")
                return
            if not self.guardian_agrees.isChecked():
                set_error(self.error, "Your parent or guardian needs to tick that they agree.")
                return

        def apply() -> list:
            return [api_client.set_consent(kind, granted, guardian if granted else None)
                    for kind, granted in changes.items()]

        def done(results: list) -> None:
            removed = sum(sum(r.get("deleted", {}).values()) for r in results)
            self.saved_note.setText("Saved." + (f" {removed} remembered items were deleted." if removed else ""))
            run_async(api_client.get_consent, on_success=lambda c: self.tab == "permissions" and self._show_permissions(c))

        run_async(apply, on_success=done, on_error=self._failed)
