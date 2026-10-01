"""MAYA answers in the language the student spoke: English or Hindi."""

import asyncio

import pytest

from app.ai import orchestrator
from app.ai.language import (
    ENGLISH, HINDI, REPLY_INSTRUCTIONS, language_from_whisper, language_of_text,
)
from app.ai.providers import GroqSTTProvider
from app.routers import ai as ai_router


@pytest.mark.parametrize("text, expected", [
    ("Which colleges can I get with rank 5000?", ENGLISH),
    ("मुझे कौन सा कॉलेज मिल सकता है?", HINDI),
    ("IIT Delhi में JEE rank कितनी चाहिए?", HINDI),   # Hindi with English names is Hindi
    ("What does शिक्षा mean in this sentence here?", ENGLISH),  # one quoted word is not
    ("", ENGLISH),
])
def test_language_of_text(text, expected):
    assert language_of_text(text) == expected


@pytest.mark.parametrize("name, expected", [
    ("hindi", HINDI), ("Urdu", HINDI), ("english", ENGLISH), (None, ENGLISH), ("marathi", ENGLISH),
])
def test_language_from_whisper(name, expected):
    assert language_from_whisper(name) == expected


def test_groq_asks_again_for_devanagari_when_hindi_comes_back_in_urdu_script(monkeypatch):
    calls = []

    async def fake_request(self, audio_bytes, filename, language=None):
        calls.append(language)
        if language is None:
            return {"text": "مجھے کالج بتاؤ", "language": "urdu"}
        return {"text": "मुझे कॉलेज बताओ", "language": "hindi"}

    monkeypatch.setattr(GroqSTTProvider, "_request", fake_request)
    text, language = asyncio.run(GroqSTTProvider().transcribe_with_language(b"wav", "a.wav"))
    assert (text, language) == ("मुझे कॉलेज बताओ", HINDI)
    assert calls == [None, HINDI]


def test_groq_keeps_english_as_heard(monkeypatch):
    async def fake_request(self, audio_bytes, filename, language=None):
        return {"text": "Tell me about NEET", "language": "english"}

    monkeypatch.setattr(GroqSTTProvider, "_request", fake_request)
    result = asyncio.run(GroqSTTProvider().transcribe_with_language(b"wav", "a.wav"))
    assert result == ("Tell me about NEET", ENGLISH)


class _HindiSTT:
    async def transcribe_with_language(self, audio_bytes, filename):
        return "मुझे डॉक्टर बनना है", HINDI


def test_voice_chat_tells_the_model_to_reply_in_hindi(client, monkeypatch):
    token = client.post("/api/auth/register", json={
        "email": "hindi@maya-device.app", "password": "a-long-password", "name": "Asha", "class_level": 12,
    }).json()["access_token"]
    seen = {}

    class FakeLLM:
        async def chat(self, messages, tools=None):
            seen["messages"] = messages
            return {"role": "assistant", "content": "ज़रूर, NEET की तैयारी से शुरू करते हैं।"}

    monkeypatch.setattr(ai_router, "get_stt_provider", lambda: _HindiSTT())
    monkeypatch.setattr(ai_router, "get_tts_provider", lambda: None)
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: FakeLLM())

    r = client.post("/api/ai/voice-chat", headers={"Authorization": f"Bearer {token}"},
                    files={"audio": ("clip.wav", b"RIFF....WAVE", "audio/wav")})
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == HINDI
    assert body["transcript"] == "मुझे डॉक्टर बनना है"
    # The instruction sits right before the student's message, so it beats earlier turns.
    assert seen["messages"][-2] == {"role": "system", "content": REPLY_INSTRUCTIONS[HINDI]}
    assert seen["messages"][-1]["content"] == "मुझे डॉक्टर बनना है"
