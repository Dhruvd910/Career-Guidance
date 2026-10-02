"""Building a roadmap tree from a student's inputs (spec §18, docs/design/14-phase5-plan.md).

Deterministic: the same inputs give the same tree.
- **Templates:** the stage templates give the spine of the current stage and the stages after it.
- **The career graph:** fills each slot from the focus career — its skills split into foundations,
  entry-level and advanced, in prerequisite order; the projects that build them; its exams,
  degrees and colleges.
- **Rules:** add the rest —
  - a foundation module before anything that builds on a subject the student finds hard (said
    or measured)
  - an exploration branch for each career being explored
  - "parked" for what only a dropped career needed — never silently removed
  - deferral of optional work when the weekly time can't fit it

Months, not dates: the current stage runs to the end of the academic year (March), and later
stages follow the school and degree calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.knowledge.graph_store import GraphStore
from app.roadmap.templates import Milestone, templates

HOURS = {"foundation": 15, "technical": 30, "clinical": 30, "creative": 20, "people": 12}
CURIOSITY_MAX, PROJECTS_MAX, EXPLORE_MAX = 2, 3, 3
SUBJECT_SKILLS = {
    "mathematics": "skill:school_mathematics", "physics": "skill:physics_fundamentals",
    "chemistry": "skill:chemistry_fundamentals", "biology": "skill:biology_fundamentals",
    "english": "skill:english_communication", "accountancy": "skill:accounting",
    "economics": "skill:economics_concepts",
}
SUBJECT_NAMES = {"mathematics": ("Maths", "मैथ्स"), "physics": ("Physics", "फ़िज़िक्स"),
                 "chemistry": ("Chemistry", "केमिस्ट्री"), "biology": ("Biology", "बायोलॉजी"),
                 "english": ("English", "अंग्रेज़ी"), "accountancy": ("Accountancy", "अकाउंटेंसी"),
                 "economics": ("Economics", "अर्थशास्त्र")}
GAP = 0.55
REPEATABLE = {"projects", "skill_development", "advanced_skills", "subject_foundation"}  # slots used more than once
STRONG = 0.7
STUDY_PLAN_EXAMS = {"JEE_MAIN", "JEE_ADVANCED", "NEET_UG"}
INSTRUMENTS_BY_BAND = {"class_6_8": ["interests"], "class_9_10": ["interests", "aptitude", "skills", "academic"]}
INSTRUMENT_TITLES = {"interests": ("What you enjoy", "आपको क्या पसंद है"), "aptitude": ("Thinking skills", "सोचने की क्षमता"),
                     "skills": ("Your skills", "आपके हुनर"), "academic": ("Your marks", "आपके अंक"),
                     "coding_check": ("Coding check", "कोडिंग जाँच")}


def t(en: str, hi: str) -> dict:
    return {"en": en, "hi": hi}


def hours_phrase(n: float) -> str:
    """'1 hour', '2 hours'."""
    return f"{n:g} hour" + ("" if n == 1 else "s")


@dataclass
class Inputs:
    """What a roadmap is built from (spec §18) — stored with every version."""

    class_level: int
    education_stage: str | None = None
    stream: str | None = None
    board: str | None = None
    state: str | None = None
    hours_per_week: int = 4
    focus: str | None = None  # career key, e.g. "ai_data"
    branches: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    difficulties: list[str] = field(default_factory=list)  # subjects the student said are hard
    measured: dict[str, dict] = field(default_factory=dict)  # graph skill → {value, says, dimension}
    directions: list[str] = field(default_factory=list)  # top careers from the assessments, best first
    assessments_done: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    shortlisted: int = 0  # colleges the student has shortlisted (Phase 7)
    month: str = ""  # "2026-10" — when it was built

    def snapshot(self) -> dict:
        return {k: (sorted(v) if isinstance(v, (set,)) else v) for k, v in self.__dict__.items()}


def band_for(inputs: Inputs) -> str:
    stage = inputs.education_stage or ""
    if stage == "dropper":
        return "dropper"
    if stage.startswith("ug") or stage in ("pg", "graduate"):
        return "college"
    if inputs.class_level <= 8:
        return "class_6_8"
    return "class_9_10" if inputs.class_level <= 10 else "class_11_12"


# ---------------- months ----------------

def _month(d: date) -> tuple[int, int]:
    return d.year, d.month


def _add(ym: tuple[int, int], months: int) -> tuple[int, int]:
    y, m = ym
    total = y * 12 + (m - 1) + months
    return total // 12, total % 12 + 1


def _fmt(ym: tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def _academic_end(ym: tuple[int, int]) -> tuple[int, int]:
    """The March that ends the academic year this month belongs to."""
    y, m = ym
    return (y + 1, 3) if m >= 4 else (y, 3)


# ---------------- building ----------------

class Builder:
    def __init__(self, store: GraphStore, inputs: Inputs, today: date):
        self.store, self.inputs, self.today = store, inputs, today
        self.tpl = templates()
        self.band = band_for(inputs)
        self.nodes: dict[str, dict] = {}
        self.filled: set[str] = set()
        self.focus_key = f"career:{inputs.focus}" if inputs.focus else None
        self.focus_name = (store.node(self.focus_key) or {}).get("name") if self.focus_key else None
        self.buckets = self._skill_buckets(self.focus_key) if self.focus_key else {"foundation": [], "entry": [], "advanced": []}
        self.routes = store.pathways(self.focus_key) if self.focus_key else None
        self.merged: dict[str, str] = {}  # skill → the foundation module that covers it

    # -- nodes --

    def add(self, key: str, parent: str | None, kind: str, stage: str, title: dict, **kw) -> dict | None:
        if key in self.nodes:
            return None  # first placement wins: a skill appears once
        node = {"node_key": key, "parent_key": parent, "kind": kind, "stage": stage, "title": title,
                "detail": kw.get("detail", {}), "prerequisites": list(kw.get("prerequisites", [])),
                "est_hours": kw.get("hours"), "window": None, "kg_refs": list(kw.get("kg_refs", [])),
                "state": kw.get("state", "active"), "attrs": dict(kw.get("attrs", {}))}
        self.nodes[key] = node
        return node

    # -- the focus career's skills --

    def _skill_buckets(self, career: str) -> dict[str, list[dict]]:
        required = {s["key"]: s for s in self.store.skills_for(career)}
        buckets = {"foundation": [], "entry": [], "advanced": []}
        kinds = {}
        for step in self.store.prerequisite_path(list(required)):
            node = self.store.node(step["key"]) or {}
            kind = node.get("attrs", {}).get("kind", "technical")
            kinds[step["key"]] = kind
            entry = all(kinds.get(p) == "foundation" for p in step["needs"])
            info = {**step, "kind": kind, "required": required.get(step["key"]),
                    "measured_by": node.get("attrs", {}).get("measured_by", []),
                    "from_class": node.get("attrs", {}).get("from_class", 0)}
            bucket = "foundation" if kind == "foundation" else "entry" if entry else "advanced"
            buckets[bucket].append(info)
        return buckets

    @staticmethod
    def stage_class(stage: str) -> int:
        """class_10 → 10; anything after school → 13."""
        return int(stage.split("_")[1]) if stage.startswith("class_") else 13

    def _take(self, bucket: str, limit: int | None = None, stage: str | None = None) -> list[dict]:
        """Skills of a bucket not yet placed — and not before the class they're usually met in."""
        upto = self.stage_class(stage) if stage else 13
        taken = [s for s in self.buckets[bucket] if f"module:skill:{s['key'].split(':', 1)[1]}" not in self.nodes
                 and s["key"] not in self.merged and s.get("from_class", 0) <= upto]
        return taken[:limit] if limit else taken

    def _skill_module(self, skill: dict, parent: str, stage: str, optional: bool = False, career_name=None) -> None:
        if skill["key"] in self.merged:
            return  # its foundation module covers it
        key = f"module:skill:{skill['key'].split(':', 1)[1]}"
        name = skill["name"]
        career_name = career_name or self.focus_name
        required = skill.get("required")
        if required and career_name:
            why = t(f"{career_name['en']} needs {name['en'].lower()} ({required.get('level') or 'some'} level).",
                    f"{career_name['hi']} में {name['hi']} की ज़रूरत है।")
        else:
            why = t(f"It's a foundation for what comes next in your roadmap.", "यह आपके रोडमैप में आगे आने वाली चीज़ों की बुनियाद है।")
        builds = self.store.developed_by(skill["key"])
        done = t("You've done one of the things to try and can use it on your own"
                 + (" — or an assessment shows it as a strength." if skill.get("measured_by") else "."),
                 "आपने आज़माने वाली चीज़ों में से एक पूरी की है और इसे ख़ुद इस्तेमाल कर सकते हैं"
                 + (" — या किसी आकलन में यह आपकी ताक़त निकली है।" if skill.get("measured_by") else "।"))
        self.add(key, parent, "module", stage, name,
                 detail={"why": why, "how": [b["name"] for b in builds],
                         "resources": [{"name": b["name"], "url": b["attrs"].get("url"), "free": b["attrs"].get("free")}
                                       for b in builds if b["attrs"].get("url")],
                         "done_when": done},
                 prerequisites=[self.merged.get(p, f"module:skill:{p.split(':', 1)[1]}") for p in skill.get("needs", [])],
                 hours=HOURS.get(skill.get("kind"), 20), kg_refs=[skill["key"]] + ([self.focus_key] if self.focus_key else []),
                 attrs={"optional": optional, "skill": skill["key"], "measured_by": skill.get("measured_by", [])})

    # -- slots --

    def fill(self, slot: str | None, milestone: Milestone, parent: str, stage: str) -> None:
        if slot is None:
            return
        if slot in self.filled and slot not in REPEATABLE:
            return
        self.filled.add(slot)
        getattr(self, f"_slot_{slot}")(milestone, parent, stage)

    def _slot_assessments(self, m: Milestone, parent: str, stage: str) -> None:
        for key in INSTRUMENTS_BY_BAND.get(self.band, ["interests"]):
            en, hi = INSTRUMENT_TITLES[key]
            self.add(f"task:assessment:{key}", parent, "task", stage, t(en, hi), hours=1 if key != "aptitude" else 0.5,
                     detail={"why": m.why.model_dump() if m.why else {}, "done_when": t("You've taken it once.", "आपने इसे एक बार दे दिया है।")},
                     attrs={"auto": "assessment", "instrument": key})

    def _slot_subject_foundation(self, m: Milestone, parent: str, stage: str) -> None:
        node = self.store.node(m.subject_skill) or {}
        builds = self.store.developed_by(m.subject_skill)
        key = f"module:skill:{m.subject_skill.split(':', 1)[1]}"
        self.add(key, parent, "module", stage, m.title.model_dump(),
                 detail={"why": m.why.model_dump() if m.why else {}, "how": [b["name"] for b in builds],
                         "resources": [{"name": b["name"], "url": b["attrs"].get("url"), "free": b["attrs"].get("free")}
                                       for b in builds if b["attrs"].get("url")],
                         "done_when": t("You've done one of the things to try.", "आपने आज़माने वाली चीज़ों में से एक कर ली है।")},
                 hours=HOURS.get(node.get("attrs", {}).get("kind"), 15), kg_refs=[m.subject_skill],
                 attrs={"optional": m.optional, "skill": m.subject_skill,
                        "measured_by": node.get("attrs", {}).get("measured_by", [])})

    def _slot_foundation_skills(self, m: Milestone, parent: str, stage: str) -> None:
        if not self.focus_key:
            self.add("module:basics", parent, "module", stage, t("Keep your basics strong", "अपनी बुनियाद मज़बूत रखिए"),
                     detail={"why": t("Maths, science and English keep the most careers open.",
                                      "मैथ्स, विज्ञान और अंग्रेज़ी सबसे ज़्यादा करियर खुले रखते हैं।"),
                             "done_when": t("Your marks in these are steady or rising.", "इनमें आपके अंक स्थिर हैं या बढ़ रहे हैं।")},
                     hours=15)
            return
        for skill in self._take("foundation", stage=stage):
            self._skill_module(skill, parent, stage)

    def _slot_curiosity(self, m: Milestone, parent: str, stage: str) -> None:
        for skill in self._take("entry", CURIOSITY_MAX, stage=stage):
            self._skill_module(skill, parent, stage, optional=True)

    def _slot_skill_development(self, m: Milestone, parent: str, stage: str) -> None:
        if not self.focus_key:
            return
        foundations = self._take("foundation", stage=stage)
        if self.band == "college":  # at college, a foundation only if it was measured weak
            foundations = [f for f in foundations if self.inputs.measured.get(f["key"], {}).get("value", 1) < GAP]
        skills = foundations + self._take("entry", stage=stage)
        if self.band == "college" or stage == "degree":
            skills += self._take("advanced", stage=stage)
        for skill in skills:
            self._skill_module(skill, parent, stage)

    def _slot_advanced_skills(self, m: Milestone, parent: str, stage: str) -> None:
        for skill in self._take("foundation", stage=stage) + self._take("entry", stage=stage) + self._take("advanced", stage=stage):
            self._skill_module(skill, parent, stage)

    def _slot_projects(self, m: Milestone, parent: str, stage: str) -> None:
        # The field's own skills first (coding for AI), then the foundations.
        placed = [n for n in self.nodes.values() if n["stage"] == stage and n["attrs"].get("skill") and n["state"] == "active"]
        kinds = {n["attrs"]["skill"]: (self.store.node(n["attrs"]["skill"]) or {}).get("attrs", {}).get("kind") for n in placed}
        rank = {"technical": 0, "clinical": 0, "creative": 0, "people": 1, "foundation": 2}
        skills = sorted((n["attrs"]["skill"] for n in placed), key=lambda k: rank.get(kinds.get(k), 1))
        seen, count = set(), 0
        for skill in skills:
            for b in self.store.developed_by(skill):
                if b["type"] != "project" or b["key"] in seen or (b["attrs"].get("level") or 1) > 2:
                    continue
                seen.add(b["key"])
                key = f"task:{b['key']}"
                if key in self.nodes:
                    continue
                skill_name = (self.store.node(skill) or {}).get("name", t(skill, skill))
                self.add(key, parent, "task", stage, b["name"], hours=b["attrs"].get("hours", 8),
                         detail={"why": t(f"Builds {skill_name['en'].lower()}.", f"इससे {skill_name['hi']} बनता है।"),
                                 "done_when": t("You've finished it and can show someone what you made.",
                                                "आपने इसे पूरा कर लिया है और किसी को दिखा सकते हैं।"),
                                 "resources": [{"name": b["name"], "url": b["attrs"]["url"]}] if b["attrs"].get("url") else []},
                         kg_refs=[b["key"], skill], attrs={"optional": count > 0, "project": b["key"]})
                count += 1
                if count >= PROJECTS_MAX:
                    return

    def _slot_career_exploration(self, m: Milestone, parent: str, stage: str) -> None:
        careers = ([self.inputs.focus] + self.inputs.branches) if self.inputs.focus else self.inputs.directions[:EXPLORE_MAX]
        if not careers:
            self.add("task:explore:by_area", parent, "task", stage, t("Explore careers by area", "क्षेत्र के हिसाब से करियर देखिए"),
                     detail={"why": m.why.model_dump() if m.why else {},
                             "done_when": t("You've read about at least three careers.", "आपने कम से कम तीन करियर के बारे में पढ़ा है।")},
                     hours=2, attrs={"link": "careers"})
            return
        from app.assessment.alignment import career_needs

        for career in careers:
            self._explore_task(f"task:explore:{career}", career, parent, stage, career_needs())

    def _explore_task(self, key: str, career: str, parent: str, stage: str, needs: dict) -> None:
        node = self.store.node(f"career:{career}")
        if node is None:
            return
        top = self.store.skills_for(f"career:{career}")
        project = next((b for s in top for b in self.store.developed_by(s["key"]) if b["type"] == "project"), None)
        ask = (needs["careers"].get(career, {}).get("ask_yourself") or [None])[0]
        how = ([project["name"]] if project else []) + ([ask] if ask else [])
        self.add(key, parent, "task", stage, t(f"Explore {node['name']['en']}", f"{node['name']['hi']} को जानिए"),
                 detail={"why": t("Try a little of it before deciding.", "फ़ैसला करने से पहले इसे थोड़ा आज़माइए।"), "how": how,
                         "done_when": t("You've tried the project or talked to someone who does this work.",
                                        "आपने प्रोजेक्ट आज़माया है या इस काम को करने वाले किसी से बात की है।")},
                 hours=6, kg_refs=[f"career:{career}"] + ([project["key"]] if project else []), attrs={"career": career})

    def _first_route(self) -> dict | None:
        if not self.routes:
            return None
        return (self.routes["common"] or self.routes["alternative"] or [None])[0]

    def _slot_stream_choice(self, m: Milestone, parent: str, stage: str) -> None:
        route = self._first_route()
        if route and route["streams"]:
            names = [s["name"] for s in route["streams"]]
            title = t(f"Choose a stream that keeps {self.focus_name['en']} open",
                      f"ऐसी स्ट्रीम चुनिए जो {self.focus_name['hi']} का रास्ता खुला रखे")
            how = names + [{"en": f"…or {s['name']['en']} if you add {', '.join(x.split(':')[1] for x in s['if_you_add'])}",
                            "hi": f"…या {s['name']['hi']}"} for s in route["streams"] if s["if_you_add"]]
            how = [n for n in names] + [h for h in how if h not in names]
        else:
            title = t("Choose your class 11 stream", "11वीं की स्ट्रीम चुनिए")
            how = []
        self.add("module:stream_choice", parent, "module", stage, title,
                 detail={"why": m.why.model_dump() if m.why else t("The stream decides which degrees stay open.",
                                                                    "स्ट्रीम तय करती है कि कौन सी डिग्रियाँ खुली रहेंगी।"),
                         "how": how, "done_when": t("You've chosen your class 11 stream.", "आपने 11वीं की स्ट्रीम चुन ली है।")},
                 hours=3, attrs={"link": "streams"}, kg_refs=[s["key"] for s in (route or {}).get("streams", [])])

    def _slot_planning(self, m: Milestone, parent: str, stage: str) -> None:
        route = self._first_route()
        how = []
        if route:
            how.append(t("Subjects: " + ", ".join(s["name"]["en"] for s in route["subjects"]["mandatory"]),
                         "विषय: " + ", ".join(s["name"]["hi"] for s in route["subjects"]["mandatory"])))
            if route["exams"]:
                how.append(t("Exams ahead (usually in class 12): " + ", ".join(e["name"]["en"] for e in route["exams"][:3]),
                             "आगे की परीक्षाएँ (आम तौर पर 12वीं में): " + ", ".join(e["name"]["hi"] for e in route["exams"][:3])))
            if any(e["key"].split(":")[1] in STUDY_PLAN_EXAMS for e in route["exams"]):
                how.append(t("MAYA's chapter-by-chapter study plan starts in class 11.",
                              "MAYA का अध्याय-दर-अध्याय स्टडी प्लान 11वीं में शुरू होता है।"))
        self.add("module:planning_11_12", parent, "module", stage, m.title.model_dump(),
                 detail={"why": m.why.model_dump() if m.why else {}, "how": how,
                         "done_when": t("You know your subjects and the exams ahead.", "आप अपने विषय और आगे की परीक्षाएँ जानते हैं।")},
                 hours=2)

    def _slot_career_decision(self, m: Milestone, parent: str, stage: str) -> None:
        title = (t(f"Your focus: {self.focus_name['en']}", f"आपका लक्ष्य: {self.focus_name['hi']}") if self.focus_name
                 else t("Choose a direction to focus on", "ध्यान देने के लिए एक दिशा चुनिए"))
        self.add("task:career_decision", parent, "task", stage, title,
                 detail={"why": m.why.model_dump() if m.why else {},
                         "done_when": t("You've chosen a focus (you can change it later).",
                                        "आपने एक लक्ष्य चुन लिया है (बाद में बदल सकते हैं)।")},
                 hours=2, attrs={"auto": "focus"})

    def _slot_entrance_exams(self, m: Milestone, parent: str, stage: str) -> None:
        route = self._first_route()
        if route is None:
            self.add("module:exams_after_focus", parent, "module", stage,
                     t("Entrance exams — after you choose a direction", "प्रवेश परीक्षाएँ — दिशा चुनने के बाद"),
                     detail={"why": t("Which exams matter depends on the direction.", "कौन सी परीक्षा ज़रूरी है, यह दिशा पर निर्भर है।"),
                             "done_when": t("You've chosen a focus.", "आपने एक लक्ष्य चुन लिया है।")}, hours=1)
            return
        exams = route["exams"] + (self.routes.get("career_exams") or [])
        for exam in exams:
            code = exam["key"].split(":", 1)[1]
            self.add(f"module:exam:{code}", parent, "module", stage, exam["name"],
                     detail={"why": t(f"It leads to {route['degree']['name']['en']}.", f"यह {route['degree']['name']['hi']} तक ले जाती है।"),
                             "resources": [{"name": exam["name"], "url": exam["url"]}] if exam.get("url") else [],
                             "done_when": t("You've appeared for it, prepared with mock tests.",
                                            "आपने मॉक टेस्ट से तैयारी करके परीक्षा दी है।")},
                     hours=40, kg_refs=[exam["key"]],
                     attrs={"exam_critical": True, "study_plan": code in STUDY_PLAN_EXAMS, "exam": code})

    def _slot_degree_selection(self, m: Milestone, parent: str, stage: str) -> None:
        route = self._first_route()
        if route is None:
            self.add("module:degree_after_focus", parent, "module", stage,
                     t("Degree — after you choose a direction", "डिग्री — दिशा चुनने के बाद"),
                     detail={"done_when": t("You've chosen a focus.", "आपने एक लक्ष्य चुन लिया है।")}, hours=1)
            return
        degree = route["degree"]
        self.add(f"module:degree:{degree['key'].split(':', 1)[1]}", parent, "module", stage, degree["name"],
                 detail={"why": t(f"The usual route into {self.focus_name['en']}.", f"{self.focus_name['hi']} का आम रास्ता।"),
                         "done_when": t("You have a place on this degree, or a clear plan for it.",
                                        "इस डिग्री में आपका दाख़िला है, या उसकी साफ़ योजना है।")},
                 hours=10, kg_refs=[degree["key"]], attrs={"exam_critical": True})
        others = [r for r in self.routes["common"] + self.routes["alternative"] if r["degree"]["key"] != degree["key"]]
        if self.band == "dropper":  # backups: related careers' usual routes too
            for related in self.store.related(self.focus_key, limit=4):
                routes = self.store.pathways(related["key"])
                first = (routes["common"] or routes["alternative"] or [None])[0]
                if first and first["degree"]["key"] not in {r["degree"]["key"] for r in others} | {degree["key"]}:
                    others.append(first)
        if others:
            self.add("module:degree:other_routes", parent, "module", stage, t("Other routes in", "दूसरे रास्ते"),
                     detail={"why": t("So one exam or one result doesn't decide everything.",
                                      "ताकि एक परीक्षा या एक नतीजा सब कुछ तय न करे।"),
                             "how": [r["degree"]["name"] for r in others],
                             "done_when": t("You know at least one backup route.", "आप कम से कम एक दूसरा रास्ता जानते हैं।")},
                     hours=2, kg_refs=[r["degree"]["key"] for r in others])

    def _slot_college_exploration(self, m: Milestone, parent: str, stage: str) -> None:
        if not self.focus_key:
            return
        state = self.inputs.state
        counts = self.store.college_counts(self.focus_key, state)
        names = [c["name"] for c in self.store.colleges_for(self.focus_key, state=state, limit=5)["colleges"]] if state else []
        if state:
            title = t(f"Colleges in {state} ({counts['in_state']} on the official lists)",
                      f"{state} के कॉलेज (आधिकारिक सूचियों में {counts['in_state']})")
        else:
            title = t("Colleges that offer your route", "आपका रास्ता पढ़ाने वाले कॉलेज")
        self.add("module:colleges", parent, "module", stage, title,
                 detail={"why": m.why.model_dump() if m.why else {}, "how": [t(n, n) for n in names],
                         "done_when": t("You've shortlisted colleges and checked their official sites.",
                                        "आपने कॉलेजों की सूची बनाकर उनकी आधिकारिक वेबसाइट देखी है।")},
                 hours=4, attrs={"link": "colleges", "total": counts["total"], "in_state": counts["in_state"],
                                 "auto": "shortlist"})

    def _slot_weak_areas(self, m: Milestone, parent: str, stage: str) -> None:
        hard = self.difficulties()
        if not hard:
            self.add("module:weak_chapters", parent, "module", stage, t("Find your weak chapters", "अपने कमज़ोर अध्याय पहचानिए"),
                     detail={"why": m.why.model_dump() if m.why else {},
                             "done_when": t("You have a list of chapters to fix, from your last attempt and mock tests.",
                                            "पिछले प्रयास और मॉक टेस्ट से सुधारने वाले अध्यायों की सूची आपके पास है।")},
                     hours=10, attrs={"exam_critical": True})
        for subject, said in hard:
            self._foundation(subject, parent, stage, said)

    def _slot_skill_gap_analysis(self, m: Milestone, parent: str, stage: str) -> None:
        how = []
        for bucket in ("foundation", "entry", "advanced"):
            for s in self.buckets[bucket]:
                r = next((self.inputs.measured[k] for k in [s["key"]] if k in self.inputs.measured), None)
                status = ("measured: " + r["says"]["en"]) if r else "not measured yet"
                how.append(t(f"{s['name']['en']} — {status}", f"{s['name']['hi']} — " + (r["says"]["hi"] if r else "अभी मापा नहीं गया")))
        self.add("module:gap_analysis", parent, "module", stage, m.title.model_dump(),
                 detail={"why": m.why.model_dump() if m.why else {}, "how": how,
                         "done_when": t("You know which skills to work on first.", "आप जानते हैं कि पहले किन हुनरों पर काम करना है।")},
                 hours=3)

    def _slot_roles(self, m: Milestone, parent: str, stage: str) -> None:
        if not self.focus_key:
            return
        roles = self.store.out(self.focus_key, "leads_to_role")[:5]
        names = self.store.names([e["other"] for e in roles])
        title = (t("Choose what to specialise in", "किसमें विशेषज्ञता लेनी है, चुनिए") if m.slot == "specialise"
                 else t("Roles this leads to", "यह किन भूमिकाओं तक ले जाता है"))
        self.add(f"task:roles:{stage}", parent, "task", stage, title,
                 detail={"why": t("Where this direction usually leads.", "यह दिशा आम तौर पर कहाँ ले जाती है।"),
                         "how": [names[e["other"]] for e in roles],
                         "done_when": t("You've applied for a role you want.", "आपने अपनी पसंद की भूमिका के लिए आवेदन किया है।")},
                 hours=20)

    def _slot_specialise(self, m: Milestone, parent: str, stage: str) -> None:
        self._slot_roles(m, parent, stage)

    # -- rules --

    def _foundation(self, subject: str, parent: str, stage: str, said: bool) -> None:
        skill = SUBJECT_SKILLS[subject]
        en, hi = SUBJECT_NAMES[subject]
        measured = self.inputs.measured.get(skill)
        if said:
            reason = t(f"Added because you said {en.lower()} feels hard.", f"इसलिए जोड़ा क्योंकि आपने कहा कि {hi} मुश्किल लगता है।")
        else:
            reason = t(f"Added because your {en.lower()} result was {measured['says']['en']}.",
                       f"इसलिए जोड़ा क्योंकि आपका {hi} का नतीजा {measured['says']['hi']} था।")
        builds = self.store.developed_by(skill)
        self.add(f"module:foundation:{subject}", parent, "module", stage, t(f"{en} foundation", f"{hi} की बुनियाद"),
                 detail={"why": reason, "how": [b["name"] for b in builds],
                         "resources": [{"name": b["name"], "url": b["attrs"].get("url")} for b in builds if b["attrs"].get("url")],
                         "done_when": t("The basics feel comfortable again — check with a short test or your teacher.",
                                        "बुनियादी बातें फिर से सहज लगती हैं — छोटे टेस्ट या शिक्षक से जाँच लीजिए।")},
                 hours=15, kg_refs=[skill], attrs={"inserted_for": subject, "reason": reason, "skill": skill,
                                                    "foundation_for": skill})
        self.merged[skill] = f"module:foundation:{subject}"

    def difficulties(self) -> list[tuple[str, bool]]:
        out = [(s, True) for s in self.inputs.difficulties if s in SUBJECT_SKILLS]
        for subject, skill in SUBJECT_SKILLS.items():
            r = self.inputs.measured.get(skill)
            if r and r["value"] < GAP and subject not in [s for s, _ in out]:
                out.append((subject, False))
        return out

    def link_foundations(self) -> None:
        """Every module that builds on a hard subject waits for its foundation module."""
        foundations = {n["attrs"]["foundation_for"]: k for k, n in self.nodes.items() if n["attrs"].get("foundation_for")}
        if not foundations:
            return
        closure: dict[str, set[str]] = {}
        for key, node in self.nodes.items():
            skill = node["attrs"].get("skill")
            if not skill or key.startswith("module:foundation:"):
                continue
            if skill not in closure:
                closure[skill] = {s["key"] for s in self.store.prerequisite_path([skill])}
            for base, module in foundations.items():
                if base in closure[skill] and module not in node["prerequisites"]:
                    node["prerequisites"].append(module)
        route = self._first_route()
        if route:
            needed = {s["key"].split(":")[1] for s in route["subjects"]["mandatory"]}
            for key, node in self.nodes.items():
                if node["attrs"].get("exam"):
                    for subject, module in ((n["attrs"]["inserted_for"], k) for k, n in self.nodes.items()
                                            if n["attrs"].get("inserted_for")):
                        if subject in needed and module not in node["prerequisites"]:
                            node["prerequisites"].append(module)

    def branches(self, current: str) -> None:
        from app.assessment.alignment import career_needs

        for career in self.inputs.branches:
            node = self.store.node(f"career:{career}")
            if node is None or career == self.inputs.focus:
                continue
            key = f"branch:{career}"
            self.add(key, f"stage:{current}", "branch", current, t(f"Exploring: {node['name']['en']}", f"खोज: {node['name']['hi']}"),
                     detail={"why": t("A direction you're curious about, alongside your focus.",
                                      "आपके लक्ष्य के साथ-साथ एक दिशा जिसमें आपकी रुचि है।")},
                     kg_refs=[f"career:{career}"], attrs={"career": career, "optional": True})
            self._explore_task(f"task:explore:{career}", career, key, current, career_needs())
            for skill in self._skill_buckets(f"career:{career}")["entry"][:1]:
                self._skill_module(skill, key, current, optional=True, career_name=node["name"])

    def parked(self, current: str) -> None:
        """What only a dropped career needed stays visible as "parked" — never silently removed."""
        for career in self.inputs.dropped:
            node = self.store.node(f"career:{career}")
            if node is None or career == self.inputs.focus or career in self.inputs.branches:
                continue
            buckets = self._skill_buckets(f"career:{career}")
            unique = [s for b in buckets.values() for s in b
                      if f"module:skill:{s['key'].split(':', 1)[1]}" not in self.nodes and s["key"] not in self.merged]
            if not unique:
                continue
            parent = f"milestone:{current}:parked:{career}"
            self.add(parent, f"stage:{current}", "milestone", current,
                     t(f"Parked: {node['name']['en']}", f"रुका हुआ: {node['name']['hi']}"),
                     detail={"why": t(f"You moved away from {node['name']['en']}. These stay here in case you come back.",
                                      f"आप {node['name']['hi']} से हट गए। अगर लौटें तो ये यहाँ हैं।")},
                     state="parked", attrs={"career": career})
            for skill in unique:
                self._skill_module(skill, parent, current, career_name=node["name"])
                self.nodes[f"module:skill:{skill['key'].split(':', 1)[1]}"]["state"] = "parked"

    # -- the whole tree --

    def build(self) -> list[dict]:
        band = self.tpl.bands[self.band]
        if self.band in ("dropper", "college"):
            current = band.stages[0]
            later = band.later
        else:
            current = f"class_{self.inputs.class_level}"
            school = [f"class_{n}" for n in range(self.inputs.class_level + 1, 13)]
            later = school + [s for s in band.later if not s.startswith("class_")]
        stages = [current] + later
        for stage in stages:
            self.add(f"stage:{stage}", None, "stage", stage, self.tpl.stages[stage].model_dump(), attrs={"current": stage == current})

        hard = self.difficulties()
        if hard and self.band != "dropper":  # a dropper's weak-area plan holds them
            parent = f"milestone:{current}:strengthen"
            self.add(parent, f"stage:{current}", "milestone", current, t("Strengthen the basics", "बुनियाद मज़बूत कीजिए"),
                     detail={"why": t("Some basics need work first — everything that builds on them waits for them.",
                                      "पहले कुछ बुनियादी चीज़ों पर काम चाहिए — उन पर टिकी हर चीज़ उनका इंतज़ार करती है।")})
            for subject, said in hard:
                self._foundation(subject, parent, current, said)

        for milestone in band.spine:
            self._milestone(milestone, current)
        self.branches(current)
        for stage in later:
            for milestone in self.tpl.later.get(stage, []):
                if milestone.slot and milestone.slot in self.filled and milestone.slot not in REPEATABLE:
                    continue
                self._milestone(milestone, stage)
        self.parked(current)
        self.link_foundations()
        self._drop_dangling()
        return self._schedule(current, stages)

    def _milestone(self, m: Milestone, stage: str) -> None:
        key = f"milestone:{stage}:{m.key}"
        self.add(key, f"stage:{stage}", "milestone", stage, m.title.model_dump(),
                 detail={k: v.model_dump() for k, v in (("why", m.why), ("done_when", m.done_when)) if v},
                 hours=m.hours, attrs={"optional": m.optional, "exam_critical": m.exam_critical, "slot": m.slot})
        self.fill(m.slot, m, key, stage)

    def _drop_dangling(self) -> None:
        for node in self.nodes.values():
            node["prerequisites"] = sorted({p for p in node["prerequisites"] if p in self.nodes and p != node["node_key"]})

    # -- time --

    def _ordered(self, keys: list[str]) -> list[str]:
        """Prerequisites first, otherwise the order they were added."""
        position = {k: n for n, k in enumerate(keys)}
        placed, out = set(), []
        remaining = list(keys)
        while remaining:
            for k in remaining:
                if all(p in placed or p not in position for p in self.nodes[k]["prerequisites"]):
                    out.append(k)
                    placed.add(k)
                    remaining.remove(k)
                    break
            else:
                out.extend(remaining)  # can't happen without a cycle; never loop forever
                break
        return out

    def _schedule(self, current: str, stages: list[str]) -> list[dict]:
        start = _month(self.today)
        end = _academic_end(start)
        degree_years = 4
        route = self._first_route()
        if route and route["degree"].get("duration_years"):
            degree_years = max(1, round(route["degree"]["duration_years"]))
        if self.band == "college":  # the rest of the degree, from the year of study
            year = int((self.inputs.education_stage or "ug_y1").split("_y")[-1]) if "_y" in (self.inputs.education_stage or "") else 1
            end = _add(_academic_end(start), 12 * max(0, degree_years - year))
        months_left = max(1, (end[0] - start[0]) * 12 + end[1] - start[1] + 1)
        capacity = months_left * 4.345 * max(1, self.inputs.hours_per_week)
        work = [k for k, n in self.nodes.items() if n["stage"] == current and n["kind"] in ("module", "task")
                and n["state"] == "active"]
        total = sum(self.nodes[k]["est_hours"] or 0 for k in work)
        # Not enough time: defer optional work, latest first — never exam-critical or required work.
        for key in reversed(work):
            if total <= capacity:
                break
            node = self.nodes[key]
            if node["attrs"].get("optional") and not node["attrs"].get("exam_critical"):
                node["state"] = "deferred"
                node["attrs"]["reason"] = t(
                    f"Moved to later: it doesn't fit in {hours_phrase(self.inputs.hours_per_week)} a week this year.",
                    f"बाद के लिए रखा: इस साल हफ़्ते के {self.inputs.hours_per_week} घंटों में यह नहीं समाता।")
                total -= node["est_hours"] or 0
        hours = 0.0
        for key in self._ordered([k for k in work if self.nodes[k]["state"] == "active"]):
            node = self.nodes[key]
            first = _add(start, int(hours / max(1, self.inputs.hours_per_week) / 4.345))
            hours += node["est_hours"] or 0
            last = _add(start, int(max(hours - 0.01, 0) / max(1, self.inputs.hours_per_week) / 4.345))
            node["window"] = {"from": _fmt(first), "to": _fmt(last)}
        # Later stages: the academic or degree calendar.
        stage_windows = {current: (start, end)}
        cursor = _add(end, 1)
        for stage in stages[1:]:
            if stage.startswith("class_"):
                stage_windows[stage] = (cursor, _add(cursor, 11))
                cursor = _add(cursor, 12)
            elif stage == "degree":
                stage_windows[stage] = (cursor, _add(cursor, degree_years * 12 - 1))
                cursor = _add(cursor, degree_years * 12)
            elif stage in ("specialisation", "internship"):
                stage_windows[stage] = (_add(cursor, -12), _add(cursor, -1))
            else:
                stage_windows[stage] = (cursor, _add(cursor, 11))
        for node in self.nodes.values():
            if node["window"] is None and node["stage"] in stage_windows and node["stage"] != current:
                a, b = stage_windows[node["stage"]]
                node["window"] = {"from": _fmt(a), "to": _fmt(b)}
        for kind in ("milestone", "stage"):
            for node in self.nodes.values():
                if node["kind"] != kind:
                    continue
                inside = [c["window"] for c in self.nodes.values() if c["parent_key"] == node["node_key"] and c["window"]]
                if inside:
                    node["window"] = {"from": min(w["from"] for w in inside), "to": max(w["to"] for w in inside)}
                elif node["stage"] in stage_windows:
                    a, b = stage_windows[node["stage"]]
                    node["window"] = {"from": _fmt(a), "to": _fmt(b)}
        return self._sorted(stages)

    def _sorted(self, stages: list[str]) -> list[dict]:
        out = []

        def walk(parent: str | None):
            children = [k for k, n in self.nodes.items() if n["parent_key"] == parent]
            if parent and self.nodes[parent]["kind"] in ("milestone", "branch"):
                children = self._ordered(children)
            for k in children:
                out.append(self.nodes[k])
                walk(k)

        for stage in stages:
            out.append(self.nodes[f"stage:{stage}"])
            walk(f"stage:{stage}")
        for n, node in enumerate(out):
            node["sort"] = n
        return out


def build(store: GraphStore, inputs: Inputs, today: date | None = None) -> list[dict]:
    return Builder(store, inputs, today or date.today()).build()
