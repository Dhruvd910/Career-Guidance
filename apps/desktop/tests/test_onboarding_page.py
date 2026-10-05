"""The onboarding steps that need a choice on screen: the memory permission, asked once."""

from PySide6.QtWidgets import QPushButton

from app.pages import onboarding
from app.pages.onboarding import OnboardingPage
from app.voice import Voice


class FakeWindow:
    def __init__(self):
        self.voice = Voice()
        self.navigated: list[tuple] = []

    def navigate(self, name, **kwargs):
        self.navigated.append((name, kwargs))

    def set_progress(self, *args):
        pass

    def set_step_pill(self, *args):
        pass


def buttons(page):
    return {b.text().strip(): b for b in page.findChildren(QPushButton)}


def test_memory_permission_opens_the_permissions_or_is_declined_once(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(onboarding, "run_async", lambda fn, *a, on_success=None, on_error=None: calls.append((fn, a)))
    window = FakeWindow()
    page = OnboardingPage(window)
    page._render_step({"step": "memory_permission", "missing_fields": ["long_term_memory"],
                       "prompt": "Can I remember what we talk about?"})
    found = buttons(page)
    found["Set it up"].click()
    assert window.navigated == [("memory", {"tab": "permissions"})]
    found["Not now"].click()
    fn, args = calls[-1]
    assert fn.__name__ == "set_consent" and args == ("long_term_memory", False), "declining is recorded, not asked again"
