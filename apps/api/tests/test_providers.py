"""The provider layer against a simulated network: streaming, retries, and the circuit breaker."""

import asyncio
import json

import httpx
import pytest

from app.providers import http as provider_http
from app.providers import registry
from app.providers.http import CircuitBreaker, ProviderError, ProviderUnavailable
from app.providers.llm import Done, OpenAICompatibleLLM, TextDelta, ToolCall, Usage
from app.providers.stt import GroqWhisperSTT
from app.providers.tts import CartesiaTTS
from tests.fakes import FakeSTT


@pytest.fixture(autouse=True)
def fresh_breakers_and_no_waiting(monkeypatch):
    monkeypatch.setattr(provider_http, "_breakers", {})

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(provider_http.asyncio, "sleep", no_sleep)


def network(*replies):
    """An AsyncClient whose requests get these replies in order (an exception is raised
    instead of replying). Every request it saw is in `.requests`."""
    queue = list(replies)
    requests = []

    def handle(request):
        requests.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://ai.invalid/v1")
    client.requests = requests
    return client


def sse(*events, done=True):
    lines = [": keep-alive", ""]
    for event in events:
        lines += [f"data: {json.dumps(event)}", ""]
    if done:
        lines += ["data: [DONE]", ""]
    return httpx.Response(200, text="\n".join(lines), headers={"content-type": "text/event-stream"})


def collect(agen):
    async def run():
        return [item async for item in agen]
    return asyncio.run(run())


def llm(client, key="sk-test"):
    return OpenAICompatibleLLM("https://ai.invalid/v1", "some/model", key, name="test-llm", client=client)


# ---------------- LLM ----------------

def test_stream_yields_text_as_it_arrives_then_done():
    client = network(sse(
        {"choices": [{"delta": {"role": "assistant", "content": "Hello"}}]},
        {"choices": [{"delta": {"content": " there."}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ))
    events = collect(llm(client).stream([{"role": "user", "content": "hi"}]))
    assert events == [TextDelta("Hello"), TextDelta(" there."), Done("stop")]
    body = json.loads(client.requests[0].content)
    assert body["stream"] is True and body["model"] == "some/model"
    assert str(client.requests[0].url) == "https://ai.invalid/v1/chat/completions"


def test_stream_assembles_tool_calls_from_fragments():
    client = network(sse(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "search_colleges", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_b", "function": {"name": "get_fees", "arguments": "{\"college"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"q\": \"IIT"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " Delhi\"}"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"arguments": "_id\": 7}"}}]}, "finish_reason": "tool_calls"}]},
    ))
    events = collect(llm(client).stream([], tools=[{"type": "function"}]))
    assert events == [
        ToolCall("call_a", "search_colleges", '{"q": "IIT Delhi"}'),
        ToolCall("call_b", "get_fees", '{"college_id": 7}'),
        Done("tool_calls"),
    ]
    assert json.loads(client.requests[0].content)["tool_choice"] == "auto"


def test_an_error_inside_the_stream_is_a_provider_error():
    client = network(sse({"error": {"message": "model overloaded"}}, done=False))
    with pytest.raises(ProviderError, match="model overloaded"):
        collect(llm(client).stream([]))


