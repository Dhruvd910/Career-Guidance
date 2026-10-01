"""Speech to text. Groq-hosted Whisper today.

Besides the words, a Transcript says how sure Whisper was and how likely the clip held no
speech at all — Whisper is known to "hear" phrases like "Thank you." in silence or fan noise,
and those two numbers are what lets a caller throw such a transcript away.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.ai.language import HINDI, has_devanagari, language_from_whisper
from app.providers.http import client_for, send

STT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str  # what was heard: "en" or "hi"
    confidence: float | None = None  # 0..1, from Whisper's average log-probability
    no_speech_prob: float | None = None  # 0..1, the most doubtful segment's
    duration_ms: int | None = None


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, filename: str) -> Transcript:
        ...


class GroqWhisperSTT(STTProvider):
    def __init__(self, base_url: str, api_key: str, model: str, *, name: str = "stt",
                 client: httpx.AsyncClient | None = None):
        self.base_url, self._api_key, self.model, self.name = base_url, api_key, model, name
        self._client = client

    async def _request(self, audio_bytes: bytes, filename: str, language: str | None = None) -> dict:
        http = self._client or client_for(self.base_url)
        data = {"model": self.model, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        response = await send(http, lambda: http.build_request(
            "POST", "audio/transcriptions", headers={"Authorization": f"Bearer {self._api_key}"},
            data=data, files={"file": (filename, audio_bytes)}, timeout=STT_TIMEOUT,
        ), provider=self.name)
        return response.json()

    async def transcribe(self, audio_bytes: bytes, filename: str) -> Transcript:
        result = await self._request(audio_bytes, filename)
        language = language_from_whisper(result.get("language"))
        if language == HINDI and not has_devanagari(result.get("text", "")):
            # Whisper hears Hindi but often writes it in Urdu script or English letters.
            # Asked again with the language pinned, it writes Devanagari, which the chat
            # model and the Hindi voice both need.
            result = await self._request(audio_bytes, filename, language=HINDI)
        return _transcript(result, language)


def _transcript(result: dict, language: str) -> Transcript:
    segments = result.get("segments") or []
    logprobs = [s["avg_logprob"] for s in segments if isinstance(s.get("avg_logprob"), (int, float))]
    no_speech = [s["no_speech_prob"] for s in segments if isinstance(s.get("no_speech_prob"), (int, float))]
    duration = result.get("duration")
    return Transcript(
        text=result.get("text", ""),
        language=language,
        confidence=math.exp(sum(logprobs) / len(logprobs)) if logprobs else None,
        no_speech_prob=max(no_speech) if no_speech else None,
        duration_ms=int(duration * 1000) if isinstance(duration, (int, float)) else None,
    )
