"""Finding a student's memories by meaning.

On PostgreSQL the search is pgvector's cosine distance over an HNSW index; on SQLite (tests) the
same ranking is computed in Python. Either way the student filter comes first, in SQL: one
student's question can never reach another student's memories.
"""

from __future__ import annotations

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, literal, select
from sqlalchemy.orm import Session

from app.models.memory import EMBEDDING_DIM, MemoryItem


def search_memories(db: Session, student_id: int, query: list[float], k: int = 5,
                    include_sensitive: bool = False) -> list[tuple[MemoryItem, float]]:
    """The student's k active memories closest in meaning to `query`, with cosine similarity."""
    q = select(MemoryItem).where(
        MemoryItem.student_profile_id == student_id,
        MemoryItem.status == "active",
        MemoryItem.embedding.is_not(None),
    )
    if not include_sensitive:
        q = q.where(MemoryItem.sensitivity == "normal")

    if db.get_bind().dialect.name == "postgresql":
        distance = MemoryItem.embedding.op("<=>", return_type=Float)(literal(query, Vector(EMBEDDING_DIM)))
        rows = db.execute(q.add_columns(distance).order_by(distance).limit(k)).all()
        return [(item, 1.0 - float(d)) for item, d in rows]

    items = db.execute(q).scalars().all()
    if not items:
        return []
    vectors = np.array([item.embedding for item in items], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    target = np.asarray(query, dtype=np.float32)
    similarities = vectors @ (target / np.linalg.norm(target))
    order = np.argsort(-similarities)[:k]
    return [(items[i], float(similarities[i])) for i in order]
