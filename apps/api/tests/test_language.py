"""MAYA answers in the language the student spoke: English or Hindi."""

import asyncio

import pytest

from app.ai import orchestrator
from app.ai.language import (
    ENGLISH, HINDI, REPLY_INSTRUCTIONS, language_from_whisper, language_of_text,
)
from app.providers.stt import GroqWhisperSTT
from tests.fakes import FakeLLM, FakeSTT
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

    monkeypatch.setattr(GroqWhisperSTT, "_request", fake_request)
    heard = asyncio.run(_groq().transcribe(b"wav", "a.wav"))
    assert (heard.text, heard.language) == ("मुझे कॉलेज बताओ", HINDI)
    assert calls == [None, HINDI]


def test_groq_keeps_english_as_heard(monkeypatch):
    async def fake_request(self, audio_bytes, filename, language=None):
        return {"text": "Tell me about NEET", "language": "english"}

    monkeypatch.setattr(GroqWhisperSTT, "_request", fake_request)
    heard = asyncio.run(_groq().transcribe(b"wav", "a.wav"))
    assert (heard.text, heard.language) == ("Tell me about NEET", ENGLISH)


def _groq():
    return GroqWhisperSTT("https://groq.invalid/openai/v1", "key", "whisper-large-v3")


def test_voice_chat_tells_the_model_to_reply_in_hindi(client, monkeypatch):
    token = client.post("/api/auth/register", json={
        "email": "hindi@maya-device.app", "password": "a-long-password", "name": "Asha", "class_level": 12,
    }).json()["access_token"]
    llm = FakeLLM("ज़रूर, NEET की तैयारी से शुरू करते हैं।")
    monkeypatch.setattr(ai_router, "get_stt_provider", lambda: FakeSTT("मुझे डॉक्टर बनना है", HINDI))
    monkeypatch.setattr(ai_router, "get_tts_provider", lambda: None)
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)

    r = client.post("/api/ai/voice-chat", headers={"Authorization": f"Bearer {token}"},
                    files={"audio": ("clip.wav", b"RIFF....WAVE", "audio/wav")})
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == HINDI
    assert body["transcript"] == "मुझे डॉक्टर बनना है"
    # The instruction sits right before the student's message, so it beats earlier turns.
    assert llm.seen[0][-2] == {"role": "system", "content": REPLY_INSTRUCTIONS[HINDI]}
    assert llm.seen[0][-1]["content"] == "मुझे डॉक्टर बनना है"
