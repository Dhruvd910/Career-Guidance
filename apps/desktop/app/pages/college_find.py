"""Finding colleges (spec §17): from a career (or everything), filtered by what matters to the
student — near home, within a budget, with a hostel, with a medical facility, by exam — and
sorted by what they choose. No "best college" score: each row shows plain facts, and a college
left out because something about it isn't known is counted, not hidden.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import preferred_language
from app.pages.base import BasePage
from app.pages.directions import words
from app.session import session
from app.widgets.common import Card, clear_layout, error_label, heading, muted, set_error, subtitle
from app.workers import run_async

DISTANCES = ((None, "Anywhere", "कहीं भी"), (50, "50 km", "50 km"), (150, "150 km", "150 km"), (400, "400 km", "400 km"))
BUDGETS = ((None, "Any fee", "कोई भी फ़ीस"), (100_000, "≤ ₹1 lakh", "≤ ₹1 लाख"), (250_000, "≤ ₹2.5 lakh", "≤ ₹2.5 लाख"))
SORTS = (("distance", "Nearest", "सबसे पास"), ("fee", "Lowest fee", "कम फ़ीस"), ("nirf", "NIRF rank", "NIRF रैंक"),
         ("name", "Name", "नाम"))
EXAMS = ((None, "All exams", "सभी परीक्षाएँ"), ("JEE_MAIN", "JEE Main", "JEE Main"), ("JEE_ADVANCED", "JEE Advanced", "JEE Advanced"),
         ("NEET_UG", "NEET", "NEET"))


def _chip(text: str, on: bool) -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(True)
    b.setChecked(on)
    b.setProperty("variant", "chip")
    b.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return b


class CollegeFindPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(8)
        self.title = heading("Find colleges")
        layout.addWidget(self.title)
        self.sub = subtitle("")
        layout.addWidget(self.sub)
        self.filters_box = QVBoxLayout()
        layout.addLayout(self.filters_box)
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        layout.addWidget(self.body)
        layout.addStretch(1)
        self.state = {"career": None, "career_name": None, "radius_km": None, "budget_max": None, "hostel": False,
                      "medical": False, "exam": None, "sort": "distance"}

    def on_show(self, career: str | None = None, career_name: str | None = None, returning: bool = False, **kwargs) -> None:
        if not returning:
            self.state.update(career=career, career_name=career_name)
        self._filters()
        self._load()

    def _home(self) -> tuple[str | None, str | None]:
        profile = session.profile or {}
        return profile.get("city"), profile.get("state")

    def _filters(self) -> None:
        lang = preferred_language(self.ctx)
        clear_layout(self.filters_box)
        home, _ = self._home()
        self.title.setText(words(lang, "Find colleges", "कॉलेज खोजें") + (f" — {self.state['career_name']}" if self.state["career_name"] else ""))
        self.sub.setText(words(lang, f"Distances from {home}" if home else "Add your town in your details to see distances",
                               f"{home} से दूरी" if home else "दूरी देखने के लिए अपनी जानकारी में अपना शहर जोड़ें"))

        def row(options, key):
            line = QHBoxLayout()
            line.setSpacing(4)
            for value, en, hi in options:
                chip = _chip(words(lang, en, hi), self.state[key] == value)
                chip.clicked.connect(lambda _c=False, v=value: self._set(key, v))
                line.addWidget(chip)
            line.addStretch(1)
            holder = QWidget()
            holder.setLayout(line)
            self.filters_box.addWidget(holder)

        if home:
            row(DISTANCES, "radius_km")
        row(BUDGETS, "budget_max")
        row(EXAMS, "exam")
        toggles = QHBoxLayout()
        for key, en, hi in (("hostel", "Hostel", "हॉस्टल"), ("medical", "Medical facility", "चिकित्सा सुविधा")):
            chip = _chip(words(lang, en, hi), self.state[key])
            chip.clicked.connect(lambda _c=False, k=key: self._set(k, not self.state[k]))
            toggles.addWidget(chip)
        toggles.addStretch(1)
        holder = QWidget()
        holder.setLayout(toggles)
        self.filters_box.addWidget(holder)
        row(SORTS if home else SORTS[1:], "sort")

    def _set(self, key: str, value) -> None:
        self.state[key] = value
        self._filters()
        self._load()

    def _load(self) -> None:
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Loading…"))
        home, home_state = self._home()
        sort = self.state["sort"] if home or self.state["sort"] != "distance" else "name"
        run_async(api_client.discover_colleges, career=self.state["career"], exam=self.state["exam"],
                  home=home, home_state=home_state, radius_km=self.state["radius_km"] if home else None,
                  budget_max=self.state["budget_max"], hostel=self.state["hostel"], medical=self.state["medical"],
                  sort=sort, limit=60, on_success=self._render, on_error=self._failed)

    def _render(self, data: dict) -> None:
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        summary = words(lang, f"{data['total']} colleges", f"{data['total']} कॉलेज")
        left = data.get("left_out") or {}
        if left:
            summary += words(lang, " · left out because it isn't known: ", " · जानकारी न होने से छोड़े गए: ") + \
                ", ".join(f"{n} ({why})" for why, n in left.items())
        self.body_layout.addWidget(muted(summary))
        for c in data["colleges"]:
            self.body_layout.addWidget(self._row(c, lang))
        self.body_layout.addWidget(muted(data.get("note", "")))

    def _row(self, c: dict, lang: str) -> QPushButton:
        b = QPushButton()
        b.setProperty("variant", "option")
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(b)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        name = QLabel(f"<b>{c['name']}</b>")
        name.setWordWrap(True)
        name.setStyleSheet("background: transparent;")
        layout.addWidget(name)
        bits = [f"{c['city']}, {c['state']}" if c.get("city") else c["state"]]
        if c.get("distance_km") is not None:
            bits.append(f"{c['distance_km']:g} km")
        if c.get("tuition"):
            bits.append(words(lang, "tuition ", "ट्यूशन ") + c["tuition"]["value"]
                        + (f" ({c['tuition']['academic_year']})" if c["tuition"].get("academic_year") else ""))
        if c.get("nirf_rank"):
            bits.append(f"NIRF #{c['nirf_rank']}")
        line = QLabel(" · ".join(bits))
        line.setWordWrap(True)
        line.setStyleSheet("background: transparent; color: #475569; font-size: 12px;")
        layout.addWidget(line)
        b.setMinimumHeight(layout.sizeHint().height() + 4)
        b.clicked.connect(lambda: self.ctx.navigate("college_detail", college_id=c["id"]))
        return b

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")


class CollegeSourcesPage(BasePage):
    """Where everything about one college comes from: each document, its publisher, how official
    it is, and when it was fetched."""

    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(8)
        self.title = heading("Where this comes from")
        layout.addWidget(self.title)
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.body)
        layout.addStretch(1)

    def on_show(self, college: dict | None = None, **kwargs) -> None:
        if college is None:
            return
        self.title.setText(college["canonical_name"])
        clear_layout(self.body_layout)
        lang = preferred_language(self.ctx)
        from app.widgets.facts import KINDS
        from app.widgets.links import link_row

        sources = college.get("sources") or []
        if not sources:
            self.body_layout.addWidget(muted(words(lang, "Nothing from outside sources yet.", "अभी बाहरी स्रोतों से कुछ नहीं।")))
        for s in sources:
            kind = KINDS.get(s.get("kind"), ("", ""))[1 if lang == "hi" else 0]
            note = f"{s['publisher']} · {kind} · " + words(lang, "fetched ", "लिया गया ") + (s.get("retrieved_at") or "")[:10]
            self.body_layout.addWidget(link_row(s["document"], note, s["url"], self))
        card = Card()
        card.addWidget(muted(words(lang, "Official sources are used first; anything else is labelled. A value MAYA "
                                         "couldn't find is shown as not available — never guessed.",
                                   "पहले आधिकारिक स्रोत; बाक़ी पर निशान लगा होता है। जो MAYA को नहीं मिला, वह "
                                   "‘उपलब्ध नहीं’ दिखता है — अंदाज़ा कभी नहीं।")))
        self.body_layout.addWidget(card)
