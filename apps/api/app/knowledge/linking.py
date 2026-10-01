"""Linking what a student told MAYA ("robotics", "becoming a doctor", "इंजीनियरिंग") to the career
graph — so a remembered interest can become a reason on a career.

Two ways, careful first:

1. **Names and aliases.** "doctor" is an alias of career:mbbs; short ones ("AI", "IT", "CA") must
   match exactly as written, so "I like it" isn't IT.
2. **Meaning**, with the on-device embedding model (Phase 2's multilingual e5), only to careers,
   domains and subjects, and only at `SIMILARITY` or above.

The threshold was calibrated on the Pi (2026-10-01): true matches ("robotics" → Robotics, "AI /
machine learning" → AI & Data, "इंजीनियरिंग" → Engineering) scored 0.87–0.92. Unrelated interests
("music", "K-pop", "video games") reached 0.85 against something, one wrong near-miss reached 0.86
("space and rockets" → spatial visualisation) and another 0.870 ("AI" → Science & Research) —
hence 0.875, skills left out, and no meaning matches at all once a name has matched.
"""

from __future__ import annotations

import re
import threading

import numpy as np

from app.knowledge.graph_store import GraphStore
from app.providers.embedding import EmbeddingProvider

LINK_TYPES = ("career", "domain", "subject")
SIMILARITY = 0.875
SHORT_ALIAS = 3  # aliases this short must match exactly as written ("IT", "CA", "AI")

_cache: dict[tuple, tuple[list[str], np.ndarray]] = {}
_lock = threading.Lock()


def _phrases(node: dict, aliases: list[str]) -> list[str]:
    return [node["name"]["en"], node["name"]["hi"], *aliases]


def _lexical(text: str, candidates: list[tuple[str, list[str]]]) -> list[str]:
    lowered = text.lower()
    found = []
    for key, phrases in candidates:
        for phrase in phrases:
            if len(phrase) <= SHORT_ALIAS:
                hit = re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text)  # as written
            else:
                hit = re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", lowered)
            if hit:
                found.append(key)
                break
    return found


def _vectors(store: GraphStore, embedder: EmbeddingProvider, version: int | None) -> tuple[list[str], np.ndarray]:
    cache_key = (version, getattr(embedder, "model_id", "?"))
    with _lock:
        if cache_key not in _cache:
            nodes = [n for t in LINK_TYPES for n in store.of_type(t)]
            aliases = _aliases(store, [n["key"] for n in nodes])
            texts = [n["name"]["en"] + (f" ({', '.join(aliases[n['key']])})" if aliases[n["key"]] else "") for n in nodes]
            _cache.clear()
            _cache[cache_key] = ([n["key"] for n in nodes], np.array(embedder.embed(texts, "passage"), dtype=np.float32))
        return _cache[cache_key]


def _aliases(store: GraphStore, keys: list[str]) -> dict[str, list[str]]:
    from sqlalchemy import select

    from app.models.knowledge import KgNode

    rows = store.db.execute(select(KgNode.key, KgNode.aliases).where(KgNode.key.in_(keys))).all()
    return {k: list(a or []) for k, a in rows}


def link(store: GraphStore, texts: list[str], embedder: EmbeddingProvider | None, version: int | None = None) -> list[list[dict]]:
    """For each text, the graph nodes it refers to: [{key, type, name, how: "name"|"meaning", score}]."""
    nodes = {n["key"]: n for t in LINK_TYPES for n in store.of_type(t)}
    aliases = _aliases(store, list(nodes))
    candidates = [(k, _phrases(n, aliases[k])) for k, n in nodes.items()]
    out: list[list[dict]] = []
    meaning = None
    if embedder is not None and texts:
        keys, matrix = _vectors(store, embedder, version)
        sims = np.array(embedder.embed(texts, "query"), dtype=np.float32) @ matrix.T
        meaning = (keys, sims)
    for i, text in enumerate(texts):
        found = {k: {"key": k, "type": nodes[k]["type"], "name": nodes[k]["name"], "how": "name", "score": 1.0}
                 for k in _lexical(text, candidates)}
        if meaning is not None and not found:  # a name match is the better evidence
            keys, sims = meaning
            for j in np.argsort(-sims[i])[:3]:
                if sims[i][j] >= SIMILARITY and keys[j] not in found:
                    found[keys[j]] = {"key": keys[j], "type": nodes[keys[j]]["type"], "name": nodes[keys[j]]["name"],
                                      "how": "meaning", "score": round(float(sims[i][j]), 3)}
        out.append(sorted(found.values(), key=lambda f: -f["score"]))
    return out
