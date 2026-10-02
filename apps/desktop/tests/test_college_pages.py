"""College pages without a backend: what the comparison concludes and how it reads."""

from PySide6.QtWidgets import QLabel

from app import college_facts as facts
from app.pages import colleges as colleges_page
from app.pages.college_detail import CollegeDetailPage
from app.pages.compare import ComparePage, verdicts
from app.voice import Voice


class FakeWindow:
    def __init__(self):
        self.voice = Voice()
        self.navigated = []

    def navigate(self, name, **kwargs):
        self.navigated.append((name, kwargs))

    def go_back(self):
        pass


def admission(exam, hardest, easiest, quota="AI"):
    return {"exam_code": exam, "year": 2026, "round": 5, "source": "JoSAA", "source_url": "https://josaa.admissions.nic.in",
            "program_count": 2,
            "toughest": {"program": "Computer Science and Engineering (B.Tech)", "closing_rank": hardest, "quota": quota},
            "easiest": {"program": "Civil Engineering (B.Tech)", "closing_rank": easiest, "quota": quota},
            "programs": []}


def cell(what, value, source="IIT (official website)", year=None, state="fresh", conflict=None):
    return {"what": what, "value": value, "status": "verified", "academic_year": year, "source": source,
            "official": True, "url": "https://example.ac.in/fees.pdf", "conflict": conflict,
            "label": {"en": "Verified 3 days ago", "hi": "3 दिन पहले जाँचा गया", "state": state}}


def row(name, nirf=None, cost=None, adm=None, station=None):
    cells = {}
    if nirf:
        cells["ranking.nirf.engineering"] = cell("NIRF rank (engineering)", f"{nirf} (Engineering 2025)", "NIRF, Ministry of Education")
    if cost:
        cells["fee.tuition.annual"] = cell("Tuition fee", {200000: "₹2,00,000 a year", 125000: "₹1,25,000 a year"}[cost],
                                           year="2026-27")
    if station:
        cells["near.railway_station"] = cell("Nearest railway station", station, "OpenStreetMap contributors (ODbL)")
    return {"college": {"id": hash(name) % 1000, "canonical_name": name, "city": "City", "state": "State",
                        "college_type": "IIT", "ownership": "government", "is_demo_data": False},
            "approximate_annual_cost": cost, "admission": adm, "profile": None, "facts": cells,
            "lowest_closing_rank_seen": None, "hostel_available": None, "placement_percentage": None,
            "average_package": None, "average_rating": None}


BOMBAY = row("Indian Institute of Technology Bombay", nirf=3, cost=200000, adm=admission("JEE_ADVANCED", 67, 7838),
             station="Kanjurmarg, 3.1 km (straight line)")
MADRAS = row("Indian Institute of Technology Madras", nirf=1, cost=200000, adm=admission("JEE_ADVANCED", 150, 9000))
TRICHY = row("National Institute of Technology, Tiruchirappalli", cost=125000, adm=admission("JEE_MAIN", 2000, 40000, quota="OS"))


def test_short_names_are_what_students_say():
    assert facts.short_name("Indian Institute of Technology Bombay") == "IIT Bombay"
    assert facts.short_name("National Institute of Technology, Tiruchirappalli") == "NIT Tiruchirappalli"
    assert facts.short_name("AIIMS, New Delhi") == "AIIMS, New Delhi"


def test_verdicts_pick_the_best_of_each():
    lines = verdicts([BOMBAY, MADRAS])
    assert "Best ranked: IIT Madras (NIRF #1)" in lines, "within one ranking list"
    assert "Hardest to get into: IIT Bombay (closed at 67)" in lines
    assert any(line.startswith("Easiest way in: IIT Madras") for line in lines)


def test_closing_ranks_from_different_exams_are_not_compared():
    lines = verdicts([BOMBAY, TRICHY])
    assert not any(line.startswith("Hardest") for line in lines)
    assert any("different exams" in line for line in lines)
    assert "Lowest tuition: NIT Tiruchirappalli (₹1.25 lakh a year)" in lines


def test_admission_lines_name_the_rank_that_counts():
    lines = facts.admission_lines(TRICHY["admission"])
    assert "other-state seats" in lines[0] and "JEE Main rank" in lines[0]
    assert lines[1] == "Hardest: Computer Science and Engineering (B.Tech) — closed at 2,000"
    assert facts.admission_lines(None) == ["No official cutoff loaded for this college yet."]


def test_spoken_text_reads_money_and_distances():
    assert facts.spoken("₹2 lakh, about 10 km") == "rupees 2 lakh, about 10 kilometres"


def _texts(widget):
    return " ".join(label.text() for label in widget.findChildren(QLabel))


def test_compare_page_shows_every_section(qapp):
    page = ComparePage(FakeWindow())
    page._render({"rows": [BOMBAY, MADRAS], "ai_summary": None})
    text = _texts(page)
    for section in ("At a glance", "Ranking", "Getting in", "What it costs", "Campus", "Around the campus", "Sources"):
        assert section in text, section
    assert "Kanjurmarg, 3.1 km (straight line)" in text and "OpenStreetMap contributors (ODbL) · Verified 3 days ago" in text
    assert "₹2,00,000 a year" in text and "Places © OpenStreetMap contributors" in text


def test_compare_says_what_isnt_known(qapp):
    page = ComparePage(FakeWindow())
    page._render({"rows": [BOMBAY, row("Some Engineering College")], "ai_summary": None})
    text = _texts(page)
    assert "Not known" in text and "Not in NIRF's ranked list" in text, "unknown is said, never filled in"


def test_college_page_lists_closing_ranks_for_the_chosen_category(qapp):
    page = CollegeDetailPage(FakeWindow())
    page.college_id = 1
    detail = dict(BOMBAY["college"], id=1, established_year=1958, official_website="https://www.iitb.ac.in",
                  profile=BOMBAY["profile"], admission=BOMBAY["admission"], courses_offered=[], aliases=[])
    page._render(detail)
    cutoffs = [
        {"program": "CSE (B.Tech)", "category": "General", "seat_type": "Gender-Neutral", "quota": "AI", "year": 2026, "closing_rank": 67},
        {"program": "CSE (B.Tech)", "category": "OBC", "seat_type": "Gender-Neutral", "quota": "AI", "year": 2026, "closing_rank": 30},
    ]
    page._got_cutoffs(1, cutoffs)
    page.category_combo.setCurrentIndex(page.category_combo.findData("General"))
    assert "67" in _texts(page.body) and "all-India seats" in _texts(page.body)
    page.category_combo.setCurrentIndex(page.category_combo.findData("SC"))
    assert "No SC seats listed here." in _texts(page.body)
    page._got_cutoffs(2, [])  # a late answer for a college the student already left
    assert page.cutoffs == cutoffs


def test_colleges_list_shows_a_page_at_a_time(qapp, monkeypatch):
    monkeypatch.setattr(colleges_page, "run_async", lambda *a, **k: None)
    page = colleges_page.CollegesPage(FakeWindow())
    many = [dict(BOMBAY["college"], id=i, canonical_name=f"College {i}") for i in range(45)]
    page._render_results(many)
    assert page.shown == colleges_page.PAGE_SIZE
    page._show_more()
    page._show_more()
    assert page.shown == 45 and page.more_btn is None
