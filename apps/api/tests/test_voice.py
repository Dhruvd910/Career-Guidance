import pytest
from fastapi.testclient import TestClient

from app.ai import providers
from app.ai.providers import TTSProvider
from app.core.db import get_db
from app.main import app
from app.routers import ai as ai_router


def _with_client_host(asgi_app, host: str):
    """TestClient reports every caller as 'testclient'; rewrite the ASGI scope so the real
    require_local_or_authenticated dependency sees a specific caller address."""
    async def wrapped(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = dict(scope, client=(host, 50000))
        await asgi_app(scope, receive, send)
    return wrapped


@pytest.fixture()
def client_from(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    clients = []

    def make(host: str) -> TestClient:
        c = TestClient(_with_client_host(app, host))
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()
    app.dependency_overrides.clear()


class _FakeSTT:
    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        return "  My name is Dhruv.  "


class _FakeTTS(TTSProvider):
    async def synthesize(self, text: str):
        return b"RIFFfake", "audio/wav"


@pytest.fixture()
def fake_voice(monkeypatch):
    monkeypatch.setattr(ai_router, "get_stt_provider", lambda: _FakeSTT())
    monkeypatch.setattr(ai_router, "get_tts_provider", lambda: _FakeTTS())


AUDIO_FILE = {"audio": ("clip.wav", b"RIFF....WAVE", "audio/wav")}


# ---- the auth rule: loopback may skip login, the network may not ----

def test_transcribe_allowed_from_loopback_without_token(client_from, fake_voice):
    r = client_from("127.0.0.1").post("/api/ai/transcribe", files=AUDIO_FILE)
    assert r.status_code == 200
    assert r.json() == {"transcript": "My name is Dhruv."}


def test_transcribe_allowed_from_ipv6_loopback_without_token(client_from, fake_voice):
    r = client_from("::1").post("/api/ai/transcribe", files=AUDIO_FILE)
    assert r.status_code == 200


def test_transcribe_rejected_from_lan_without_token(client_from, fake_voice):
    r = client_from("192.168.1.50").post("/api/ai/transcribe", files=AUDIO_FILE)
    assert r.status_code == 401


def test_transcribe_allowed_from_lan_with_valid_token(client_from, fake_voice):
    lan = client_from("192.168.1.50")
    token = lan.post(
        "/api/auth/register",
        json={"email": "voice@example.com", "password": "password123", "name": "V", "class_level": 11},
    ).json()["access_token"]
    r = lan.post("/api/ai/transcribe", files=AUDIO_FILE, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_transcribe_rejected_from_lan_with_forged_token(client_from, fake_voice):
    r = client_from("192.168.1.50").post(
        "/api/ai/transcribe", files=AUDIO_FILE, headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


def test_speak_allowed_from_loopback_without_token(client_from, fake_voice):
    r = client_from("127.0.0.1").post("/api/ai/speak", json={"text": "Good morning!"})
    assert r.status_code == 200
    body = r.json()
    assert body["tts_configured"] is True
    assert body["audio_base64"] is not None


def test_speak_rejected_from_lan_without_token(client_from, fake_voice):
    r = client_from("10.0.0.7").post("/api/ai/speak", json={"text": "Good morning!"})
    assert r.status_code == 401


def test_chat_still_requires_login_even_from_loopback(client_from, fake_voice):
    # Only the pre-account voice endpoints were opened up — chat touches personal data.
    r = client_from("127.0.0.1").post("/api/ai/chat", json={"message": "hi"})
    assert r.status_code == 401


# ---- TTS configuration ----

def test_no_tts_provider_without_cartesia_key(monkeypatch):
    monkeypatch.setattr(providers.settings, "cartesia_api_key", None)
    assert providers.get_tts_provider() is None


def test_no_tts_provider_without_cartesia_voice(monkeypatch):
    monkeypatch.setattr(providers.settings, "cartesia_api_key", "configured")
    monkeypatch.setattr(providers.settings, "cartesia_voice_id", None)
    assert providers.get_tts_provider() is None


def test_speak_returns_no_audio_instead_of_erroring_when_tts_fails(client_from, monkeypatch):
    class _Broken(TTSProvider):
        async def synthesize(self, text):
            raise RuntimeError("401 from provider")

    monkeypatch.setattr(ai_router, "get_tts_provider", lambda: _Broken())
    r = client_from("127.0.0.1").post("/api/ai/speak", json={"text": "Good morning!"})
    assert r.status_code == 200
    assert r.json()["audio_base64"] is None
