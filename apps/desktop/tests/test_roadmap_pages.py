"""The roadmap screens: stages with progress, the next step, changing it, a step's page, what
changed, and my progress."""

import pytest

from app.pages import directions, progress as progress_page, roadmap as roadmap_page
from app.pages.progress import ProgressPage
from app.pages.roadmap import RoadmapChangesPage, RoadmapNodePage, RoadmapPage
from tests.test_assessment_pages import CSE, T, Window, button, texts


def node(key, kind, title, stage="class_10", status="not_started", state="active", children=(), **extra):
    return {"node_key": key, "kind": kind, "title": title, "stage": stage, "status": status, "state": state,
            "percent": 100 if status == "done" else 0, "window": extra.pop("window", {"from": "2026-10", "to": "2026-11"}),
            "detail": extra.pop("detail", {}), "attrs": extra.pop("attrs", {}), "prerequisites": extra.pop("prerequisites", []),
            "est_hours": extra.pop("est_hours", 15), "evidence": extra.pop("evidence", []), "children": list(children), **extra}


PYTHON = node("module:skill:python", "module", T("Python", "पाइथन"),
              detail={"why": T("AI needs Python.", "एआई को पाइथन चाहिए।"), "done_when": T("You can use it.", "इस्तेमाल कर सकते हैं।"),
                      "how": [T("CS50x", "CS50x")], "resources": [{"name": T("CS50x", "CS50x"), "url": "https://cs50.harvard.edu/x/"}]},
              prerequisites=["module:skill:programming_fundamentals"])
LOGIC = node("module:skill:logical_reasoning", "module", T("Logical reasoning", "तार्किक सोच"), status="done",
             evidence=[{"kind": "assessment", "says": T("5 of 5 right", "5 में से 5 सही")}])
LATER = node("task:project:quiz_game", "task", T("Make a quiz game", "क्विज़ गेम"), state="deferred", window=None,
             attrs={"optional": True, "reason": T("Moved to later: it doesn't fit in 2 hours a week.", "…")})
ROADMAP = {
    "version": 3, "latest_version": 3, "focus": {"key": "ai_data", "name": T("AI & Data", "एआई और डेटा")},
    "branches": [{"key": "robotics", "name": T("Robotics", "रोबोटिक्स")}], "dropped": [], "hours_per_week": 2,
    "completion": 30, "current_stage": "class_10", "time": {"hours_needed": 60, "hours_available": 52},
    "changes": [{"op": "add", "node_key": "module:foundation:mathematics", "title": T("Maths foundation", "मैथ्स की बुनियाद"),
                 "reason": T("Added because you said maths feels hard.", "…")},
                {"op": "defer", "node_key": "task:project:quiz_game", "title": T("Make a quiz game", "क्विज़ गेम"),
                 "reason": T("Moved to later: it doesn't fit in 2 hours a week.", "…")},
                {"op": "modify", "node_key": "module:skill:python", "title": T("Python", "पाइथन"), "reason": T("…", "…")}],
    "next_step": {"node_key": "module:skill:python", "title": T("Python", "पाइथन"), "stage": "class_10", "overdue": False,
                  "detail": {"why": T("AI needs Python.", "एआई को पाइथन चाहिए।")}, "window": None, "status": "not_started", "attrs": {}},
    "stages": [
        node("stage:class_10", "stage", T("Class 10", "कक्षा 10"), attrs={"current": True}, work=3, children=[
            node("milestone:class_10:foundation_skills", "milestone", T("Foundation skills", "बुनियादी हुनर"), work=2,
                 children=[LOGIC, PYTHON]),
            node("milestone:class_10:projects", "milestone", T("Projects", "प्रोजेक्ट"), work=0, children=[LATER]),
        ]),
        node("stage:degree", "stage", T("Degree", "डिग्री"), stage="degree", window={"from": "2029-04", "to": "2033-03"},
             children=[node("milestone:degree:advanced_skills", "milestone", T("Deeper skills", "गहरे हुनर"), stage="degree",
                            children=[node("module:skill:machine_learning", "module", T("Machine learning", "मशीन लर्निंग"),
                                           stage="degree")])]),
    ],
}
PROGRESS = {
    "skills": [{"skill": "skill:logical_reasoning", "name": T("Logical reasoning", "तार्किक सोच"), "initial": 0.4,
                "current": 1.0, "change": 1,
                "points": [{"at": "2026-10-01T10:00:00+00:00", "value": 0.4, "source": "assessment", "says": T("2 of 5 right", "…")},
                           {"at": "2026-11-01T10:00:00+00:00", "value": 1.0, "source": "assessment", "says": T("5 of 5 right", "…")}]}],
    "assessments": {"kinds": ["aptitude"], "attempts": 2},
    "roadmap": {"version": 3, "completion": 30, "current_stage": "class_10", "focus": ROADMAP["focus"]},
    "milestones": {"done": 1, "total": 4, "done_titles": [T("Assessment", "आकलन")]},
    "projects": {"done": 0, "total": 2, "done_titles": []},
    "goals": [], "careers_explored": {"focus": ROADMAP["focus"], "branches": ROADMAP["branches"], "moved_away_from": []},
    "note": T("Skill levels come only from assessments and practice papers.", "…"),
}


