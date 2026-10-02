"""Facts from colleges' own websites: the site confirmed by its own home page, the relevant pages
found, every value checked against the document's own words, and 'not on the official website'
said plainly. A fake site and a fake model; never the web or a real model."""

import httpx

from app.facts import store
from app.ingest import college_facts, read as reading, websites
from app.ingest.crawl import crawl, score
from app.ingest.fetch import Fetcher
from app.ingest.text import Extracted, contains, from_html
from app.models.college import College
from tests.pdfs import text_pdf
from tests.test_ingest_fetch import Clock

FEES = text_pdf(["FEE STRUCTURE FOR 2026 ADMISSION BATCH (B.Tech)", "Tuition Fee (per semester) 62,500",
                 "Hostel Seat Rent (per semester) 21,000", "Mess advance (per semester) 18,000"])
HOME = b"""<html><head><title>Maulana Azad National Institute of Technology Bhopal</title></head><body>
<nav><a href="/tenders/hostel-mess-tender.pdf">Hostel mess tender</a> <a href="/recruitment">Recruitment</a></nav>
<a href="/academics/fee-structure">Fee structure</a> <a href="/campus/health-centre">Health Centre</a>
<a href="https://other.example.com/fees">Someone else's fees</a></body></html>"""
FEE_PAGE = b"""<html><head><title>Fee structure</title></head><body><h1>Fee structure 2026-27</h1>
<a href="/files/fees-2026.pdf">B.Tech fee structure 2026 (PDF)</a></body></html>"""
HEALTH = b"""<html><head><title>Health Centre</title></head><body><h1>Health Centre</h1>
<p>The institute health centre is open 24 hours with two resident doctors and an ambulance.</p></body></html>"""
SITE = {"/": HOME, "/academics/fee-structure": FEE_PAGE, "/campus/health-centre": HEALTH}


