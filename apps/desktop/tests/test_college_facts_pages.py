"""College facts on the Pi's screens: every value with its source and freshness, conflicts shown,
'not found' said plainly, the source a tap away; finding colleges by what matters, with what was
left out (because it isn't known) counted."""

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from app.pages import college_detail, college_find
from app.pages.college_detail import CollegeDetailPage
from app.pages.college_find import CollegeFindPage, CollegeSourcesPage
from app.widgets.facts import FactRow, SourceDialog
from tests.test_assessment_pages import Window as BaseWindow


class Window(BaseWindow):
    def go_back(self):
        pass


def view(attribute, what, text, source="MANIT Bhopal (official website)", tier=2, state="fresh", status="verified",
         year=None, conflict=None):
    return {"attribute": attribute, "what": {"en": what, "hi": what}, "text": {"en": text, "hi": text}, "value": {},
            "status": status, "academic_year": year, "quote": "Tuition Fee 62500 62500", "verified_by": "auto",
            "retrieved_at": "2026-10-02T10:00:00+00:00",
            "label": {"en": "Verified today", "hi": "आज जाँचा गया", "state": state},
            "source": {"name": source, "tier": tier, "kind": "institution" if tier == 2 else "dataset",
                       "official": tier <= 4, "document": "B.Tech fee structure 2026-27", "url": "https://www.manit.ac.in/fees.pdf",
                       "locator": "page 2"},
            "conflict": conflict}


TUITION = view("fee.tuition.annual", "Tuition fee", "₹62,500 a semester", year="2026-27",
               conflict=[view("fee.tuition.annual", "Tuition fee", "₹60,000 a semester", source="JoSAA", tier=3)])
TUITION["status"] = "conflicted"
COLLEGE = {
    "id": 7, "canonical_name": "Maulana Azad National Institute of Technology Bhopal", "city": "Bhopal",
    "state": "Madhya Pradesh", "college_type": "NIT", "ownership": "government", "is_demo_data": False,
    "official_website": None, "admission": None, "profile": None, "aliases": [],
    "facts": {
        "Academic": {"ranking.nirf.engineering": {**view("ranking.nirf.engineering", "NIRF rank (engineering)", "72 (Engineering 2025)",
                                                          source="NIRF, Ministry of Education", tier=1),
                                                  "value": {"rank": 72, "category": "Engineering", "year": 2025}}},
        "Financial": {"fee.tuition.annual": TUITION},
        "Campus": {"facility.medical": view("facility.medical", "Medical facility", "Not found in official sources", status="not_available",
                                            state="not_available")},
        "Location": {"near.railway_station": view("near.railway_station", "Nearest railway station",
                                                  "Bhopal Junction, 6.2 km (straight line)", "OpenStreetMap contributors (ODbL)", 5),
                     "location.website": {**view("location.website", "Official website", "…"), "value": {"url": "https://www.manit.ac.in/"}}},
        "Admissions": {},
    },
    "sources": [{"document": "B.Tech fee structure 2026-27", "publisher": "MANIT Bhopal (official website)", "tier": 2,
                 "kind": "institution", "official": True, "url": "https://www.manit.ac.in/fees.pdf",
                 "retrieved_at": "2026-10-02T10:00:00+00:00"}],
}


class FakeApi:
    def __init__(self):
        self.calls = []

    def get_college(self, college_id):
        return COLLEGE

    def get_cutoffs(self, college_id):
        return []

    def get_reviews(self, college_id):
        return []

    def shortlist(self):
        return [{"id": 7}] if ("add", 7) in self.calls and ("remove", 7) not in self.calls[self.calls.index(("add", 7)):] else []

    def shortlist_add(self, college_id):
        self.calls.append(("add", college_id))
        return {"added": "x", "shortlist": 1}

    def shortlist_remove(self, college_id):
        self.calls.append(("remove", college_id))
        return {"removed": "x", "shortlist": 0}

    def college_refresh(self, college_id):
        self.calls.append(("refresh", college_id))
        return {"queued": True, "message": "MAYA will check this college's official sources again tonight."}

    def discover_colleges(self, **filters):
        self.calls.append(("discover", filters))
        return {"total": 1, "sorted_by": filters.get("sort"), "left_out": {"no tuition fee on record": 3},
                "home": {"town": "Indore", "state": "Madhya Pradesh"}, "note": "No overall score: compare the attributes.",
                "colleges": [{"id": 7, "name": COLLEGE["canonical_name"], "city": "Bhopal", "state": "Madhya Pradesh",
                              "distance_km": 171.4, "nirf_rank": 72,
                              "tuition": {"value": "₹62,500 a semester", "academic_year": "2026-27"}}]}


