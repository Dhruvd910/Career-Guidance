"""Finding the pages and PDFs on an official website that answer students' questions — fees,
hostel and mess, admissions and prospectus, the health centre, how to reach the campus
(docs/design/15-phase6-plan.md, Step 4).

Starting from the home page: at most 40 pages, two links deep, on the institute's own domain,
following the most promising links first (by their words and address). Tenders, recruitment and
results are passed over even when they mention a hostel. Every page fetched is kept raw by the
fetcher; the crawl returns the relevant ones, best first.
"""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.ingest.fetch import Fetched, Fetcher
from app.ingest.text import Extracted, extract

WORDS = {"fee structure": 8, "fee": 5, "fees": 5, "tuition": 5, "hostel": 4, "mess": 4, "admission": 4,
         "prospectus": 5, "brochure": 4, "information bulletin": 5, "bulletin": 2, "health centre": 5,
         "health center": 5, "hospital": 2, "dispensary": 4, "medical": 2, "facilities": 2, "campus": 1,
         "how to reach": 4, "reach us": 4, "contact": 2, "address": 1, "library": 1, "nirf": 3, "ug": 1,
         "b.tech": 2, "mbbs": 3, "academic": 1, "शुल्क": 5, "छात्रावास": 4, "प्रवेश": 4}
AVOID = ("tender", "recruitment", "vacanc", "career", "job", "result", "notice-board", "gallery", "alumni", "rti",
         "quotation", "e-procurement", "advertisement", "phd", "ph.d", "m.tech", "mba", "pg-", "/pg/")
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".rar", ".mp4", ".mp3", ".doc", ".docx", ".xls",
            ".xlsx", ".ppt", ".pptx", ".css", ".js", ".ico", ".webp")


def site_of(url: str) -> str:
    host = urlsplit(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, site: str) -> bool:
    host = site_of(url)
    return host == site or host.endswith("." + site)


def score(text: str) -> int:
    text = text.lower()
    if any(a in text for a in AVOID):
        return -10
    return sum(w for word, w in WORDS.items() if word in text)


@dataclass
class Page:
    url: str
    fetched: Fetched
    extracted: Extracted
    score: int
    via: str  # the link text that led here

    @property
    def is_pdf(self) -> bool:
        return self.extracted.kind == "pdf"


def crawl(fetcher: Fetcher, home: str, max_pages: int = 40, depth: int = 2, keep: int = 12) -> tuple[list[Page], list[str]]:
    """The relevant pages of one site, best first, and what went wrong on the way."""
    site = site_of(home)
    queue: list[tuple[int, int, str, str]] = [(0, 0, home, "home page")]
    seen, pages, problems = {home}, [], []
    fetched = 0
    while queue and fetched < max_pages:
        priority, level, url, via = heapq.heappop(queue)
        page = fetcher.get(url)
        fetched += 1
        if not page.ok:
            problems.append(f"{url}: {page.error}")
            continue
        if not (page.mime or "").startswith(("text/html", "application/pdf", "application/xhtml")) and page.body[:5] != b"%PDF-":
            continue
        try:
            text = extract(page.body, page.final_url, page.mime, page.storage_path)
        except Exception as e:  # a broken PDF shouldn't stop the crawl
            problems.append(f"{url}: couldn't read ({type(e).__name__})")
            continue
        relevance = score(f"{via} {url} {text.title}") * 2 + min(score(text.text[:20000]), 20)
        pages.append(Page(page.final_url, page, text, relevance, via))
        if level >= depth:
            continue
        for link, words in text.links:
            if link in seen or not same_site(link, site) or link.lower().endswith(SKIP_EXT) or "mailto:" in link:
                continue
            hint = score(f"{words} {link}")
            if hint <= 0 and level >= 1:
                continue
            seen.add(link)
            heapq.heappush(queue, (-hint, level + 1, link, words[:120]))
    relevant = sorted((p for p in pages if p.score > 0), key=lambda p: -p.score)
    return relevant[:keep], problems


def title_names(page: Fetched, text: Extracted, names: list[str]) -> str | None:
    """The words on a home page that show it's this institute's site: its title (or its first
    lines) carrying the institute's name or short name. None if they don't."""
    from app.ingest.locations import same_place_name

    head = [text.title] + [line for line in text.text.split("\n")[:15] if 8 < len(line) < 160]
    for line in head:
        if not line:
            continue
        for name in names:
            if same_place_name(name, line) or re.search(rf"\b{re.escape(name)}\b", line, re.I) and len(name) >= 4:
                return line
    # A title in Hindi only ("भारतीय प्रौद्योगिकी संस्थान मुंबई"): the official name, or a short name of two
    # or more words ("IIT Bombay"), written anywhere on the page.
    for line in text.text.split("\n"):
        for name in [n for n in names if len(n.split()) >= 2]:
            if len(line) < 300 and re.search(rf"\b{re.escape(name)}\b", line, re.I):
                return line
    return None
