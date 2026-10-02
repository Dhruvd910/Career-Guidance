"""Where we are, and the shortlist, on the Pi: what MAYA keeps track of on one page, each next step
with Open / Done / Not now; the shortlist with each fact's source and freshness."""

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from app.pages import dashboard as dashboard_page, shortlist as shortlist_page, where_we_are
from app.pages.shortlist import ShortlistPage
from app.pages.where_we_are import WhereWeArePage
from tests.test_assessment_pages import T, Window

ITEM = {"key": "dates:JEE_MAIN:announced:2027-28", "kind": "dates", "title": T("JEE Main 2027: the dates are out", "…"),
        "why": T("The official bulletin for the next cycle has been published", "…"), "source": "the official bulletin",
        "priority": 70, "screen": {"page": "exam", "args": {"code": "JEE_MAIN"}}, "raised": False}
STEP = {**ITEM, "key": "roadmap:next:task:assessment:aptitude", "kind": "roadmap", "title": T("Thinking skills", "…"),
        "why": T("Your roadmap's next step", "…"), "source": "your roadmap",
        "screen": {"page": "roadmap_node", "args": {"node_key": "task:assessment:aptitude"}}}
BRIEF = {
    "who": {"name": "Asha", "class_level": 10, "stream": None, "town": "Indore, Madhya Pradesh"},
    "discussed": [], "confused": [],
    "decided": [{"what": "Roadmap focus: Data Science & AI", "position": None, "when": None, "source": "your roadmap"}],
    "working_toward": {"goals": ["Learn Python"], "focus": T("Data Science & AI", "…"), "next_step": T("Thinking skills", "…"),
                       "shortlist": 2},
    "progress": {"skills": [{"skill": "Logical reasoning", "first": 40, "now": 100, "change": 1}], "roadmap_percent": 12,
                 "milestones_done": 1, "assessments": 2},
    "last_stopped": {"current_counselling_topic": "PCM vs PCB", "decision_status": "leaning",
                     "current_problem": "Leaning PCM; father prefers PCB", "open_questions": ["How to tell father"],
                     "next_step": "Review the assessment together"},
    "next": [ITEM, STEP], "memory": True, "note": None,
}
SHORTLIST = [{"id": 35, "name": "Maulana Azad National Institute of Technology Bhopal", "city": "Bhopal", "state": "Madhya Pradesh",
              "type": "NIT", "facts": {"fee.tuition.annual": {"what": "Tuition fee", "value": "₹62,500 a semester",
                                                              "status": "verified", "source": "MANIT (official website)",
                                                              "label": {"en": "Verified today", "hi": "…", "state": "fresh"},
                                                              "academic_year": "2026-27", "official": True, "url": "x",
                                                              "conflict": None}}},
             {"id": 58, "name": "National Institute of Technology, Tiruchirappalli", "city": "Tiruchirappalli",
              "state": "Tamil Nadu", "type": "NIT", "facts": {}}]


class FakeApi:
    def __init__(self):
        self.calls = []

    def mentor_brief(self):
        return BRIEF

    def mentor_agenda(self):
        return [ITEM]

    def mentor_mark(self, key, what):
        self.calls.append((key, what))
        return {"key": key, "status": what}

    def shortlist(self):
        return SHORTLIST


@pytest.fixture()
def api(monkeypatch):
    fake = FakeApi()
    now = lambda fn, *a, on_success=None, on_error=None, **kw: on_success and on_success(fn(*a, **kw))  # noqa: E731
    for module in (where_we_are, shortlist_page, dashboard_page):
        monkeypatch.setattr(module, "api_client", fake)
        monkeypatch.setattr(module, "run_async", now)
    return fake


def texts(widget):
    return " ".join(label.text() for label in widget.findChildren(QLabel))


def buttons(widget, text):
    return [b for b in widget.findChildren(QPushButton) if b.text() == text]


def test_where_we_are(qapp, api):
    page = WhereWeArePage(Window())
    page.on_show()
    shown = texts(page)
    assert "<b>PCM vs PCB</b> — leaning one way" in shown and "?  How to tell father" in shown
    assert "<b>JEE Main 2027: the dates are out</b>" in shown and "the official bulletin" in shown
    assert "Focus: Data Science & AI" in shown and "2 colleges shortlisted" in shown
    assert "Logical reasoning: 40% → 100% (improved)" in shown
    buttons(page, "Open")[0].click()
    assert page.ctx.went[-1] == ("jee", {}), "the exam's own page"
    buttons(page, "Open")[1].click()
    assert page.ctx.went[-1] == ("roadmap", {})
    buttons(page, "Not now")[0].click()
    assert api.calls[-1] == ("dates:JEE_MAIN:announced:2027-28", "not_now")


def test_my_shortlist(qapp, api):
    page = ShortlistPage(Window())
    page.on_show()
    shown = texts(page)
    assert "Tuition fee: ₹62,500 a semester — MANIT (official website) · Verified today" in shown
    assert "Nothing verified about it yet." in shown
    buttons(page, "Compare them")[0].click()
    assert page.ctx.went[-1] == ("compare", {"college_ids": [35, 58]})


def test_the_dashboard_says_whats_next(qapp, api, monkeypatch):
    from app.session import session

    monkeypatch.setattr(session, "profile", {"onboarding_completed": True})
    page = dashboard_page.DashboardPage(Window())
    page.on_show()
    assert page.next_strip.text() == "Next: JEE Main 2027: the dates are out — The official bulletin for the next cycle has been published  ›"
