"""My roadmap (spec §18–19, §31): stages top to bottom — Class 10 → Class 11 → Class 12 → Degree →
Specialisation → Internship → Career — the current one open with each step's ✓ / % / ○.

Up top: the focus career and the next step. Below the stages: what the time looks like
(this stage's work vs the hours left until March) and three changes the student can make
themselves — less time, a subject that's hard, a different focus. Each change makes a new
version and says what moved and why. Tap a step for why, how, when it's done, things to try (with
QR codes), and to mark it started or done. Nothing is ever deleted: old versions stay, and
"What changed" shows the latest changes.
"""

from __future__ import annotations

import calendar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import LANGUAGES, preferred_language, short_date
from app.pages.base import BasePage
from app.pages.directions import link_button, words
from app.widgets.common import (
    Card, clear_layout, error_label, ghost_button, heading, muted, primary_button, secondary_button, set_error, subtitle,
)
from app.widgets.links import link_row
from app.workers import run_async

MARK = {"done": "✓", "skipped": "–", "in_progress": "◐", "not_started": "○"}
COLOURS = {"done": "#15803d", "in_progress": "#4f46e5", "not_started": "#94a3b8", "skipped": "#94a3b8",
           "deferred": "#94a3b8", "parked": "#94a3b8"}
HOURS = (1, 2, 4, 6, 8, 10)
SUBJECTS = (("mathematics", "Maths", "मैथ्स"), ("physics", "Physics", "फ़िज़िक्स"), ("chemistry", "Chemistry", "केमिस्ट्री"),
            ("biology", "Biology", "बायोलॉजी"), ("english", "English", "अंग्रेज़ी"))
OPS = {"add": ("Added", "जोड़ा"), "defer": ("Moved later", "बाद के लिए रखा"), "park": ("Parked", "रोका"),
       "remove": ("Removed", "हटाया"), "resume": ("Back on", "फिर से शुरू"), "modify": ("Changed", "बदला")}


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n["children"])


def _months(window: dict | None) -> str:
    """{"from": "2026-10", "to": "2026-11"} → "Oct–Nov 2026"; across years "Dec 2026–Jan 2027"."""
    if not window:
        return ""
    (y1, m1), (y2, m2) = (map(int, window["from"].split("-")), map(int, window["to"].split("-")))
    a, b = calendar.month_abbr[m1], calendar.month_abbr[m2]
    if (y1, m1) == (y2, m2):
        return f"{a} {y1}"
    return f"{a}–{b} {y2}" if y1 == y2 else f"{a} {y1}–{b} {y2}"


def step_text(node: dict, lang: str) -> str:
    if node["state"] in ("deferred", "parked"):
        tag = words(lang, "later" if node["state"] == "deferred" else "parked", "बाद में" if node["state"] == "deferred" else "रुका हुआ")
        return f"{node['title'][lang]}  ({tag})"
    status = f"{node['percent']}%" if node["status"] == "in_progress" else MARK[node["status"]]
    when = _months(node["window"])
    return f"{status}  {node['title'][lang]}" + (f"   · {when}" if when else "")


class RoadmapPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("Your roadmap"))
        self.focus_line = subtitle("")
        layout.addWidget(self.focus_line)
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
        self.data: dict | None = None
        self.open_stages: set[str] = set()
        self.panel: str | None = None  # "time" | "hard" while choosing

    def set_language(self, code: str) -> None:
        self.ctx.assessment_language = code
        for c, button in self.language_buttons.items():
            button.setChecked(c == code)
        if self.data is not None:
            self._render(self.data)

    def on_show(self, returning: bool = False, **kwargs) -> None:
        self.set_language(preferred_language(self.ctx))
        if not returning:
            self.panel = None
        self.refresh()  # also when coming back: a step may have changed on its own page

    def refresh(self) -> None:
        set_error(self.error, None)
        if self.data is None:
            clear_layout(self.body_layout)
            self.body_layout.addWidget(muted("Building your roadmap…"))
        run_async(api_client.roadmap, on_success=self._render, on_error=self._failed)

    # ---------------- the page ----------------

    def _render(self, data: dict) -> None:
        self.data = data
        lang = preferred_language(self.ctx)
        if not self.open_stages:
            self.open_stages = {data["current_stage"]}
        clear_layout(self.body_layout)
        focus = data.get("focus")
        if focus:
            line = words(lang, f"Focus: {focus['name']['en']}", f"लक्ष्य: {focus['name']['hi']}")
            if data["branches"]:
                line += words(lang, " · also exploring ", " · साथ में खोज: ") + ", ".join(b["name"][lang] for b in data["branches"])
        else:
            line = words(lang, "No focus career yet — your roadmap covers the basics and exploring.",
                         "अभी कोई लक्ष्य करियर नहीं — रोडमैप में बुनियादी बातें और खोज है।")
        self.focus_line.setText(line + words(lang, f" · {data['completion']}% done", f" · {data['completion']}% पूरा"))

        self._next_step(data, lang)
        if data["version"] > 1 and data["changes"]:
            changed = ghost_button(words(lang, f"What changed in version {data['version']}", f"संस्करण {data['version']} में क्या बदला"))
            changed.clicked.connect(lambda: self.ctx.navigate("roadmap_changes"))
            self.body_layout.addWidget(changed)
        for stage in data["stages"]:
            self._stage(stage, lang, stage["stage"] == data["current_stage"])
        self._time(data, lang)
        if any(n["attrs"].get("study_plan") for n in _walk(data["stages"])):
            plan = secondary_button(words(lang, "Open my exam study plan", "मेरा परीक्षा स्टडी प्लान खोलें"))
            plan.clicked.connect(lambda: self.ctx.navigate("study_plan"))
            self.body_layout.addWidget(plan)
        mine = secondary_button(words(lang, "My progress", "मेरी प्रगति"))
        mine.clicked.connect(lambda: self.ctx.navigate("progress"))
        self.body_layout.addWidget(mine)

    def _next_step(self, data: dict, lang: str) -> None:
        step = data.get("next_step")
        card = Card()
        if step is None:
            card.addWidget(heading(words(lang, "Nothing waiting right now — well done.", "अभी कुछ बाक़ी नहीं — शाबाश।")))
            self.body_layout.addWidget(card)
            return
        card.addWidget(muted(words(lang, "Next step", "अगला कदम") + (words(lang, " · overdue", " · समय निकल गया") if step["overdue"] else "")))
        card.addWidget(heading(step["title"][lang]))
        why = (step.get("detail") or {}).get("why")
        if why:
            card.addWidget(muted(why[lang]))
        row = QHBoxLayout()
        open_btn = primary_button(words(lang, "Open", "खोलें"))
        open_btn.clicked.connect(lambda: self._open(step["node_key"]))
        row.addWidget(open_btn)
        done = secondary_button(words(lang, "Mark done", "पूरा हुआ"))
        done.clicked.connect(lambda: self._update(step["node_key"], "done"))
        row.addWidget(done)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        card.addWidget(holder)
        self.body_layout.addWidget(card)

    def _stage(self, stage: dict, lang: str, current: bool) -> None:
        opened = stage["stage"] in self.open_stages
        header = QPushButton()
        header.setProperty("variant", "option")
        header.setCursor(Qt.PointingHandCursor)
        header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        inner = QHBoxLayout(header)
        inner.setContentsMargins(12, 8, 12, 8)
        title = QLabel(("▾  " if opened else "▸  ") + stage["title"][lang].upper()
                       + (words(lang, "  · now", "  · अभी") if current else ""))
        title.setStyleSheet("background: transparent; font-weight: 800;")
        inner.addWidget(title, 1)
        detail = QLabel(f"{stage['percent']}%" if stage.get("work") else _months(stage["window"]))
        detail.setStyleSheet("background: transparent; color: #4f46e5; font-weight: 700;")
        inner.addWidget(detail)
        for label in header.findChildren(QLabel):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        header.setMinimumHeight(44)
        header.clicked.connect(lambda _c=False, s=stage["stage"]: self._toggle(s))
        self.body_layout.addWidget(header)
        if not opened:
            return
        for milestone in stage["children"]:
            if milestone["kind"] in ("milestone", "branch"):
                self._milestone(milestone, lang)

    def _milestone(self, milestone: dict, lang: str) -> None:
        card = Card()
        title = milestone["title"][lang] + (f"  ·  {milestone['percent']}%" if milestone.get("work") else "")
        label = heading(title)
        if milestone["state"] == "parked":
            label.setStyleSheet("color: #94a3b8;")
        card.addWidget(label)
        steps = [c for c in milestone["children"] if c["kind"] in ("module", "task")]
        if not steps and milestone.get("detail", {}).get("why"):
            card.addWidget(muted(milestone["detail"]["why"][lang]))
        for step in steps:
            button = link_button(step_text(step, lang))
            colour = COLOURS[step["state"]] if step["state"] != "active" else COLOURS[step["status"]]
            if step["state"] != "active" or step["status"] == "done":
                button.findChild(QLabel).setStyleSheet(f"background: transparent; color: {colour}; font-weight: 600;")
            button.clicked.connect(lambda _c=False, k=step["node_key"]: self._open(k))
            card.addWidget(button)
        self.body_layout.addWidget(card)

    def _time(self, data: dict, lang: str) -> None:
        card = Card()
        card.addWidget(heading(words(lang, "Your time", "आपका समय")))
        time = data["time"]
        line = words(lang, f"This stage still has about {time['hours_needed']} hours of work; at {data['hours_per_week']} "
                           f"hours a week you have about {time['hours_available']} until March.",
                     f"इस चरण में लगभग {time['hours_needed']} घंटे का काम बाक़ी है; हफ़्ते के {data['hours_per_week']} घंटों से "
                     f"मार्च तक लगभग {time['hours_available']} घंटे हैं।")
        card.addWidget(muted(line))
        row = QHBoxLayout()
        for key, en, hi in (("time", "I have less (or more) time", "मेरा समय कम/ज़्यादा है"),
                            ("hard", "Something's hard", "कुछ मुश्किल है")):
            button = secondary_button(words(lang, en, hi))
            button.clicked.connect(lambda _c=False, k=key: self._panel(k))
            row.addWidget(button)
        change = secondary_button(words(lang, "Change focus", "लक्ष्य बदलें"))
        change.clicked.connect(lambda: self.ctx.navigate("directions"))
        row.addWidget(change)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        card.addWidget(holder)
        if self.panel == "time":
            card.addWidget(muted(words(lang, "Hours a week for your roadmap, on top of school:",
                                       "स्कूल के अलावा, रोडमैप के लिए हफ़्ते में कितने घंटे:")))
            card.addWidget(self._chips([(str(h), str(h)) for h in HOURS],
                                       lambda h: self._adapt("time_budget", hours_per_week=int(h), detail=f"{h} hours a week")))
        elif self.panel == "hard":
            card.addWidget(muted(words(lang, "Which subject feels hard? A foundation step goes in before everything that "
                                             "builds on it.", "कौन सा विषय मुश्किल लगता है? उस पर टिकी हर चीज़ से पहले एक "
                                                             "बुनियादी कदम जुड़ेगा।")))
            card.addWidget(self._chips([(key, en if lang == "en" else hi) for key, en, hi in SUBJECTS],
                                       lambda s: self._adapt("difficulty", subject=s, detail=f"{s} feels hard")))
        self.body_layout.addWidget(card)

    def _chips(self, options: list[tuple[str, str]], action) -> QWidget:
        row = QHBoxLayout()
        for value, label in options:
            button = secondary_button(label)
            button.clicked.connect(lambda _c=False, v=value: action(v))
            row.addWidget(button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        return holder

    # ---------------- actions ----------------

    def _toggle(self, stage: str) -> None:
        self.open_stages ^= {stage}
        self._render(self.data)

    def _panel(self, which: str) -> None:
        self.panel = None if self.panel == which else which
        self._render(self.data)

    def _adapt(self, kind: str, **detail) -> None:
        self.panel = None
        run_async(api_client.roadmap_recalculate, kind, **detail,
                  on_success=lambda result: self._adapted(result), on_error=self._failed)

    def _adapted(self, result: dict) -> None:
        if result.get("changed"):
            self.ctx.navigate("roadmap_changes")
        else:
            self.refresh()

    def _update(self, key: str, status: str) -> None:
        run_async(api_client.progress_update, key, status, on_success=self._render, on_error=self._failed)

    def _open(self, key: str) -> None:
        nodes = {n["node_key"]: n for n in _walk(self.data["stages"])}
        if key in nodes:
            self.ctx.navigate("roadmap_node", node=nodes[key], names={k: n["title"] for k, n in nodes.items()})

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")


class RoadmapNodePage(BasePage):
    """One step: why, how, when it's done, things to try, and the student's own progress on it."""

    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        self.title = heading("")
        layout.addWidget(self.title)
        self.status = subtitle("")
        layout.addWidget(self.status)
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)
        self.node: dict | None = None
        self.names: dict = {}

    def on_show(self, node: dict | None = None, names: dict | None = None, returning: bool = False, **kwargs) -> None:
        if node is not None:
            self.node, self.names = node, names or {}
        if self.node is not None:
            self._render(self.node)

    def _render(self, node: dict) -> None:
        lang = preferred_language(self.ctx)
        detail = node.get("detail") or {}
        clear_layout(self.body_layout)
        set_error(self.error, None)
        self.title.setText(node["title"][lang])
        status = {"done": ("Done", "पूरा"), "in_progress": ("In progress", "चल रहा है"),
                  "not_started": ("Not started", "शुरू नहीं"), "skipped": ("Skipped", "छोड़ा")}[node["status"]]
        when = _months(node.get("window"))
        self.status.setText(words(lang, *status) + (f" · {when}" if when else "")
                            + (f" · {words(lang, 'about', 'लगभग')} {node['est_hours']:g} h" if node.get("est_hours") else ""))
        reason = (node.get("attrs") or {}).get("reason")
        if node["state"] != "active" or reason:
            self.body_layout.addWidget(muted((reason or {}).get(lang) or words(lang, "Parked for now.", "अभी रोका गया है।")))
        for key, en, hi in (("why", "Why", "क्यों"), ("done_when", "Done when", "कब पूरा")):
            if detail.get(key):
                card = Card()
                card.addWidget(heading(words(lang, en, hi)))
                label = QLabel(detail[key][lang])
                label.setWordWrap(True)
                card.addWidget(label)
                self.body_layout.addWidget(card)
        how = detail.get("how") or []
        if how:
            card = Card()
            card.addWidget(heading(words(lang, "Things to try", "आज़माने के लिए")))
            for item in how:
                label = QLabel("•  " + (item[lang] if isinstance(item, dict) else item))
                label.setWordWrap(True)
                card.addWidget(label)
            for resource in detail.get("resources") or []:
                if resource.get("url"):
                    card.addWidget(link_row(resource["name"][lang] if isinstance(resource["name"], dict) else resource["name"],
                                            "", resource["url"], self))
            self.body_layout.addWidget(card)
        waiting = [self.names.get(p, {}).get(lang, p) for p in node.get("prerequisites") or []]
        if waiting:
            self.body_layout.addWidget(muted(words(lang, "Builds on: ", "इस पर टिका है: ") + ", ".join(waiting)))
        if node.get("evidence"):
            e = node["evidence"][-1]
            says = (e.get("says") or {}).get(lang) or e.get("note") or ""
            source = {"self": ("you marked it", "आपने मार्क किया"), "assessment": ("from an assessment", "आकलन से"),
                      "focus": ("you chose your focus", "आपने लक्ष्य चुना")}.get(e.get("kind"), (e.get("kind", ""), e.get("kind", "")))
            self.body_layout.addWidget(muted(words(lang, *source) + (f": {says}" if says else "")))
        self._actions(node, lang)

    def _actions(self, node: dict, lang: str) -> None:
        if node["kind"] not in ("module", "task") or node["state"] != "active":
            return
        row = QHBoxLayout()
        for status, en, hi in (("in_progress", "Started", "शुरू किया"), ("done", "Done", "पूरा हुआ"),
                               ("not_started", "Not yet", "अभी नहीं")):
            if status == node["status"]:
                continue
            button = primary_button(words(lang, en, hi)) if status == "done" else secondary_button(words(lang, en, hi))
            button.clicked.connect(lambda _c=False, s=status: self._set(s))
            row.addWidget(button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.body_layout.addWidget(holder)
        attrs = node.get("attrs") or {}
        if attrs.get("instrument"):
            go = secondary_button(words(lang, "Take it now", "अभी दें"))
            go.clicked.connect(lambda: self.ctx.navigate("assessment_run", key=attrs["instrument"], language=lang))
            self.body_layout.addWidget(go)
        link = {"streams": ("See what each stream keeps open", "हर स्ट्रीम क्या खुला रखती है, देखें"),
                "careers": ("Explore careers", "करियर देखें"), "colleges": ("Explore colleges", "कॉलेज देखें")}.get(attrs.get("link"))
        if link:
            go = secondary_button(words(lang, *link))
            go.clicked.connect(lambda: self.ctx.navigate(attrs["link"]))
            self.body_layout.addWidget(go)
        if attrs.get("study_plan"):
            plan = secondary_button(words(lang, "Open my exam study plan", "मेरा परीक्षा स्टडी प्लान खोलें"))
            plan.clicked.connect(lambda: self.ctx.navigate("study_plan"))
            self.body_layout.addWidget(plan)
        ask = ghost_button(words(lang, "Ask MAYA about this", "MAYA से इसके बारे में पूछें"))
        question = words(lang, f"Help me with this step of my roadmap: {node['title']['en']}",
                         f"मेरे रोडमैप के इस कदम में मदद करो: {node['title']['hi']}")
        ask.clicked.connect(lambda: self.ctx.navigate("maya", ask=question))
        self.body_layout.addWidget(ask)

    def _set(self, status: str) -> None:
        run_async(api_client.progress_update, self.node["node_key"], status,
                  on_success=self._updated, on_error=self._failed)

    def _updated(self, view: dict) -> None:
        nodes = {n["node_key"]: n for n in _walk(view["stages"])}
        self.node = nodes.get(self.node["node_key"], self.node)
        self._render(self.node)

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")


class RoadmapChangesPage(BasePage):
    """What the latest version changed and why — and every version so far."""

    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        self.title = heading("What changed")
        layout.addWidget(self.title)
        layout.addWidget(subtitle("Finished steps still count, and every earlier version is kept."))
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        back = primary_button("Back to my roadmap")
        back.clicked.connect(lambda: self.ctx.navigate("roadmap"))
        layout.addWidget(back)
        layout.addStretch(1)

    def on_show(self, **kwargs) -> None:
        set_error(self.error, None)
        clear_layout(self.body_layout)
        run_async(lambda: (api_client.roadmap(), api_client.roadmap_versions()), on_success=self._render, on_error=self._failed)

    def _render(self, result: tuple) -> None:
        data, versions = result
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        self.title.setText(words(lang, f"What changed in version {data['version']}", f"संस्करण {data['version']} में क्या बदला"))
        grouped: dict[str, list] = {}
        for change in data["changes"]:
            if change["node_key"].split(":")[0] in ("module", "task", "branch"):
                grouped.setdefault(change["op"], []).append(change)
        rescheduled = len(grouped.pop("modify", []))
        for op in ("add", "defer", "park", "resume", "remove"):
            if op not in grouped:
                continue
            card = Card()
            card.addWidget(heading(words(lang, *OPS[op])))
            for change in grouped[op]:
                label = QLabel(f"•  {(change['title'] or {}).get(lang, change['node_key'])} — {change['reason'][lang]}")
                label.setWordWrap(True)
                card.addWidget(label)
            self.body_layout.addWidget(card)
        if rescheduled:
            self.body_layout.addWidget(muted(words(lang, f"{rescheduled} other steps moved to new months.",
                                                   f"{rescheduled} दूसरे कदम नए महीनों में गए।")))
        if not grouped and not rescheduled:
            self.body_layout.addWidget(muted(words(lang, "This is your first version.", "यह आपका पहला संस्करण है।")))
        card = Card()
        card.addWidget(heading(words(lang, "All versions", "सभी संस्करण")))
        for v in reversed(versions):
            reason = (v.get("rationale") or {}).get(lang, "")
            label = QLabel(f"{v['version']}.  {short_date(v.get('created_at'))} — {reason}")
            label.setWordWrap(True)
            card.addWidget(label)
        self.body_layout.addWidget(card)

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
