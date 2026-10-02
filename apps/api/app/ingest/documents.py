"""The national admission documents, from the official portals (tier 3): JoSAA's business rules,
MCC's counselling scheme, NTA's NEET-UG and JEE Main information bulletins, the JEE (Advanced)
brochure. Each portal's page is read for the PDFs whose links say what they are; the newest few
are fetched, written into the OKF bundle as Official Document concepts, and indexed for search.

    python -m app.ingest.documents
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app import rag
from app.core.config import get_settings
from app.ingest.fetch import Fetcher
from app.ingest.text import extract
from app.ingest.publish import SECTIONS
from app.okf import bundle, documents, loader

PORTALS = (
    ("josaa", "JoSAA", 3, "https://josaa.nic.in/", ("business rules", "information brochure"), ["exam:JEE_MAIN", "exam:JEE_ADVANCED"]),
    ("mcc", "Medical Counselling Committee (MCC)", 3, "https://mcc.nic.in/ug-medical-counselling/",
     ("scheme", "information bulletin", "information brochure"), ["exam:NEET_UG"]),
    ("nta-neet", "National Testing Agency (NEET-UG)", 3, "https://neet.nta.nic.in/", ("information bulletin",), ["exam:NEET_UG"]),
    ("nta-jee-main", "National Testing Agency (JEE Main)", 3, "https://jeemain.nta.nic.in/", ("information bulletin",), ["exam:JEE_MAIN"]),
    ("jee-advanced", "JEE (Advanced)", 3, "https://jeeadv.ac.in/", ("information brochure", "brochure"), ["exam:JEE_ADVANCED"]),
)
OFFICIAL_HOSTS = (".gov.in", ".nic.in", ".ac.in", "s3waas.gov.in")


def _year(text: str) -> str | None:
    # "2026", and the dates file names often start with ("2025020754.pdf" was put up in February 2025)
    years = [int(y) for y in re.findall(r"(?<!\d)(20[2-3]\d)(?=\b|\d{4,}\b|[-_.])", text)]
    if not years:
        return None
    y = max(years)
    return f"{y}-{str(y + 1)[2:]}"


def wanted_links(page_links: list[tuple[str, str]], words: tuple[str, ...], keep: int = 3) -> list[tuple[str, str]]:
    """PDF links on official hosts whose words say what they are, newest year first."""
    found = []
    for url, label in page_links:
        host = urlsplit(url).netloc.lower()
        said = f"{label} {url}".lower().replace("_", " ").replace("-", " ").replace("%20", " ")
        if not url.lower().split("?")[0].endswith(".pdf") or not host.endswith(OFFICIAL_HOSTS):
            continue
        if any(w in said for w in words):
            found.append((url, label))
    found.sort(key=lambda x: -(int(_year(f"{x[1]} {x[0]}")[:4]) if _year(f"{x[1]} {x[0]}") else 0))
    return list(dict.fromkeys(found))[:keep]


def run(db: Session, fetcher: Fetcher, root: Path | None = None, embedder=None) -> dict:
    root = root or loader.bundle_root()
    report = {"documents": [], "problems": []}
    log = []
    fetched = []
    for key, publisher, tier, start, words, about in PORTALS:
        home = fetcher.get(start)
        if not home.ok:
            report["problems"].append(f"{publisher}: {home.error}")
            continue
        links = extract(home.body, home.final_url, home.mime).links
        if not wanted_links(links, words):
            # The documents are often a page deeper ("Information Bulletin", "Business Rules", "Notices").
            hints = (*words, "information", "bulletin", "brochure", "business", "rules", "scheme", "notice", "document")
            site = urlsplit(home.final_url).netloc
            deeper = [u for u, label in links if urlsplit(u).netloc == site and not u.lower().endswith(".pdf")
                      and any(h in f"{label} {u}".lower() for h in hints)][:6]
            for url in dict.fromkeys(deeper):
                sub = fetcher.get(url)
                if sub.ok and (sub.mime or "").startswith("text/html"):
                    links += extract(sub.body, sub.final_url, sub.mime).links
        picks = wanted_links(links, words)
        if not picks:
            report["problems"].append(f"{publisher}: no document links found on {start}")
        for url, label in picks:
            page = fetcher.get(url)
            if not page.ok:
                report["problems"].append(f"{publisher}: {url}: {page.error}")
                continue
            doc = extract(page.body, page.final_url, page.mime, page.storage_path)
            title = " ".join((label or doc.title or url.rsplit("/", 1)[-1]).split())[:200]
            fetched.append((key, publisher, tier, about, page, doc, title))
            report["documents"].append(f"{publisher}: {title} ({len(doc.pages)} pages)")
    with bundle.locked(root):
        bundle.ensure_repo(root)
        for key, publisher, tier, about, page, doc, title in fetched:
            _, lines = documents.upsert(root, publisher_key=key, publisher=publisher, tier=tier, url=page.final_url,
                                        title=title, retrieved_at=page.retrieved_at, sha256=page.sha256, about=about,
                                        academic_year=_year(f"{title} {page.url}"), pages=len(doc.pages), scanned=doc.scanned)
            log += lines
        bundle.write_indexes(root, SECTIONS)
        bundle.append_log(root, log, datetime.now(timezone.utc).date())
        report["commit"] = bundle.commit(root, f"Official admission documents ({len(fetched)})")
        loader.load(db, root)
    report["passages"] = rag.index_bundle(db, root, fetcher.store, embedder)
    db.commit()
    return report


if __name__ == "__main__":
    from app.core.db import SessionLocal
    from app.providers.registry import get_embedding_provider

    with SessionLocal() as session, Fetcher(get_settings().source_store_path) as fetcher:
        result = run(session, fetcher, embedder=get_embedding_provider())
    print("documents:", *result["documents"], sep="\n  ")
    print("passages indexed:", result["passages"], "| commit:", result["commit"])
    print("problems:", *result["problems"], sep="\n  ")
    sys.exit(0)