class FakeApi:
    def __init__(self):
        self.calls = []

    def roadmap(self, version=None):
        return ROADMAP

    def roadmap_versions(self):
        return [{"version": 1, "created_at": "2026-10-01T10:00:00+00:00", "rationale": T("Your first roadmap.", "…")},
                {"version": 3, "created_at": "2026-10-02T10:00:00+00:00", "rationale": T("You said mathematics feels hard.", "…")}]

    def roadmap_recalculate(self, kind, **detail):
        self.calls.append(("recalculate", kind, detail))
        return {"changed": True, "version": 4, "changes": []}

    def roadmap_focus(self, career):
        self.calls.append(("focus", career))
        return {"changed": True}

    def progress_update(self, key, status, note=None):
        self.calls.append(("progress", key, status))
        return ROADMAP

    def progress(self):
        return PROGRESS

    def career_explain(self, key):
        return CSE


@pytest.fixture()
def api(monkeypatch):
    fake = FakeApi()
    now = lambda fn, *a, on_success=None, on_error=None, **kw: on_success and on_success(fn(*a, **kw))  # noqa: E731
    for module in (roadmap_page, progress_page, directions):
        monkeypatch.setattr(module, "api_client", fake)
        monkeypatch.setattr(module, "run_async", now)
    return fake


def test_the_roadmap_page(qapp, api):
    page = RoadmapPage(Window())
    page.on_show()
    shown = texts(page)
    assert page.focus_line.text() == "Focus: AI & Data · also exploring Robotics · 30% done"
    assert "Next step" in shown and "Python" in shown
    assert "▾  CLASS 10  · now" in shown and "▸  DEGREE" in shown, "the current stage open, later ones closed"
    assert "✓  Logical reasoning   · Oct–Nov 2026" in shown
    assert "Make a quiz game  (later)" in shown
    assert "Machine learning" not in " ".join(shown)
    assert "What changed in version 3" in shown
    assert any("about 60 hours of work" in t for t in shown)
    button(page, "▸  DEGREE").click()
    assert any("Machine learning" in t for t in texts(page))


def test_changing_the_time_and_a_hard_subject(qapp, api):
    page = RoadmapPage(Window())
    page.on_show()
    button(page, "I have less (or more) time").click()
    button(page, "4").click()
    assert api.calls[-1] == ("recalculate", "time_budget", {"hours_per_week": 4, "detail": "4 hours a week"})
    assert page.ctx.went[-1] == ("roadmap_changes", {})
    button(page, "Something's hard").click()
    button(page, "Maths").click()
    assert api.calls[-1][:2] == ("recalculate", "difficulty") and api.calls[-1][2]["subject"] == "mathematics"


def test_marking_the_next_step_done_and_opening_a_step(qapp, api):
    page = RoadmapPage(Window())
    page.on_show()
    button(page, "Mark done").click()
    assert api.calls[-1] == ("progress", "module:skill:python", "done")
    button(page, "Open").click()
    name, kwargs = page.ctx.went[-1]
    assert name == "roadmap_node" and kwargs["node"]["node_key"] == "module:skill:python"
    assert kwargs["names"]["module:skill:logical_reasoning"]["en"] == "Logical reasoning"


def test_a_steps_page(qapp, api):
    page = RoadmapNodePage(Window())
    names = {"module:skill:programming_fundamentals": T("Programming fundamentals", "प्रोग्रामिंग")}
    page.on_show(node=PYTHON, names=names)
    shown = texts(page)
    assert "AI needs Python." in shown and "You can use it." in shown and "•  CS50x" in shown
    assert "Builds on: Programming fundamentals" in shown
    button(page, "Done").click()
    assert api.calls[-1] == ("progress", "module:skill:python", "done")
    page.on_show(node=LOGIC, names={})
    assert "from an assessment: 5 of 5 right" in texts(page)
    page.on_show(node=LATER, names={})
    assert "Moved to later: it doesn't fit in 2 hours a week." in texts(page) and "Done" not in texts(page)


def test_what_changed(qapp, api):
    page = RoadmapChangesPage(Window())
    page.on_show()
    shown = texts(page)
    assert "Added" in shown and "•  Maths foundation — Added because you said maths feels hard." in shown
    assert "Moved later" in shown and "1 other steps moved to new months." in shown
    assert "3.  2 Oct — You said mathematics feels hard." in shown


def test_my_progress(qapp, api):
    page = ProgressPage(Window())
    page.on_show()
    shown = texts(page)
    assert "Logical reasoning" in shown and "Improved" in shown and "First: 40%" in shown
    assert "Now: 100% — 5 of 5 right · 1 Nov" in shown
    assert "Milestones: 1 of 4" in shown and "✓  Assessment" in shown and "Assessments taken: 2" in shown
    assert "Exploring: Robotics" in shown


def test_make_a_career_my_focus(qapp, api):
    page = directions.DirectionPage(Window())
    page.on_show(key="cse")
    button(page, "Make this my focus").click()
    assert api.calls[-1] == ("focus", "cse") and page.ctx.went[-1] == ("roadmap", {})
