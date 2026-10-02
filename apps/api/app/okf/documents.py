"""Official documents as OKF concepts — `documents/<publisher>/<name>.md`, type "Official
Document": what it is, who published it (with the tier), where it lives, which version (sha256)
and when it was fetched, and what it's about (an exam, a college). The search index (app/rag.py)
is built from these and the raw files kept by sha256, so it can always be rebuilt from the bundle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.okf import bundle
from app.okf.bundle import Concept
from app.okf.facts import _iso, slug, when

TYPE = "Official Document"


def concept_id(publisher_key: str, url: str, title: str) -> str:
    """Its title and its file's name — two documents may share a title ("Information Bulletin")."""
    file = slug(url.split("?")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0])[:40]
    name = "-".join(x for x in (slug(title)[:50], file) if x) or "document"
    return f"documents/{slug(publisher_key)}/{name}"


def upsert(root: Path, *, publisher_key: str, publisher: str, tier: int, url: str, title: str, retrieved_at: datetime,
           sha256: str, about: list[str], academic_year: str | None = None, pages: int | None = None,
           scanned: bool = False, now: datetime | None = None) -> tuple[str, list[str]]:
    """Writes (or updates) a document's concept; returns its id and log lines."""
    now = now or datetime.now(timezone.utc)
    cid = concept_id(publisher_key, url, title)
    old = bundle.read(root, cid)
    meta = {
        "type": TYPE, "title": title, "description": f"{publisher}: {title}", "resource": url,
        "tags": sorted({slug(publisher_key), *([academic_year] if academic_year else [])}), "status": "stable",
        "generated": {"by": "maya-documents/1", "at": _iso(now)},
        "verified": [{"by": "process:maya-fetch", "at": _iso(retrieved_at)}],
        "stale_after": _iso(when(_iso(retrieved_at)) + timedelta(days=400)),
        "sources": [{"id": "s1", "resource": url, "title": title, "author": f"org:{publisher_key}", "publisher": publisher,
                     "tier": tier, "retrieved_at": _iso(retrieved_at), "sha256": sha256}],
        "maya": {"document": {"sha256": sha256, "about": sorted(about), "academic_year": academic_year, "pages": pages,
                              "scanned": scanned}},
    }
    body = (f"# {title}\n\nPublished by {publisher} (tier {tier}); fetched {_iso(retrieved_at)[:10]}"
            + (f"; {pages} pages" if pages else "") + (", scanned" if scanned else "") + ".\n\n"
            f"Read it at [{url}]({url}).[^s1]\n\n[^s1]: {title}, {publisher}\n")
    if old:  # unchanged apart from when this ran: leave it as it is
        same = {k: v for k, v in old.meta.items() if k != "generated"} == {k: v for k, v in meta.items() if k != "generated"}
        if same:
            return cid, []
    bundle.write(root, Concept(cid, meta, body))
    verb = "Update" if old else "Creation"
    return cid, [f"**{verb}**: [{title}](/{cid}.md), from {publisher}"]


def documents(root: Path):
    for concept in bundle.concepts(root, "documents") if (root / "documents").exists() else []:
        if concept.type == TYPE:
            yield concept
