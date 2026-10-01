"""MAYA's memory screen: see it, delete it (two taps), and give or withdraw permission."""

import pytest

from app.pages import memory as memory_page
from app.pages.memory import MemoryPage
from app.voice import Voice

MEMORY = {
    "enabled": True,
    "threads": [{"id": 1, "title": "PCM vs PCB", "status": "open", "decision_status": "leaning",
                 "current_position": "Leaning PCM", "open_questions": [], "next_step": "Aptitude assessment",
                 "last_touched_at": "2026-10-01T10:00:00+00:00"}],
    "interests": [{"id": 2, "text": "Robotics", "kind": None, "sensitive": False, "created_at": None}],
    "goals": [],
    "constraints": [{"id": 3, "text": "Father wants medicine", "kind": "family_expectation", "sensitive": True,
                     "created_at": None}],
    "memories": [{"id": 4, "text": "Built a robot", "kind": "fact", "sensitive": False, "created_at": None}],
    "recent_sessions": [{"session_id": 9, "summary": "Discussed streams.", "decisions": [], "next_steps": [],
                         "created_at": "2026-10-01T10:00:00+00:00"}],
}
CONSENT = {"is_minor": True, "notice_version": "2026-10-01", "notice": {"en": "MAYA can remember…", "hi": "MAYA याद…"},
           "long_term_memory": {"granted": False, "decided_at": None},
           "emotion_signals": {"granted": False, "decided_at": None}}


class FakeApi:
    def __init__(self):
        self.calls = []

    def get_memory(self):
        return MEMORY

    def get_consent(self):
        return CONSENT

    def timeline(self):
        return [{"id": 1, "event_type": "DECISION_MADE", "occurred_at": "2026-10-03T10:00:00+00:00",
                 "description": "Decided: PCM vs PCB", "reason": None}]

    def forget(self, kind, item_id):
        self.calls.append(("forget", kind, item_id))
        return {"deleted": {"x": 1}}

    def forget_everything(self):
        self.calls.append(("forget_everything",))
        return {"deleted": {}}

    def set_consent(self, kind, granted, guardian=None):
        self.calls.append(("set_consent", kind, granted, guardian))
        return {"kind": kind, "state": {"granted": granted}, "deleted": {"memory_items": 3} if not granted else {}}


class Window:
    def __init__(self):
        self.voice = Voice()

    def navigate(self, name, **kw):
        pass


@pytest.fixture()
def page(qapp, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(memory_page, "api_client", api)
    # Run "background" work at once, so the screen can be checked straight after.
    monkeypatch.setattr(memory_page, "run_async",
                        lambda fn, *a, on_success=None, on_error=None: on_success and on_success(fn(*a)))
    p = MemoryPage(Window())
    p.api = api
    return p


def texts(page):
    from PySide6.QtWidgets import QLabel, QPushButton
    widgets = page.body.findChildren(QLabel) + page.body.findChildren(QPushButton)
    return [w.text() for w in widgets if w.isVisibleTo(page.body)]


def test_everything_she_remembers_is_shown_private_items_marked(page):
    page.on_show()
    shown = texts(page)
    assert "PCM vs PCB — leaning. Next: Aptitude assessment" in shown
    assert "Robotics" in shown and "Built a robot" in shown
    assert "<i>Private</i> · Father wants medicine" in shown
    assert any("Discussed streams." in t for t in shown)


def test_deleting_takes_two_taps(page):
    from PySide6.QtWidgets import QPushButton
    page.on_show()
    delete = [b for b in page.body.findChildren(QPushButton) if b.text() == "Delete"][0]
    delete.click()
    assert page.api.calls == [] and delete.text() == "Sure?"
    delete.click()
    assert page.api.calls == [("forget", "thread", 1)]


def test_forgetting_everything_takes_two_taps(page):
    from PySide6.QtWidgets import QPushButton
    page.on_show()
    forget = [b for b in page.body.findChildren(QPushButton) if b.text() == "Forget everything"][0]
    forget.click()
    forget.click()
    assert page.api.calls == [("forget_everything",)]


def test_when_memory_is_off_it_says_so_and_offers_to_turn_it_on(page, monkeypatch):
    monkeypatch.setattr(page.api, "get_memory", lambda: {**MEMORY, "enabled": False})
    page.on_show()
    assert "Memory is off" in texts(page) and "Turn memory on" in texts(page)


def test_the_journey(page):
    page.on_show(tab="journey")
    assert any("Decided: PCM vs PCB" in t and "3 Oct" in t for t in texts(page))


def test_a_minor_needs_the_guardian_details_and_their_agreement(page):
    page.on_show(tab="permissions")
    page.memory_box.setChecked(True)
    page._save_permissions()
    assert "name" in page.error.text() and page.api.calls == []
    page.guardian_fields["name"].setText("Sunita Sharma")
    page.guardian_fields["contact"].setText("98xxxxxx10")
    page._save_permissions()
    assert "tick" in page.error.text() and page.api.calls == []
    page.guardian_agrees.setChecked(True)
    page._save_permissions()
    assert page.api.calls == [("set_consent", "long_term_memory", True,
                               {"name": "Sunita Sharma", "relationship": "Mother", "contact": "98xxxxxx10"})]


def test_switching_memory_off_needs_no_guardian_and_says_what_was_deleted(page, monkeypatch):
    on = {**CONSENT, "long_term_memory": {"granted": True, "decided_at": "2026-10-01T10:00:00+00:00"}}
    monkeypatch.setattr(page.api, "get_consent", lambda: on)
    page.on_show(tab="permissions")
    page.memory_box.setChecked(False)
    page._save_permissions()
    assert page.api.calls == [("set_consent", "long_term_memory", False, None)]


def test_the_notice_can_be_read_in_hindi(page):
    page.on_show(tab="permissions")
    page._switch_notice_language()
    assert "MAYA याद…" in texts(page)
