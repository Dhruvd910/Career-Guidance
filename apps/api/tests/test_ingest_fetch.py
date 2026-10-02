"""Fetching politely — robots.txt, one request per host every 2 s, retries, raw bytes kept by
sha256 — and NIRF ranks read from the ministry's pages into the bundle. Never the live web."""

import httpx

from app.facts import store
from app.ingest import nirf
from app.ingest.fetch import USER_AGENT, Fetcher
from app.okf import bundle
from tests.test_facts import college

ROBOTS = "User-agent: *\nDisallow: /private/\n"


class Clock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 2))
        self.now += seconds


def fetcher(tmp_path, handler, clock=None):
    clock = clock or Clock()
    return Fetcher(tmp_path / "sources", transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.time)


def test_robots_rate_limits_retries_and_storage(tmp_path):
    seen = []
    flaky = {"n": 0}

    def handler(request):
        seen.append(request.url.path)
        assert request.headers["user-agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS, headers={"content-type": "text/plain"})
        if request.url.path == "/flaky":
            flaky["n"] += 1
            return httpx.Response(503) if flaky["n"] == 1 else httpx.Response(200, text="ok now")
        if request.url.path == "/missing":
            return httpx.Response(404)
        return httpx.Response(200, content=b"%PDF-1.4 fee notice", headers={"content-type": "application/pdf"})

    clock = Clock()
    f = fetcher(tmp_path, handler, clock)
    blocked = f.get("https://college.ac.in/private/salaries.pdf")
    assert not blocked.ok and blocked.error == "disallowed by robots.txt" and "/private/salaries.pdf" not in seen
    first = f.get("https://college.ac.in/fees.pdf")
    second = f.get("https://college.ac.in/fees.pdf")
    assert first.ok and first.sha256 == second.sha256 and first.storage_path.endswith(".pdf")
    assert (tmp_path / "sources" / first.sha256[:2] / f"{first.sha256}.pdf").read_bytes() == b"%PDF-1.4 fee notice"
    assert clock.slept and all(s <= 2.0 for s in clock.slept), "one request every 2 s per host"
    assert f.get("https://college.ac.in/flaky").text() == "ok now", "a server error is retried"
    missing = f.get("https://college.ac.in/missing")
    assert missing.status == 404 and missing.error == "HTTP 404" and missing.storage_path is None


ROW = """<tr><td>IR-E-U-{id}</td><td>{name}<a>More Details</a><div>Close</div><td>TLR (100)</td><td>80.1</td></td>
<td>{city}</td><td>{state}</td><td>{score}</td><td>{rank}</td></tr>"""


def page(*rows):
    return "<table>" + "".join(ROW.format(**r) for r in rows) + "</table>"


def test_nirf_rows_are_parsed_and_matched(db_session):
    manit = college(db_session)
    iitb = college(db_session, "Indian Institute of Technology Bombay")
    iitb.state, iitb.city = "Maharashtra", "Mumbai"
    rows = nirf.parse(page(
        {"id": "0306", "name": "Indian Institute of Technology Bombay", "city": "Mumbai", "state": "Maharashtra", "score": "83.65", "rank": 3},
        {"id": "0400", "name": "Maulana Azad National Institute of Technology", "city": "Bhopal", "state": "Madhya Pradesh", "score": "60.1", "rank": 72},
        {"id": "0999", "name": "A University We Don't Have", "city": "Pune", "state": "Maharashtra", "score": "55", "rank": 90}))
    assert [(r.rank, r.name) for r in rows] == [(3, "Indian Institute of Technology Bombay"),
                                               (72, "Maulana Azad National Institute of Technology"),
                                               (90, "A University We Don't Have")]
    found, missed = nirf.match(rows, [manit, iitb])
    assert found[iitb.id].rank == 3 and found[manit.id].rank == 72, "by name, or the official name starting with NIRF's in the same city"
    assert [r.name for r in missed] == ["A University We Don't Have"], "never guessed"


def test_nirf_ranks_reach_the_bundle_and_the_facts(tmp_path, db_session):
    iitb = college(db_session, "Indian Institute of Technology Bombay")
    html = page({"id": "0306", "name": "Indian Institute of Technology Bombay", "city": "Mumbai", "state": "Maharashtra",
                 "score": "83.65", "rank": 3})

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if "Engineering" in request.url.path:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(500)

    with fetcher(tmp_path, handler) as f:
        report = nirf.run(db_session, f, root=tmp_path / "okf")
    assert report["ranked"]["engineering"] == "1 of 1 ranked institutes matched"
    assert report["failed"]["medical"] == "HTTP 500" and report["problems"] == []
    shown = store.current(db_session, "college", iitb.id)["ranking.nirf.engineering"]
    assert shown["value"] == {"rank": 3, "category": "Engineering", "year": 2025, "score": 83.65}
    assert shown["source"]["tier"] == 1 and shown["status"] == "verified"
    assert shown["quote"] == "IR-E-U-0306 Indian Institute of Technology Bombay Mumbai Maharashtra 83.65 3"
    assert bundle.head(tmp_path / "okf"), "committed to the bundle's own repo"
    assert "IIT Bombay" in db_session.get(type(iitb), iitb.id).aliases
