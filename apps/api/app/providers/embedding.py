"""Turning text into vectors that sit close together when they mean the same thing — across
English, Hindi and Hinglish — so MAYA can find "everything about Python" in a student's memory.

Computed on the Pi (decision 2026-10-01): multilingual-e5-small, int8-quantised ONNX, run with
ONNX Runtime — ~6 ms a sentence, so students' memories never leave the device to be indexed.
Measured: Hinglish, Devanagari and English paraphrases each find the matching memory.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

import numpy as np

Kind = Literal["query", "passage"]


class EmbeddingProvider(ABC):
    model_id: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        """Unit-length vectors. "query" for what's being looked for, "passage" for what's stored."""


class LocalE5Embedding(EmbeddingProvider):
    """e5 wants each text prefixed with what it is ("query: …" / "passage: …"), mean-pooled over
    the real tokens and L2-normalised; then cosine similarity is a dot product."""

    model_id = "multilingual-e5-small-int8"
    dim = 384
    MAX_TOKENS = 256

    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self._session = None
        self._tokenizer = None
        self._lock = threading.Lock()

    @staticmethod
    def available(model_dir: Path) -> bool:
        return (model_dir / "model_quantized.onnx").is_file() and (model_dir / "tokenizer.json").is_file()

    def _load(self) -> None:
        # ~0.5 s and ~300 MB, so only on first use.
        import onnxruntime as ort
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        tokenizer.enable_truncation(self.MAX_TOKENS)
        tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self._session = ort.InferenceSession(str(self.model_dir / "model_quantized.onnx"), options,
                                             providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._tokenizer = tokenizer

    def embed(self, texts, kind):
        if not texts:
            return []
        with self._lock:
            if self._session is None:
                self._load()
        encoded = self._tokenizer.encode_batch([f"{kind}: {t}" for t in texts])
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]
        pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
        pooled /= np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled.astype(np.float32).tolist()
