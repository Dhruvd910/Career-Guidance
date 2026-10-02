"""Official documents, searchable: chunked by page and heading, embedded on the Pi, found by
meaning and by words, written into the OKF bundle and indexed from it. A fake portal and fake
embeddings; never the web."""

import httpx

from app import rag
from app.ai.tools import execute_tool
from app.facts import store
from app.ingest import documents
from app.ingest.fetch import Fetcher
from app.ingest.text import Extracted
from app.okf import bundle
from tests.fakes import FakeEmbedding
from tests.pdfs import text_pdf
from tests.test_ingest_fetch import Clock

EMBED = FakeEmbedding()
RULES = ["JOINT SEAT ALLOCATION 2026 BUSINESS RULES", "1. ELIGIBILITY",
         "A candidate must have secured at least 75 percent marks in the Class XII examination or be in the top",
         "20 percentile of the successful candidates of their board, to be eligible for admission to IITs, NITs.",
         "2. DOCUMENTS REQUIRED", "Category certificate, PwD certificate and Class X and XII mark sheets must be uploaded."]


def test_chunks_follow_pages_and_headings():
    doc = Extracted("pdf", ["\n".join(RULES[:4]), "\n".join(RULES[4:])])
    passages = rag.chunk(doc)
    assert [p.page for p in passages] == [1, 2]
    assert passages[0].section == "1. ELIGIBILITY" and passages[1].section == "2. DOCUMENTS REQUIRED"
    long = Extracted("html", ["\n".join(f"Line {n} about hostel rules and mess timings for students." for n in range(80))])
    pieces = rag.chunk(long)
    assert len(pieces) > 1 and all(len(p.text) <= rag.TARGET + 100 for p in pieces), "a page becomes passages"
    assert pieces[1].text.split("\n")[0] in pieces[0].text, "with a little overlap, never a split line"


PORTAL = b"""<html><head><title>JoSAA</title></head><body>
<a href="https://cdnbbsr.s3waas.gov.in/josaa/Business_Rules_2026.pdf">JoSAA 2026 Business Rules</a>
<a href="https://josaa.nic.in/old/Business_Rules_2019.pdf">Business rules 2019</a>
<a href="https://example.com/fake-business-rules.pdf">Business rules (mirror)</a>
<a href="https://josaa.nic.in/gallery.pdf">Photo gallery</a></body></html>"""


def handler(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    if request.url.host == "josaa.nic.in" and request.url.path == "/":
        return httpx.Response(200, content=PORTAL, headers={"content-type": "text/html"})
    if request.url.path.endswith("Business_Rules_2026.pdf"):
        return httpx.Response(200, content=text_pdf(RULES), headers={"content-type": "application/pdf"})
    return httpx.Response(404)


def test_the_right_links_are_picked():
    links = [("https://cdnbbsr.s3waas.gov.in/josaa/Business_Rules_2026.pdf", "JoSAA 2026 Business Rules"),
             ("https://josaa.nic.in/old/Business_Rules_2019.pdf", "Business rules 2019"),
             ("https://example.com/fake-business-rules.pdf", "Business rules (mirror)"),
             ("https://josaa.nic.in/gallery.pdf", "Photo gallery")]
    picked = documents.wanted_links(links, ("business rules",))
    assert [u for u, _ in picked] == ["https://cdnbbsr.s3waas.gov.in/josaa/Business_Rules_2026.pdf",
                                      "https://josaa.nic.in/old/Business_Rules_2019.pdf"], "official hosts only, newest first"


def test_documents_reach_the_bundle_and_the_search(tmp_path, db_session, monkeypatch):
    monkeypatch.setattr(documents, "PORTALS", documents.PORTALS[:1])
    clock = Clock()
    with Fetcher(tmp_path / "sources", transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.time) as f:
        report = documents.run(db_session, f, root=tmp_path / "okf", embedder=EMBED)
    assert report["documents"] == ["JoSAA: JoSAA 2026 Business Rules (1 pages)"]
    assert report["passages"] >= 1 and bundle.check(tmp_path / "okf") == []
    concept = next(bundle.concepts(tmp_path / "okf", "documents"))
    assert concept.type == "Official Document" and concept.meta["sources"][0]["tier"] == 3
    assert concept.meta["maya"]["document"]["about"] == ["exam:JEE_ADVANCED", "exam:JEE_MAIN"]
    assert concept.meta["maya"]["document"]["academic_year"] == "2026-27"

    hits = rag.search(db_session, "class XII 75 percent eligibility", EMBED)
    assert "75 percent" in hits[0]["text"] and hits[0]["publisher"] == "JoSAA" and hits[0]["official"]
    assert rag.search(db_session, "class XII 75 percent", EMBED, entity="exam:NEET_UG") == [], "about another exam"
    assert rag.index_bundle(db_session, tmp_path / "okf", tmp_path / "sources", EMBED) == 0, "indexed once"

    from tests.test_assessment_service import student

    said = execute_tool(db_session, student(db_session), "search_documents", {"query": "documents required category certificate"})
    assert said["passages"][0]["document"] == "JoSAA 2026 Business Rules" and "Category certificate" in said["passages"][0]["text"]
    assert store.source  # the document's publisher is a source like any other
