"""Provider abstraction (spec §29/§47): the rest of the app talks to `LLMProvider`,
`STTProvider`, `TTSProvider` interfaces, never to OpenRouter/Groq/Cartesia directly, so
any one can be swapped by adding a new subclass — no caller changes.

OpenRouter and Groq are verified against live keys. Cartesia is MAYA's only voice: if it's
unconfigured or failing, callers get no audio and fall back to on-screen text.
"""

import base64
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.ai.language import HINDI, has_devanagari, language_from_whisper, language_of_text
from app.core.config import get_settings

settings = get_settings()


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Returns an OpenAI-style choice message dict: {role, content, tool_calls?}."""


class STTProvider(ABC):
    async def transcribe_with_language(self, audio_bytes: bytes, filename: str) -> tuple[str, str]:
        """The transcript and the language it was spoken in ("en" or "hi")."""
        text = await self.transcribe(audio_bytes, filename)
        return text, language_of_text(text)

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        """Returns the transcribed text."""


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> tuple[bytes, str] | None:
        """Returns (audio_bytes, content_type), or None if synthesis is unavailable."""


class OpenRouterProvider(LLMProvider):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": settings.openrouter_model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]


class GroqSTTProvider(STTProvider):
    async def _request(self, audio_bytes: bytes, filename: str, language: str | None = None) -> dict:
        data = {"model": settings.groq_stt_model, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.groq_base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                data=data,
                files={"file": (filename, audio_bytes)},
            )
            response.raise_for_status()
            return response.json()

    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        return (await self.transcribe_with_language(audio_bytes, filename))[0]

    async def transcribe_with_language(self, audio_bytes: bytes, filename: str) -> tuple[str, str]:
        result = await self._request(audio_bytes, filename)
        language = language_from_whisper(result.get("language"))
        text = result["text"]
        if language == HINDI and not has_devanagari(text):
            # Whisper hears Hindi but often writes it in Urdu script or English letters.
            # Asked again with the language pinned, it writes Devanagari, which the chat
            # model and the Hindi voice both need.
            text = (await self._request(audio_bytes, filename, language=HINDI))["text"]
        return text, language


class CartesiaTTSProvider(TTSProvider):
    async def synthesize(self, text: str) -> tuple[bytes, str] | None:
        if not settings.cartesia_voice_id:
            return None
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.cartesia_base_url}/tts/bytes",
                headers={
                    "Authorization": f"Bearer {settings.cartesia_api_key}",
                    "Cartesia-Version": "2026-08-14",
                    "Content-Type": "application/json",
                },
                json={
                    "model_id": settings.cartesia_model,
                    "transcript": text,
                    # The reply's own script picks the voice's language: Devanagari is read
                    # in Hindi, everything else in English.
                    "language": language_of_text(text),
                    "voice": settings.cartesia_voice_id,
                    "output_format": {
                        "container": "mp3",
                        "sample_rate": 44100,
                        "bit_rate": 128000,
                    },
                },
            )
            response.raise_for_status()
            return response.content, "audio/mpeg"


def audio_to_base64(audio_bytes: bytes) -> str:
    return base64.b64encode(audio_bytes).decode("utf-8")


def get_llm_provider() -> LLMProvider | None:
    if not settings.openrouter_api_key:
        return None
    return OpenRouterProvider()


def get_stt_provider() -> STTProvider | None:
    if not settings.groq_api_key:
        return None
    return GroqSTTProvider()


def get_tts_provider() -> TTSProvider | None:
    if not (settings.cartesia_api_key and settings.cartesia_voice_id):
        return None
    return CartesiaTTSProvider()