@pytest.fixture()
def api(monkeypatch):
    fake = FakeApi()
    now = lambda fn, *a, on_success=None, on_error=None, **kw: on_success and on_success(fn(*a, **kw))  # noqa: E731
    for module in (college_detail, college_find):
        monkeypatch.setattr(module, "api_client", fake)
        monkeypatch.setattr(module, "run_async", now)
    monkeypatch.setattr(college_find.session, "profile", {"city": "Indore", "state": "Madhya Pradesh"})
    return fake


def texts(widget):
    return " ".join(label.text() for label in widget.findChildren(QLabel))


def button(widget, text):
    return next(b for b in widget.findChildren(QPushButton) if b.text() == text)


def test_a_college_page_shows_where_each_value_comes_from(qapp, api):
    page = CollegeDetailPage(Window())
    page.on_show(college_id=7)
    shown = texts(page)
    assert "NIRF 2025: #72 in Engineering" in shown
    assert "<b>Tuition fee:</b> ₹62,500 a semester" in shown
    assert "MANIT Bhopal (official website) · 2026-27 · Verified today" in shown
    assert "Another source says: ₹60,000 a semester (JoSAA)" in shown and "couldn't be reconciled" in shown
    assert "<b>Medical facility:</b> Not found in official sources" in shown, "not found is said, never filled in"
    assert "Places © OpenStreetMap contributors (ODbL)" in shown
    button(page, "Save to my shortlist").click()
    assert ("add", 7) in api.calls and page.save_btn.text() == "✓ On your shortlist (remove)"
    button(page, "Check for updates").click()
    assert api.calls[-1] == ("refresh", 7) and "again tonight" in page.refresh_note.text()
    button(page, "Where this comes from").click()
    assert page.ctx.went[-1][0] == "college_sources"


def test_a_tap_shows_the_source(qapp):
    dialog = SourceDialog(TUITION, "en")
    shown = texts(dialog)
    assert "Source: MANIT Bhopal (official website) (The college's own)" in shown
    assert "Document: B.Tech fee structure 2026-27, page 2" in shown and "Academic year: 2026-27" in shown
    assert "“Tuition Fee 62500 62500”" in shown and "Read automatically from the document" in shown
    row = FactRow(view("near.airport", "Nearest airport", "Raja Bhoj Airport, 15.8 km", "OpenStreetMap contributors (ODbL)", 5,
                       state="stale"), "en")
    chip = [label for label in row.findChildren(QLabel) if "OpenStreetMap" in label.text()][0]
    assert "#b45309" in chip.styleSheet(), "stale is amber"


def test_finding_colleges_by_what_matters(qapp, api):
    page = CollegeFindPage(Window())
    page.on_show(career="cse", career_name="Computer Science")
    filters = api.calls[-1][1]
    assert filters["career"] == "cse" and filters["home"] == "Indore" and filters["sort"] == "distance"
    assert "Distances from Indore" in texts(page)
    shown = texts(page)
    assert "1 colleges · left out because it isn't known: 3 (no tuition fee on record)" in shown
    assert "Bhopal, Madhya Pradesh · 171.4 km · tuition ₹62,500 a semester (2026-27) · NIRF #72" in shown
    button(page, "≤ ₹1 lakh").click()
    assert api.calls[-1][1]["budget_max"] == 100000
    button(page, "Hostel").click()
    assert api.calls[-1][1]["hostel"] is True


def test_where_it_all_comes_from(qapp):
    page = CollegeSourcesPage(Window())
    page.on_show(college=COLLEGE)
    shown = texts(page)
    assert "B.Tech fee structure 2026-27" in shown and "The college's own" in shown
    assert "never guessed" in shown
