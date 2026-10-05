"""Finding a student's memories by meaning, then weighing how recent and how important each is.

On PostgreSQL the search is pgvector's cosine distance over an HNSW index; on SQLite (tests) the
same ranking is computed in Python. Either way the student filter comes first, in SQL: one
student's question can never reach another student's memories.

Ranking (spec §7: relevance + recency + importance; docs/design/03-memory-schema.md): the nearest
CANDIDATES by meaning are re-ordered by

    score = similarity + RECENCY_WEIGHT * recency + IMPORTANCE_WEIGHT * salience

with recency halving every RECENCY_HALF_LIFE_DAYS since the memory was written (one said again gets more
salience from the writer instead: updated_at also moves whenever a memory is merely used). Meaning stays
first: this embedding model's similarities sit close together (relevant ~0.82-0.89, unrelated up to
~0.81), so the two bonuses together are worth at most 0.06 — enough to prefer what's recent and
said more than once among memories about as relevant, never enough to bring up an unrelated one.
The similarity returned is the raw one, which is what the privacy threshold in retrieval.py uses.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, literal, select
from sqlalchemy.orm import Session

from app.models.memory import EMBEDDING_DIM, MemoryItem

CANDIDATES = 4  # times k, fetched by meaning before re-ranking
RECENCY_WEIGHT = 0.03
IMPORTANCE_WEIGHT = 0.03
RECENCY_HALF_LIFE_DAYS = 90


def recency(item: MemoryItem, now: datetime) -> float:
    """1.0 for a memory written today, 0.5 after RECENCY_HALF_LIFE_DAYS."""
    when = item.created_at
    if when is None:
        return 1.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - when).total_seconds() / 86400)
    return math.pow(0.5, days / RECENCY_HALF_LIFE_DAYS)


def score(item: MemoryItem, similarity: float, now: datetime) -> float:
    return similarity + RECENCY_WEIGHT * recency(item, now) + IMPORTANCE_WEIGHT * (item.salience or 0.0)


def _nearest(db: Session, q, query: list[float], limit: int) -> list[tuple[MemoryItem, float]]:
    if db.get_bind().dialect.name == "postgresql":
        distance = MemoryItem.embedding.op("<=>", return_type=Float)(literal(query, Vector(EMBEDDING_DIM)))
        rows = db.execute(q.add_columns(distance).order_by(distance).limit(limit)).all()
        return [(item, 1.0 - float(d)) for item, d in rows]

    items = db.execute(q).scalars().all()
    if not items:
        return []
    vectors = np.array([item.embedding for item in items], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    target = np.asarray(query, dtype=np.float32)
    similarities = vectors @ (target / np.linalg.norm(target))
    order = np.argsort(-similarities)[:limit]
    return [(items[i], float(similarities[i])) for i in order]


def search_memories(db: Session, student_id: int, query: list[float], k: int = 5,
                    include_sensitive: bool = False, now: datetime | None = None,
                    rerank: bool = True) -> list[tuple[MemoryItem, float]]:
    """The student's k best active memories for `query`: closest in meaning, with recent and important
    ones preferred among the near-equal (see above). Each with its cosine similarity. rerank=False is
    meaning alone — for finding a duplicate."""
    q = select(MemoryItem).where(
        MemoryItem.student_profile_id == student_id,
        MemoryItem.status == "active",
        MemoryItem.embedding.is_not(None),
    )
    if not include_sensitive:
        q = q.where(MemoryItem.sensitivity == "normal")
    if not rerank:
        return _nearest(db, q, query, k)
    now = now or datetime.now(timezone.utc)
    found = _nearest(db, q, query, k * CANDIDATES)
    return sorted(found, key=lambda pair: -score(pair[0], pair[1], now))[:k]
