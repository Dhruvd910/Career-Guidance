"""Official documents, searchable by meaning and by words (docs/design/05-rag-pipeline.md; 15-phase6-plan.md
Step 6). RAG answers "what does this document say" — eligibility rules, how counselling works,
what a prospectus says about the hostel. Numbers that change (fees, dates) come from facts: a fee
or date in a passage is quoted with its document and date, never restated as current (P6-10).

- **Chunks:** a page at a time, split at headings and blank lines into ~1,400-character passages
  (within e5's 512-token limit) with a little overlap; a line is never split.
- **Embeddings:** the Pi's own multilingual e5, so Hindi and Hinglish questions find English
  documents.
- **Search:** hybrid — nearest by meaning (pgvector) and by words (Postgres full text), merged
  by reciprocal rank. On SQLite (the tests) the same in Python.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.ingest.text import Extracted
from app.models.facts import DocChunk, SourceDocument
from app.providers.embedding import EmbeddingProvider

TARGET, OVERLAP = 1400, 200


def _heading(line: str) -> bool:
    s = line.strip()
    return 3 < len(s) < 90 and not s.endswith((".", ",", ";")) and (s.isupper() or bool(re.match(r"^(\d+(\.\d+)*|[IVX]+\.|[A-Z]\.)\s+\S", s)))


@dataclass
class Passage:
    text: str
    page: int | None
    section: str | None


def chunk(doc: Extracted) -> list[Passage]:
    out: list[Passage] = []
    pages = doc.pages if doc.kind == "pdf" else [doc.text]
    for number, page in enumerate(pages, start=1):
        section, buffer = None, []

        def flush():
            body = "\n".join(buffer).strip()
            if len(body) > 40:
                out.append(Passage(body, number if doc.kind == "pdf" else None, section))

        for line in page.split("\n"):
            if _heading(line) and sum(len(b) for b in buffer) > TARGET // 3:
                flush()
                buffer = []
            if _heading(line):
                section = line.strip()[:200]
            buffer.append(line)
            if sum(len(b) + 1 for b in buffer) >= TARGET:
                flush()
                tail, size = [], 0
                for b in reversed(buffer):
                    if size + len(b) > OVERLAP:
                        break
                    tail.insert(0, b)
                    size += len(b) + 1
                buffer = tail
        flush()
    return out


def index(db: Session, document: SourceDocument, doc: Extracted, embedder: EmbeddingProvider | None,
          entity_refs: list[str] | None = None, lang: str = "en") -> int:
    """(Re)builds a document's passages. Returns how many."""
    db.execute(delete(DocChunk).where(DocChunk.source_document_id == document.id))
    passages = chunk(doc)
    vectors = embedder.embed([p.text for p in passages], "passage") if embedder and passages else [None] * len(passages)
    for seq, (p, v) in enumerate(zip(passages, vectors)):
        db.add(DocChunk(source_document_id=document.id, seq=seq, section=p.section, page=p.page, text=p.text, lang=lang,
                        entity_refs=entity_refs or document.entity_refs or [], academic_year=document.academic_year,
                        embedding=v, embed_model=getattr(embedder, "model_id", None) if v else None))
    db.flush()
    return len(passages)


def _rrf(*rankings: list[int], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda i: -scores[i])


def _words(q: str) -> set[str]:
    return {w for w in re.findall(r"[\wऀ-ॿ]+", q.lower()) if len(w) > 2}


def search(db: Session, query: str, embedder: EmbeddingProvider | None, entity: str | None = None, limit: int = 6) -> list[dict]:
    """The passages that best answer `query`, each with its document's title, publisher, tier,
    address, page and when it was fetched. `entity` ("college:412", "exam:2") narrows to one."""
    vector = embedder.embed([query], "query")[0] if embedder else None
    current = select(DocChunk.id).join(SourceDocument).where(SourceDocument.superseded_by.is_(None))
    if db.bind.dialect.name == "postgresql":
        where = "d.superseded_by IS NULL" + (" AND c.entity_refs ? :entity" if entity else "")
        params = {"q": query, "entity": entity}
        by_words = [r[0] for r in db.execute(text(
            f"SELECT c.id FROM doc_chunks c JOIN source_documents d ON d.id = c.source_document_id WHERE {where} "
            "AND to_tsvector('simple', c.text) @@ plainto_tsquery('simple', :q) "
            "ORDER BY ts_rank(to_tsvector('simple', c.text), plainto_tsquery('simple', :q)) DESC LIMIT 30"), params)]
        by_meaning = []
        if vector is not None:
            by_meaning = [r[0] for r in db.execute(text(
                f"SELECT c.id FROM doc_chunks c JOIN source_documents d ON d.id = c.source_document_id WHERE {where} "
                "AND c.embedding IS NOT NULL ORDER BY c.embedding <=> CAST(:v AS vector) LIMIT 30"),
                {**params, "v": str(vector)})]
    else:
        rows = db.execute(select(DocChunk).where(DocChunk.id.in_(current))).scalars().all()
        if entity:
            rows = [r for r in rows if entity in (r.entity_refs or [])]
        wanted = _words(query)
        by_words = [r.id for r in sorted(rows, key=lambda r: -len(wanted & _words(r.text))) if wanted & _words(r.text)][:30]

        def cos(a, b):
            return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)

        by_meaning = [r.id for r in sorted((r for r in rows if r.embedding and vector), key=lambda r: -cos(r.embedding, vector))][:30]
    ids = _rrf(by_meaning, by_words)[:limit]
    chunks = {c.id: c for c in db.execute(select(DocChunk).where(DocChunk.id.in_(ids))).scalars()}
    out = []
    for i in ids:
        c = chunks[i]
        d = c.document
        out.append({"text": c.text, "page": c.page, "section": c.section, "document": d.title, "url": d.url,
                    "publisher": d.source.name, "tier": d.source.tier, "official": d.source.tier <= 4,
                    "retrieved": d.retrieved_at.date().isoformat() if d.retrieved_at else None,
                    "academic_year": c.academic_year, "chunk_id": c.id})
    return out


def index_bundle(db: Session, root, store_dir, embedder: EmbeddingProvider | None) -> int:
    """Indexes every Official Document in the OKF bundle that isn't indexed yet, reading its raw
    file (kept by sha256) again. Returns how many passages were added."""
    from pathlib import Path

    from app.ingest.text import extract
    from app.okf import documents
    from app.okf.loader import document_row

    added = 0
    for concept in documents.documents(Path(root)):
        row = document_row(db, concept)
        if db.execute(select(DocChunk.id).where(DocChunk.source_document_id == row.id).limit(1)).first():
            continue
        sha = row.sha256 or ""
        raw = next(iter(sorted((Path(store_dir) / sha[:2]).glob(f"{sha}.*"))), None) if sha else None
        if raw is None:
            continue
        doc = extract(raw.read_bytes(), row.url, "application/pdf" if raw.suffix == ".pdf" else "text/html", str(raw))
        about = (concept.meta.get("maya") or {}).get("document", {}).get("about") or []
        added += index(db, row, doc, embedder, entity_refs=about)
    return added
