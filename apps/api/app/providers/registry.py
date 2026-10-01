"""Builds the configured provider for each AI service. Swapping a provider is a config change
(LLM_PROVIDER, STT_PROVIDER, TTS_PROVIDER); adding a new kind is a new class plus a branch here.

Each getter returns None when its service isn't configured, and callers degrade gracefully:
no LLM → a plain "not configured" reply, no STT → typing only, no TTS → on-screen text.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.providers.embedding import EmbeddingProvider, LocalE5Embedding
from app.providers.llm import LLMProvider, OpenAICompatibleLLM
from app.providers.stt import GroqWhisperSTT, STTProvider
from app.providers.tts import CartesiaTTS, TTSProvider

settings = get_settings()


def get_llm_provider() -> LLMProvider | None:
    if settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key:
            return None
        return OpenAICompatibleLLM(settings.openrouter_base_url, settings.openrouter_model,
                                   settings.openrouter_api_key, name="openrouter")
    if settings.llm_provider == "openai_compatible":
        if not (settings.llm_base_url and settings.llm_model):
            return None
        return OpenAICompatibleLLM(settings.llm_base_url, settings.llm_model, settings.llm_api_key,
                                   name="openai_compatible")
    raise ValueError(f"Unknown LLM_PROVIDER {settings.llm_provider!r}")


def get_stt_provider() -> STTProvider | None:
    if settings.stt_provider == "none":
        return None
    if settings.stt_provider == "groq":
        if not settings.groq_api_key:
            return None
        return GroqWhisperSTT(settings.groq_base_url, settings.groq_api_key, settings.groq_stt_model, name="groq")
    raise ValueError(f"Unknown STT_PROVIDER {settings.stt_provider!r}")


def get_tts_provider() -> TTSProvider | None:
    if settings.tts_provider == "none":
        return None
    if settings.tts_provider == "cartesia":
        if not (settings.cartesia_api_key and settings.cartesia_voice_id):
            return None
        return CartesiaTTS(settings.cartesia_base_url, settings.cartesia_api_key, settings.cartesia_voice_id,
                           settings.cartesia_model, sample_rate=settings.tts_sample_rate, name="cartesia")
    raise ValueError(f"Unknown TTS_PROVIDER {settings.tts_provider!r}")


_embedders: dict[str, EmbeddingProvider] = {}


def get_embedding_provider() -> EmbeddingProvider | None:
    """One instance per model: loading it costs ~0.5 s and ~300 MB. None when the model isn't
    downloaded — memory then falls back to recency instead of meaning."""
    if settings.embedding_provider == "none":
        return None
    if settings.embedding_provider == "local_e5":
        model_dir = Path(settings.embedding_model_dir)
        if not LocalE5Embedding.available(model_dir):
            return None
        key = str(model_dir.resolve())
        if key not in _embedders:
            _embedders[key] = LocalE5Embedding(model_dir)
        return _embedders[key]
    raise ValueError(f"Unknown EMBEDDING_PROVIDER {settings.embedding_provider!r}")
