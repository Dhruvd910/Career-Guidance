"""Exploring careers by domain, and what each stream keeps open."""

import pytest

from app.pages import careers as careers_page
from app.pages import streams as streams_page
from app.pages.careers import CareersPage
from app.pages.streams import StreamExplorerPage
from tests.test_assessment_pages import T, Window, button, texts

TREE = {"domains": [
    {"key": "domain:technology", "name": T("Technology", "टेक्नोलॉजी"),
     "careers": [{"key": "career:cse", "name": T("Computer Science", "कंप्यूटर साइंस"), "primary": True},
                 {"key": "career:design", "name": T("Design", "डिज़ाइन"), "primary": False}]},
    {"key": "domain:health", "name": T("Medicine & Health", "मेडिकल और हेल्थ"),
     "careers": [{"key": "career:mbbs", "name": T("Doctor (MBBS)", "डॉक्टर (MBBS)"), "primary": True}]},
]}
LIBRARY = [{"key": "cse", "description": "Build software.", "typical_entrance_exam_codes": ["JEE_MAIN"]},
           {"key": "mbbs", "description": "Treat patients.", "typical_entrance_exam_codes": ["NEET_UG"]},
           {"key": "design", "description": "Design products.", "typical_entrance_exam_codes": []}]


def row(career, via, missing=(), notes=()):
    return {"career": {"key": f"career:{career}", "name": T(career.upper(), career)},
            "via": {"key": f"degree:{via}", "name": T(via.upper(), via)},
            "missing": [{"key": f"subject:{m}", "name": T(m.capitalize(), m)} for m in missing],
            "notes": [{"key": f"subject:{k}", "name": T(k.capitalize(), k), "note": n} for k, n in notes]}


PCB = {"stream": {"key": "stream:pcb", "name": T("Science — PCB", "विज्ञान — पी.सी.बी.")},
       "open": [row("mbbs", "mbbs"), row("cse", "bca", notes=[("mathematics", "many colleges ask for maths")])],
       "if_you_add": [], "closed": [row("robotics", "btech_robotics", missing=["mathematics"])]}


class FakeApi:
    def __init__(self):
        self.streams = []

    def career_explore(self):
        return TREE

    def list_careers(self):
        return LIBRARY

    def career_stream(self, stream):
        self.streams.append(stream)
        return PCB


@pytest.fixture()
def api(monkeypatch):
    fake = FakeApi()
    now = lambda fn, *a, on_success=None, on_error=None: on_success and on_success(fn(*a))  # noqa: E731
    for module in (careers_page, streams_page):
        monkeypatch.setattr(module, "api_client", fake)
        monkeypatch.setattr(module, "run_async", now)
    return fake


def test_careers_by_domain(qapp, api, monkeypatch):
    monkeypatch.setattr(careers_page, "target_exam_code", lambda: None)
    page = CareersPage(Window())
    page.on_show()
    shown = texts(page)
    assert shown.index("Technology") < shown.index("Medicine & Health")
    assert "Computer Science  ›" in shown and "Build software." in shown
    button(page, "Doctor (MBBS)  ›").click()
    assert page.ctx.went[-1] == ("direction", {"key": "mbbs"})
    button(page, "Choosing a stream? See what each one keeps open").click()
    assert page.ctx.went[-1] == ("streams", {})


def test_a_neet_student_sees_medicine_first(qapp, api, monkeypatch):
    monkeypatch.setattr(careers_page, "target_exam_code", lambda: "NEET_UG")
    page = CareersPage(Window())
    page.on_show()
    shown = texts(page)
    assert shown.index("Medicine & Health") < shown.index("Technology")


def test_what_a_stream_keeps_open(qapp, api, monkeypatch):
    monkeypatch.setattr(streams_page.session, "profile", {"stream": "PCB"})
    page = StreamExplorerPage(Window())
    page.on_show()
    assert api.streams == ["pcb"], "the student's own stream first"
    shown = texts(page)
    assert "Stays open (2)" in shown and "MBBS — via MBBS  ›" in shown and "CSE — via BCA  ›" in shown
    assert "Mathematics: many colleges ask for maths" in shown
    assert "Closes (1)" in shown and "ROBOTICS — needs Mathematics  ›" in shown
    button(page, "ROBOTICS — needs Mathematics  ›").click()
    assert page.ctx.went[-1] == ("direction", {"key": "robotics"})
    button(page, "Commerce").click()
    assert api.streams[-1] == "commerce"
