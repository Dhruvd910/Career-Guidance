"""Spec §29-30: request ids, structured logs, health, metrics, rate limits, the production secret."""

import json
import logging

import pytest

from app.core import observability, ratelimit
from app.core.config import get_settings


def register(client, email="a@example.com"):
    return client.post("/api/auth/register", json={"email": email, "password": "password123", "name": "A",
                                                    "class_level": 10}).json()["access_token"]


def test_every_response_carries_a_request_id_and_keeps_the_callers(client):
    fresh = client.get("/api/health")
    assert len(fresh.headers["x-request-id"]) == 16
    assert client.get("/api/health", headers={"X-Request-ID": "pi-turn-42"}).headers["x-request-id"] == "pi-turn-42"
    assert client.get("/api/health", headers={"X-Request-ID": "bad id\\n"}).headers["x-request-id"] != "bad id\\n"


def test_log_lines_are_json_with_the_request_id(capsys):
    observability.setup_logging("json")
    try:
        token = observability.request_id.set("abc123")
        logging.getLogger("app.test").info("turn %s done", "t1")
        observability.request_id.reset(token)
        line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
        assert line["msg"] == "turn t1 done" and line["request_id"] == "abc123" and line["level"] == "INFO"
    finally:
        observability.setup_logging("text")


def test_health_reports_each_part_without_secrets(client):
    body = client.get("/api/health").json()
    assert body["status"] in ("ok", "degraded") and body["database"] == "ok"
    assert set(body["services"]) == {"llm", "background_llm", "stt", "tts", "embedding"}
    assert "key" not in json.dumps(body).lower()


def test_metrics_count_requests_and_are_only_for_the_device(client):
    client.get("/api/health")
    assert client.get("/api/metrics").status_code == 403, "the test client isn't the device itself"
    routes = observability.snapshot()["requests"]
    assert routes["GET /api/health"]["count"] == 1 and "p95_ms" in routes["GET /api/health"]
    observability.record_llm("some/model", 8000, 6000, 50, 0.0004)
    assert observability.snapshot()["llm_cost_usd"] == pytest.approx(0.0004)


def test_too_many_logins_are_turned_away_with_retry_after(client):
    for _ in range(ratelimit.LIMITS["login"][0]):
        assert client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-pass"}).status_code == 401
    refused = client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-pass"})
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) >= 1
    assert observability.snapshot()["events"]["rate_limited.login"] == 1


def test_the_ai_limit_is_per_student_and_refills():
    capacity, period = ratelimit.LIMITS["ai"]
    for _ in range(capacity):
        assert ratelimit.allow("ai", "user:1", now=0.0) == 0
    assert ratelimit.allow("ai", "user:1", now=0.0) > 0
    assert ratelimit.allow("ai", "user:2", now=0.0) == 0, "another student isn't affected"
    assert ratelimit.allow("ai", "user:1", now=period / capacity) == 0, "a token comes back after its share of the period"


def test_production_refuses_the_development_secret(monkeypatch):
    get_settings.cache_clear()
    try:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me")
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            get_settings()
        monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
        assert get_settings().environment == "production"
    finally:
        get_settings.cache_clear()
