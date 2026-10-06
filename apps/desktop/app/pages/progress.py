"""My progress (spec §20): how measured skills moved — first vs now, with every measurement —
plus the roadmap's completion, milestones and projects done, assessments taken, goals, and the
careers explored. Skill levels come only from assessments and practice papers; ticking a step
done is progress on the roadmap, and the page says so.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import preferred_language, short_date
from app.pages.base import BasePage
from app.pages.directions import words
from app.widgets.common import Card, clear_layout, error_label, heading, muted, secondary_button, set_error, subtitle
from app.workers import run_async

CHANGE = {1: ("Improved", "बेहतर हुआ", "#15803d"), 0: ("About the same", "लगभग वही", "#64748b"),
          -1: ("Lower this time", "इस बार कम", "#a16207")}


def bar(value: float, colour: str) -> QProgressBar:
    b = QProgressBar()
    b.setRange(0, 100)
    b.setValue(round(value * 100))
    b.setTextVisible(False)
    b.setFixedHeight(8)
    b.setStyleSheet(f"QProgressBar::chunk {{ background: {colour}; border-radius: 4px; }}")
    return b


class ProgressPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("My progress"))
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
        run_async(api_client.progress, on_success=self._render, on_error=self._failed)

    def _render(self, data: dict) -> None:
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        roadmap = data["roadmap"]
        self.sub.setText(words(lang, f"Roadmap {roadmap['completion']}% done", f"रोडमैप {roadmap['completion']}% पूरा")
                         + (f" · {roadmap['focus']['name'][lang]}" if roadmap.get("focus") else ""))

        skills = Card()
        skills.addWidget(heading(words(lang, "Your skills — first vs now", "आपके हुनर — पहले बनाम अब")))
        if not data["skills"]:
            skills.addWidget(muted(words(lang, "Nothing measured yet. Each assessment or practice paper adds a point here.",
                                         "अभी कुछ मापा नहीं गया। हर आकलन या प्रैक्टिस पेपर यहाँ एक बिंदु जोड़ता है।")))
            go = secondary_button(words(lang, "My Tests", "मेरे टेस्ट"))
            go.clicked.connect(lambda: self.ctx.navigate("assessment"))
            skills.addWidget(go)
        for s in data["skills"]:
            skills.addWidget(self._skill(s, lang))
        self.body_layout.addWidget(skills)

        done = Card()
        done.addWidget(heading(words(lang, "Done so far", "अब तक पूरा")))
        m, p = data["milestones"], data["projects"]
        done.addWidget(QLabel(words(lang, f"Milestones: {m['done']} of {m['total']}", f"पड़ाव: {m['total']} में से {m['done']}")))
        for title in m["done_titles"]:
            done.addWidget(muted("✓  " + title[lang]))
        done.addWidget(QLabel(words(lang, f"Projects: {p['done']} of {p['total']}", f"प्रोजेक्ट: {p['total']} में से {p['done']}")))
        for title in p["done_titles"]:
            done.addWidget(muted("✓  " + title[lang]))
        done.addWidget(QLabel(words(lang, f"Assessments taken: {data['assessments']['attempts']}",
                                    f"दिए गए आकलन: {data['assessments']['attempts']}")))
        self.body_layout.addWidget(done)

        explored = data["careers_explored"]
        lines = []
        if explored.get("focus"):
            lines.append(words(lang, "Focus: ", "लक्ष्य: ") + explored["focus"]["name"][lang])
        if explored.get("branches"):
            lines.append(words(lang, "Exploring: ", "खोज: ") + ", ".join(b["name"][lang] for b in explored["branches"]))
        if explored.get("moved_away_from"):
            lines.append(words(lang, "Moved away from: ", "इनसे हटे: ") + ", ".join(d["name"][lang] for d in explored["moved_away_from"]))
        if data.get("goals"):
            lines.append(words(lang, "Goals: ", "लक्ष्य: ") + "; ".join(g["title"] for g in data["goals"]))
        if lines:
            card = Card()
            card.addWidget(heading(words(lang, "Careers and goals", "करियर और लक्ष्य")))
            for line in lines:
                label = QLabel(line)
                label.setWordWrap(True)
                card.addWidget(label)
            self.body_layout.addWidget(card)
        self.body_layout.addWidget(muted(data["note"][lang]))

    def _skill(self, s: dict, lang: str) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(3)
        top = QHBoxLayout()
        name = QLabel(s["name"][lang])
        name.setStyleSheet("font-weight: 700;")
        top.addWidget(name, 1)
        if len(s["points"]) > 1:
            en, hi, colour = CHANGE[s["change"]]
            chip = QLabel(words(lang, en, hi))
            chip.setStyleSheet(f"color: {colour}; font-weight: 700;")
            top.addWidget(chip)
        layout.addLayout(top)
        if len(s["points"]) > 1:
            layout.addWidget(muted(words(lang, f"First: {round(s['initial'] * 100)}%", f"पहले: {round(s['initial'] * 100)}%")))
            layout.addWidget(bar(s["initial"], "#cbd5e1"))
        layout.addWidget(muted(words(lang, f"Now: {round(s['current'] * 100)}%", f"अब: {round(s['current'] * 100)}%")
                               + (f" — {s['points'][-1]['says'][lang]}" if s["points"][-1].get("says") else "")
                               + f" · {short_date(s['points'][-1]['at'])}"))
        layout.addWidget(bar(s["current"], "#4f46e5"))
        return holder

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
