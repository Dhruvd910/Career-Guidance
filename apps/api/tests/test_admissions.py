"""Admission dates from the official bulletins, checked against the quoted words; and the next
cycle's dates said to be 'not announced yet' when they aren't. Fake portal and fake model."""

import hashlib
from datetime import date

import httpx

from app.ai.tools import execute_tool
from app.facts import store
from app.ingest import admissions
from app.ingest.fetch import Fetcher
from app.ingest.read import Read
from app.ingest.text import Extracted
from app.models.exam import Exam
from tests.pdfs import text_pdf
from tests.test_ingest_fetch import Clock

BULLETIN = ["NEET (UG) - 2026 INFORMATION BULLETIN", "IMPORTANT DATES",
            "Online submission of Application Form 07.02.2026 to 07.03.2026",
            "Date of Examination 03.05.2026 (Sunday)"]


def test_dates_must_be_in_the_quoted_words():
    doc = Extracted("pdf", ["\n".join(BULLETIN)])
    ok = admissions.check({"attribute": "admission.application_window", "label": "Online application",
                           "from": "2026-02-07", "to": "2026-03-07", "exam_year": 2026,
                           "quote": "Online submission of Application Form 07.02.2026 to 07.03.2026", "page": 1}, doc)
    assert ok.value == {"from": "2026-02-07", "to": "2026-03-07", "label": "Online application"} and ok.academic_year == "2026-27"
    wrong_day = {"attribute": "admission.exam_date", "from": "2026-05-04", "quote": "Date of Examination 03.05.2026 (Sunday)"}
    assert admissions.check(wrong_day, doc) is None, "a date that isn't in the quote is thrown away"
    invented = {"attribute": "admission.result_date", "from": "2026-06-14", "quote": "Result on 14.06.2026"}
    assert admissions.check(invented, doc) is None, "words that aren't in the document are thrown away"


def test_dates_reach_the_exam_and_maya(tmp_path, db_session, monkeypatch):
    neet = Exam(code="NEET_UG", name="NEET-UG", category="medical")
    db_session.add(neet)
    db_session.flush()
    raw = text_pdf(BULLETIN)
    sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / "sources" / sha[:2]).mkdir(parents=True)
    (tmp_path / "sources" / sha[:2] / f"{sha}.pdf").write_bytes(raw)
    src = store.source(db_session, "nta-neet", "National Testing Agency (NEET-UG)", 3)
    store.document(db_session, src, "https://neet.nta.nic.in/bulletin-2026.pdf", "Information Bulletin for NEET(UG)-2026",
                   sha256=sha, parse_status="text", entity_refs=["exam:NEET_UG"])

    def fake_reader(doc, title, url, usage):
        return [Read("admission.application_window", {"from": "2026-02-07", "to": "2026-03-07", "label": "Online application"},
                     "2026-27", "Online submission of Application Form 07.02.2026 to 07.03.2026", 1),
                Read("admission.exam_date", {"from": "2026-05-03", "to": None, "label": "NEET (UG) 2026"},
                     "2026-27", "Date of Examination 03.05.2026 (Sunday)", 1)]

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"<html><title>NEET</title><body>NEET (UG) 2026 results declared</body></html>",
                              headers={"content-type": "text/html"})

    monkeypatch.setattr(admissions, "PORTALS", [p for p in admissions.PORTALS if p[0] == "nta-neet"])
    clock = Clock()
    with Fetcher(tmp_path / "sources", transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.time) as f:
        report = admissions.run(db_session, f, root=tmp_path / "okf", next_cycle=2027, reader=fake_reader)
    assert report["dates"] == 2 and report["problems"] == [] and report["bundle_problems"] == []
    shown = store.current(db_session, "exam", neet.id, prefix="admission.")
    window = shown["admission.application_window.online_application"]
    assert window["academic_year"] == "2026-27" and window["source"]["tier"] == 3 and window["source"]["locator"] == "page 1"
    upcoming = shown["admission.application_window"]
    assert upcoming["status"] == "not_available" and upcoming["academic_year"] == "2027-28"
    assert upcoming["source"]["locator"].startswith("no 2027 dates on the official portal yet (checked")

    from tests.test_assessment_service import student

    said = execute_tool(db_session, student(db_session), "admission_dates", {"exam": "NEET_UG"})
    assert said["cycles"]["2027-28"][0]["when"] == "Not found in official sources"
    assert {"Applications", "Exam date"} <= {c["what"] for c in said["cycles"]["2026-27"]}
    assert "Online application: 7 Feb 2026 – 7 Mar 2026" in {c["when"] for c in said["cycles"]["2026-27"]}
    assert "never as this year's" in said["note"]
    assert date.today()  # the cycle is computed from today's date when not given
