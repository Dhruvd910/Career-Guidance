"""Where we are (spec §37): the eight things MAYA keeps track of, on one page — where we left off,
what's worth doing next (each with Open, Done and Not now), what you're working toward, how you've
progressed and what you've decided. Everything comes from the student's own records."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import preferred_language
from app.pages.base import BasePage
from app.pages.directions import words
from app.widgets.common import Card, clear_layout, error_label, ghost_button, heading, muted, secondary_button, set_error, subtitle
from app.workers import run_async

# The agenda's screens, as the Pi's pages (the roadmap opens on its own next step).
SCREENS = {"roadmap_node": "roadmap", "profile": "setup", "career_detail": "direction", "exam": None, "assessment_run": "assessment_run"}
EXAM_PAGES = {"JEE_MAIN": "jee", "JEE_ADVANCED": "jee", "NEET_UG": "neet"}


def open_item(ctx, item: dict, lang: str) -> None:
    screen = item.get("screen") or {}
    page, args = screen.get("page"), dict(screen.get("args") or {})
    if page == "exam":
        page, args = EXAM_PAGES.get(args.get("code"), "dashboard"), {}
    elif page == "profile":
        page, args = "setup", {"edit": True}
    elif page == "assessment_run":
        args["language"] = lang
    elif page in SCREENS:
        page = SCREENS[page] or page
        if page == "roadmap":
            args = {}
    ctx.navigate(page or "maya", **args)


def _text(text: str, style: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if style:
        label.setStyleSheet(style)
    return label


class WhereWeArePage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("Where we are"))
        self.sub = subtitle("")
        layout.addWidget(self.sub)
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)

    def on_show(self, **kwargs) -> None:
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Loading…"))
        run_async(api_client.mentor_brief, on_success=self._render, on_error=self._failed)

    def _render(self, b: dict) -> None:
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        who = b["who"]
        stage = who.get("education_stage") or ""
        where = (f"college, year {stage[4:]}" if stage.startswith("ug_y") else "graduated" if stage in ("graduate", "pg")
                 else f"class {who['class_level']}" if who.get("class_level") else None)
        self.sub.setText(", ".join(x for x in (who.get("name"), where, who.get("stream"), who.get("town")) if x))

        last = b.get("last_stopped")
        card = Card()
        card.addWidget(heading(words(lang, "Where we left off", "हम कहाँ रुके थे")))
        if last and last.get("current_counselling_topic"):
            status = {"undecided": ("not decided yet", "अभी तय नहीं"), "leaning": ("leaning one way", "एक तरफ़ झुकाव"),
                      "decided": ("decided", "तय"), "reopened": ("open again", "फिर से खुला")}.get(last.get("decision_status"), ("", ""))
            card.addWidget(_text(f"<b>{last['current_counselling_topic']}</b> — {words(lang, *status)}"))
            if last.get("current_problem"):
                card.addWidget(muted(last["current_problem"]))
            for q in last.get("open_questions") or []:
                card.addWidget(muted("?  " + q))
            if last.get("next_step"):
                card.addWidget(muted(words(lang, "Next we agreed: ", "आगे तय हुआ: ") + last["next_step"]))
        elif b.get("discussed"):
            card.addWidget(_text(b["discussed"][0]["summary"]))
        else:
            card.addWidget(muted(b.get("note") or words(lang, "Nothing yet — talk to MAYA and it'll show here.",
                                                         "अभी कुछ नहीं — MAYA से बात कीजिए, यहाँ दिखेगा।")))
        self.body_layout.addWidget(card)

        card = Card()
        card.addWidget(heading(words(lang, "What's next", "आगे क्या")))
        if not b.get("next"):
            card.addWidget(muted(words(lang, "Nothing pressing right now.", "अभी कुछ ज़रूरी नहीं।")))
        for item in b.get("next") or []:
            card.addWidget(self._item(item, lang))
        self.body_layout.addWidget(card)

        work = b["working_toward"]
        lines = []
        if work.get("focus"):
            lines.append(words(lang, "Focus: ", "लक्ष्य: ") + work["focus"][lang])
        if work.get("next_step"):
            lines.append(words(lang, "Roadmap's next step: ", "रोडमैप का अगला कदम: ") + work["next_step"][lang])
        lines += [words(lang, "Goal: ", "लक्ष्य: ") + g for g in work.get("goals") or []]
        if work.get("shortlist"):
            lines.append(words(lang, f"{work['shortlist']} colleges shortlisted", f"{work['shortlist']} कॉलेज चुने हुए"))
        if lines:
            card = Card()
            card.addWidget(heading(words(lang, "Working toward", "किस ओर बढ़ रहे हैं")))
            for line in lines:
                card.addWidget(_text(line))
            self.body_layout.addWidget(card)

        prog = b["progress"]
        card = Card()
        card.addWidget(heading(words(lang, "How you've progressed", "आपकी प्रगति")))
        for s in prog.get("skills") or []:
            change = {1: words(lang, "improved", "बेहतर"), 0: words(lang, "about the same", "लगभग वही"),
                      -1: words(lang, "lower this time", "इस बार कम")}[s["change"]]
            card.addWidget(_text(f"{s['skill']}: {s['first']}% → {s['now']}% ({change})"))
        if prog.get("roadmap_percent") is not None:
            card.addWidget(muted(words(lang, f"Roadmap {prog['roadmap_percent']}% done · {prog['assessments']} assessments taken",
                                       f"रोडमैप {prog['roadmap_percent']}% पूरा · {prog['assessments']} आकलन दिए")))
        self.body_layout.addWidget(card)

        if b.get("decided"):
            card = Card()
            card.addWidget(heading(words(lang, "Decided", "तय किया")))
            for d in b["decided"]:
                card.addWidget(_text(d["what"] + (f" — {d['position']}" if d.get("position") else "")))
            self.body_layout.addWidget(card)
        if b.get("note"):
            self.body_layout.addWidget(muted(b["note"]))

    def _item(self, item: dict, lang: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)
        layout.addWidget(_text(f"<b>{item['title'][lang]}</b>"))
        layout.addWidget(muted(f"{item['why'][lang]} · {item['source']}"))
        row = QHBoxLayout()
        go = secondary_button(words(lang, "Open", "खोलें"))
        go.clicked.connect(lambda: open_item(self.ctx, item, lang))
        row.addWidget(go)
        for what, en, hi in (("done", "Done", "हो गया"), ("not_now", "Not now", "अभी नहीं")):
            b = ghost_button(words(lang, en, hi))
            b.clicked.connect(lambda _c=False, w=what: run_async(api_client.mentor_mark, item["key"], w,
                                                                on_success=lambda _r: self.on_show(), on_error=self._failed))
            row.addWidget(b)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        layout.addWidget(holder)
        return box

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