def test_chat_returns_the_message_and_a_local_server_needs_no_key():
    client = network(httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Hi!"}}]}))
    reply = asyncio.run(llm(client, key=None).chat([{"role": "user", "content": "hi"}]))
    assert reply == {"role": "assistant", "content": "Hi!"}
    assert "authorization" not in client.requests[0].headers


# ---------------- retries ----------------

def test_a_temporary_outage_is_retried():
    client = network(httpx.Response(503, text="busy"),
                     httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
    assert asyncio.run(llm(client).chat([]))["content"] == "ok"
    assert len(client.requests) == 2


def test_a_connection_that_never_opened_is_retried():
    client = network(httpx.ConnectError("no route"),
                     httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
    assert asyncio.run(llm(client).chat([]))["content"] == "ok"


def test_a_bad_key_is_not_retried():
    client = network(httpx.Response(401, text="invalid key"))
    with pytest.raises(ProviderError) as caught:
        asyncio.run(llm(client).chat([]))
    assert caught.value.status == 401 and len(client.requests) == 1


def test_a_read_timeout_is_not_resent():
    # The provider had the request; sending it again could bill and answer it twice.
    client = network(httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderError, match="ReadTimeout"):
        asyncio.run(llm(client).chat([]))
    assert len(client.requests) == 1


def test_retries_give_up_after_three_attempts():
    client = network(*[httpx.Response(503) for _ in range(3)])
    with pytest.raises(ProviderError) as caught:
        asyncio.run(llm(client).chat([]))
    assert caught.value.status == 503 and len(client.requests) == 3


# ---------------- circuit breaker ----------------

def test_repeated_failures_stop_further_calls_for_a_while():
    client = network(*[httpx.Response(402, text="no credits") for _ in range(3)])
    for _ in range(3):
        with pytest.raises(ProviderError):
            asyncio.run(llm(client).chat([]))
    with pytest.raises(ProviderUnavailable):
        asyncio.run(llm(client).chat([]))
    assert len(client.requests) == 3, "the fourth call never went out"


def test_after_the_cooldown_one_call_is_let_through():
    now = [0.0]
    guard = CircuitBreaker("x", threshold=2, cooldown=60, clock=lambda: now[0])
    guard.record_failure()
    guard.record_failure()
    with pytest.raises(ProviderUnavailable):
        guard.check()
    now[0] = 61
    guard.check()  # half-open: allowed
    guard.record_failure()
    with pytest.raises(ProviderUnavailable):
        guard.check()  # and one more failure re-opens it at once
    now[0] = 200
    guard.record_success()
    guard.check()
    assert guard.failures == 0


def test_a_bad_request_does_not_trip_the_breaker():
    client = network(*[httpx.Response(400, text="bad input") for _ in range(5)])
    for _ in range(5):
        with pytest.raises(ProviderError) as caught:
            asyncio.run(llm(client).chat([]))
        assert not isinstance(caught.value, ProviderUnavailable)


# ---------------- TTS and STT ----------------

def test_tts_stream_never_splits_a_sample():
    async def body():
        for piece in (b"\x01", b"\x02\x03\x04\x05", b"\x06\x07", b"\x08"):
            yield piece

    client = network(httpx.Response(200, content=body()))
    tts = CartesiaTTS("https://ai.invalid/v1", "key", "voice-1", "sonic", sample_rate=24000, client=client)
    chunks = collect(tts.stream("नमस्ते, मैं माया हूँ।"))
    assert all(len(c) % 2 == 0 for c in chunks)
    assert b"".join(chunks) == bytes(range(1, 9))
    sent = json.loads(client.requests[0].content)
    assert sent["output_format"] == {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000}
    assert sent["language"] == "hi", "a Devanagari reply is read in Hindi"


def test_tts_language_can_be_chosen_explicitly():
    client = network(httpx.Response(200, content=b"\x00\x00"))
    tts = CartesiaTTS("https://ai.invalid/v1", "key", "voice-1", "sonic", client=client)
    collect(tts.stream("Mujhe engineering pasand hai", language="hi"))
    assert json.loads(client.requests[0].content)["language"] == "hi"


def test_transcript_carries_confidence_and_no_speech_probability():
    client = network(httpx.Response(200, json={
        "text": " Thank you.", "language": "english", "duration": 1.5,
        "segments": [{"avg_logprob": -0.1, "no_speech_prob": 0.2}, {"avg_logprob": -0.3, "no_speech_prob": 0.9}],
    }))
    heard = asyncio.run(GroqWhisperSTT("https://ai.invalid/v1", "key", "whisper", client=client).transcribe(b"wav", "a.wav"))
    assert heard.text == " Thank you." and heard.language == "en" and heard.duration_ms == 1500
    assert heard.confidence == pytest.approx(0.8187, abs=1e-3)  # e^-0.2
    assert heard.no_speech_prob == 0.9


# ---------------- configuration ----------------

def test_a_local_openai_compatible_server_is_a_config_change(monkeypatch):
    monkeypatch.setattr(registry.settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(registry.settings, "llm_base_url", "http://127.0.0.1:8080/v1")
    monkeypatch.setattr(registry.settings, "llm_model", "qwen2.5-7b-instruct")
    monkeypatch.setattr(registry.settings, "llm_api_key", None)
    provider = registry.get_llm_provider()
    assert isinstance(provider, OpenAICompatibleLLM) and provider.model_id == "qwen2.5-7b-instruct"


def test_openrouter_calls_keep_students_words_from_providers_that_train_on_them(monkeypatch):
    monkeypatch.setattr(registry.settings, "llm_provider", "openrouter")
    monkeypatch.setattr(registry.settings, "openrouter_api_key", "sk-test")
    monkeypatch.setattr(registry.settings, "openrouter_model", "qwen/some-model:free")
    monkeypatch.setattr(registry.settings, "openrouter_fallback_models", ["openai/gpt-oss-120b"])
    provider = registry.get_llm_provider()
    client = network(httpx.Response(200, json={"model": "openai/gpt-oss-120b", "choices": [
        {"message": {"role": "assistant", "content": "ok"}}], "usage": {
        "prompt_tokens": 8000, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 6000}, "cost": 0.0004}}))
    provider._client = client
    asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    body = json.loads(client.requests[0].content)
    assert body["provider"] == {"data_collection": "deny"} and body["usage"] == {"include": True}
    assert body["models"] == ["qwen/some-model:free", "openai/gpt-oss-120b"], "the free model first, then a fallback"
    assert provider.last_usage == Usage("openai/gpt-oss-120b", 8000, 6000, 40, 0.0004), "who answered, and what it cost"


def test_a_streamed_reply_reports_what_it_used():
    client = network(sse(
        {"choices": [{"delta": {"content": "Hi."}, "finish_reason": "stop"}]},
        {"model": "some/model", "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.00001}},
    ))
    events = collect(llm(client).stream([{"role": "user", "content": "hi"}]))
    assert events[-1] == Done("stop", Usage("some/model", 10, 0, 2, 0.00001))
    assert (Usage(cost=0.1) + Usage(cost=0.2) + None).cost == pytest.approx(0.3)


def test_unconfigured_services_are_none_not_errors(monkeypatch):
    monkeypatch.setattr(registry.settings, "llm_provider", "openrouter")
    monkeypatch.setattr(registry.settings, "openrouter_api_key", None)
    monkeypatch.setattr(registry.settings, "tts_provider", "none")
    assert registry.get_llm_provider() is None and registry.get_tts_provider() is None


def test_an_unknown_provider_name_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(registry.settings, "stt_provider", "carrier-pigeon")
    with pytest.raises(ValueError, match="carrier-pigeon"):
        registry.get_stt_provider()


def test_a_failing_service_answers_503_not_500(client, monkeypatch):
    from app.routers import ai as ai_router

    class DeadSTT(FakeSTT):
        async def transcribe(self, audio_bytes, filename):
            raise ProviderError("groq", "HTTP 503: down", 503)

    monkeypatch.setattr(ai_router, "get_stt_provider", lambda: DeadSTT())
    token = client.post("/api/auth/register", json={
        "email": "dead-stt@example.com", "password": "password123", "name": "S", "class_level": 10,
    }).json()["access_token"]
    r = client.post("/api/ai/transcribe", files={"audio": ("a.wav", b"RIFF", "audio/wav")},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503 and "groq" in r.json()["detail"]


def test_idle_connections_are_kept_between_turns():
    assert provider_http.LIMITS.keepalive_expiry >= 60


def test_warming_up_opens_the_connection_and_ignores_failure(monkeypatch):
    client = network(httpx.Response(404), httpx.ConnectError("offline"))
    monkeypatch.setattr(provider_http, "client_for", lambda base_url: client)
    asyncio.run(provider_http.warm("https://ai.invalid/v1"))
    asyncio.run(provider_http.warm("https://ai.invalid/v1"))  # must not raise
    assert [r.method for r in client.requests] == ["HEAD", "HEAD"]
