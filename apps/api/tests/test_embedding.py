"""The on-device embedding model: does meaning survive a change of language?"""

import numpy as np
import pytest

from app.providers import registry

embedder = registry.get_embedding_provider()
pytestmark = pytest.mark.skipif(embedder is None, reason="embedding model not downloaded")

MEMORIES = [
    "Student likes programming and wants to build AI apps",
    "Parents want the student to take PCB and become a doctor",
    "Student finds maths, especially algebra, difficult",
    "Student lives in Pune and does not want to move far from home",
    "Student plays cricket for the school team",
]
QUERIES = [  # Hinglish, Hindi, Hinglish, English, English — each about the memory at its index
    "Mujhe coding aur AI pasand hai",
    "मेरे पापा चाहते हैं कि मैं डॉक्टर बनूँ",
    "maths mein bahut weak hoon",
    "I would prefer a college near my home city",
    "What sports do I play?",
]


def test_vectors_are_unit_length_and_the_right_size():
    v = np.array(embedder.embed(["hello"], "query"))
    assert v.shape == (1, embedder.dim) and abs(np.linalg.norm(v) - 1) < 1e-4


def test_meaning_is_found_across_english_hindi_and_hinglish():
    m = np.array(embedder.embed(MEMORIES, "passage"))
    q = np.array(embedder.embed(QUERIES, "query"))
    assert list((q @ m.T).argmax(axis=1)) == list(range(len(QUERIES)))


def test_no_texts_no_work():
    assert embedder.embed([], "query") == []
