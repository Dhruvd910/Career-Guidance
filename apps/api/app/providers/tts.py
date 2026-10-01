"""Text to speech. Cartesia is MAYA's voice: if it's unconfigured or failing, callers get no
audio and fall back to on-screen text — there is deliberately no lesser offline voice.

`synthesize()` returns one compressed clip (MP3) for one-off lines; `stream()` returns raw
16-bit PCM as it is generated, for the sentence-by-sentence conversation pipeline — the edge
can play it as it arrives, with no decoding step in between.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from app.ai.language import language_of_text
from app.providers.http import ProviderError, client_for, send

TTS_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
CARTESIA_VERSION = "2026-08-14"


class TTSProvider(ABC):
    sample_rate: int  # of stream()'s PCM: mono, signed 16-bit little-endian

    @abstractmethod
    async def synthesize(self, text: str, language: str | None = None) -> tuple[bytes, str] | None:
        """(audio_bytes, content_type) for the whole text, or None if synthesis is unavailable."""

    @abstractmethod
    def stream(self, text: str, language: str | None = None) -> AsyncIterator[bytes]:
        """Raw PCM chunks as they're generated, each a whole number of samples."""


class CartesiaTTS(TTSProvider):
    def __init__(self, base_url: str, api_key: str, voice_id: str, model: str, *, sample_rate: int = 44100,
                 name: str = "tts", client: httpx.AsyncClient | None = None):
        self.base_url, self._api_key, self.voice_id, self.model = base_url, api_key, voice_id, model
        self.sample_rate, self.name, self._client = sample_rate, name, client

    def _build(self, text: str, language: str | None, output_format: dict):
        http = self._client or client_for(self.base_url)
        body = {
            "model_id": self.model,
            "transcript": text,
            # Without an explicit language the reply's own script picks it: Devanagari is read
            # in Hindi, everything else in English.
            "language": language or language_of_text(text),
            "voice": self.voice_id,
            "output_format": output_format,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Cartesia-Version": CARTESIA_VERSION,
                   "Content-Type": "application/json"}
        return http, lambda: http.build_request("POST", "tts/bytes", json=body, headers=headers, timeout=TTS_TIMEOUT)

    async def synthesize(self, text, language=None):
        http, build = self._build(text, language, {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000})
        response = await send(http, build, provider=self.name)
        return response.content, "audio/mpeg"

    async def stream(self, text, language=None):
        http, build = self._build(text, language, {"container": "raw", "encoding": "pcm_s16le",
                                                   "sample_rate": self.sample_rate})
        response = await send(http, build, provider=self.name, stream=True)
        carry = b""
        try:
            async for chunk in response.aiter_bytes():
                chunk = carry + chunk
                # Network chunks can split a 2-byte sample; hold the odd byte for the next one.
                whole = len(chunk) - len(chunk) % 2
                carry = chunk[whole:]
                if whole:
                    yield chunk[:whole]
        except httpx.HTTPError as e:
            raise ProviderError(self.name, f"stream broke off: {type(e).__name__}: {e}") from e
        finally:
            await response.aclose()