def handler(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    if request.url.path == "/files/fees-2026.pdf":
        return httpx.Response(200, content=FEES, headers={"content-type": "application/pdf"})
    if request.url.path in SITE and request.url.host == "www.manit.ac.in":
        return httpx.Response(200, content=SITE[request.url.path], headers={"content-type": "text/html"})
    return httpx.Response(404)


def fetcher(tmp_path):
    clock = Clock()
    return Fetcher(tmp_path / "sources", transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.time)


def manit(db):
    c = College(canonical_name="Maulana Azad National Institute of Technology Bhopal", college_type="NIT",
                ownership="government", state="Madhya Pradesh", city="Bhopal", is_demo_data=False,
                aliases=["NIT Bhopal", "MANIT", "MANIT Bhopal"])
    db.add(c)
    db.flush()
    return c


def test_text_and_crawl(tmp_path):
    page = from_html(HOME, "https://www.manit.ac.in/")
    assert page.title == "Maulana Azad National Institute of Technology Bhopal"
    assert ("https://www.manit.ac.in/academics/fee-structure", "Fee structure") in page.links
    assert score("Hostel mess tender") < 0 and score("Fee structure") > 0
    assert contains("Tuition Fee (per semester) 62,500", "tuition fee (per semester) 62500")
    with fetcher(tmp_path) as f:
        pages, problems = crawl(f, "https://www.manit.ac.in/")
    urls = [p.url for p in pages]
    assert urls[0].endswith("/files/fees-2026.pdf") or "fee" in urls[0], "the fee documents first"
    assert any(u.endswith("/campus/health-centre") for u in urls)
    assert not any("tender" in u or "recruitment" in u or "other.example" in u for u in urls), "never tenders, jobs or other sites"


def test_every_value_is_checked_against_the_document():
    doc = Extracted("pdf", ["FEE STRUCTURE 2026\nTuition Fee (per semester) 62,500\nHostel Seat Rent (per semester) 21,000"])
    ok = reading.check({"attribute": "fee.tuition.annual", "amount": 62500, "per": "semester", "applies_to": "General",
                        "academic_year": "2026-27", "quote": "Tuition Fee (per semester) 62,500", "page": 1}, doc)
    assert ok.value == {"amount": 62500, "per": "semester", "applies_to": "general"} and ok.flags == []
    invented = {"attribute": "fee.mess.annual", "amount": 40000, "per": "year", "academic_year": "2026-27",
                "quote": "Mess charges 40,000 per year", "page": 1}
    assert reading.check(invented, doc) is None, "words that aren't in the document are thrown away"
    calculated = {"attribute": "fee.tuition.annual", "amount": 125000, "per": "year", "academic_year": "2026-27",
                  "quote": "Tuition Fee (per semester) 62,500", "page": 1}
    undone = reading.check(calculated, doc)
    assert (undone.value["amount"], undone.value["per"]) == (62500, "semester"), "stored as the document says it"
    made_up = dict(calculated, amount=130000)
    assert reading.check(made_up, doc) is None, "a number the document doesn't have is thrown away"
    odd = reading.check({"attribute": "fee.mess.annual", "amount": 21000, "per": "month", "academic_year": None,
                         "quote": "Hostel Seat Rent (per semester) 21,000"}, doc)
    assert odd.flags == ["₹21,000 month is outside the expected range for fee.mess.annual", "no academic year given"]
    menu = Extracted("html", ["Home | Academics | Hospital | Sports | Contact"])
    assert reading.check({"attribute": "facility.medical", "text": "There is a hospital.", "quote": "Hospital"}, menu) is None, \
        "a menu word isn't evidence"
    scan = Extracted("pdf", ["T u i t i o n  F e e  6 2 5 0 0"], scanned=True)
    held = reading.check({"attribute": "fee.tuition.annual", "amount": 62500, "per": "semester", "academic_year": "2026-27",
                          "quote": "Tuition Fee 62500"}, scan)
    assert held.flags == ["the quote isn't in the Pi's own reading of this scanned page"]


def fake_model(college, place, title, url, doc, usage, images=None, client=None):
    usage.add({"prompt_tokens": 1000, "completion_tokens": 100, "cost": 0.0004})
    offered = []
    if "Tuition" in doc.text:
        offered = [
            {"attribute": "fee.tuition.annual", "amount": 62500, "per": "semester", "applies_to": "general",
             "academic_year": "2026-27", "quote": "Tuition Fee (per semester) 62,500", "page": 1},
            {"attribute": "fee.hostel.annual", "amount": 21000, "per": "semester", "academic_year": "2026-27",
             "quote": "Hostel Seat Rent (per semester) 21,000", "page": 1},
            {"attribute": "fee.mess.annual", "amount": 99000, "per": "semester", "academic_year": "2026-27",
             "quote": "Mess charges 99,000", "page": 1}]
    if "health centre" in doc.text.lower():
        offered = [{"attribute": "facility.medical", "text": "Health centre open 24 hours, two resident doctors, an ambulance",
                    "quote": "The institute health centre is open 24 hours with two resident doctors and an ambulance."}]
    checked = [r for r in (reading.check(f, doc) for f in offered) if r]
    return checked, len(offered)


def test_a_colleges_own_site_becomes_facts(tmp_path, db_session, monkeypatch):
    college = manit(db_session)
    monkeypatch.setattr(websites, "DOMAINS", {"MANIT": "manit.ac.in"})
    with fetcher(tmp_path) as f:
        confirmed = websites.run(db_session, f, root=tmp_path / "okf")
        assert confirmed["confirmed"] == 1, confirmed["missing"]
        site = store.current(db_session, "college", college.id)["location.website"]
        assert site["value"] == {"url": "https://www.manit.ac.in/"} and site["source"]["tier"] == 2
        assert site["quote"] == "Maulana Azad National Institute of Technology Bhopal", "the site says whose it is"
        report = college_facts.run(db_session, f, root=tmp_path / "okf", reader=fake_model, progress=lambda m: None)
    assert report["with_values"] == 1 and report["values"] == 3 and report["held"] == 0
    shown = store.current(db_session, "college", college.id)
    tuition = shown["fee.tuition.annual"]
    assert tuition["value"] == {"amount": 62500, "per": "semester", "applies_to": "general"}
    assert tuition["academic_year"] == "2026-27" and tuition["status"] == "verified"
    assert tuition["source"]["url"].endswith("/files/fees-2026.pdf") and tuition["source"]["locator"] == "page 1"
    assert tuition["quote"] == "Tuition Fee (per semester) 62,500"
    assert "fee.mess.annual" not in shown, "the invented mess fee never arrives"
    assert shown["facility.medical"]["value"]["text"].startswith("Health centre open 24 hours")
    assert report["usage"].calls >= 2 and round(report["usage"].cost, 4) >= 0.0008


def test_saying_nothing_is_recorded_as_nothing(tmp_path, db_session, monkeypatch):
    college = manit(db_session)
    monkeypatch.setattr(websites, "DOMAINS", {"MANIT": "manit.ac.in"})
    silent = lambda *a, **k: ([], 0)  # noqa: E731
    monkeypatch.setitem(SITE, "/academics/fee-structure", b"<html><title>Fee structure</title><body>Coming soon</body></html>")
    with fetcher(tmp_path) as f:
        websites.run(db_session, f, root=tmp_path / "okf")
        college_facts.run(db_session, f, root=tmp_path / "okf", reader=silent, progress=lambda m: None)
    shown = store.current(db_session, "college", college.id)
    assert shown["fee.tuition.annual"]["status"] == "not_available"
    assert shown["fee.tuition.annual"]["source"]["locator"].startswith("not found on the official website (looked at")
    assert shown["facility.medical"]["status"] == "not_available"
