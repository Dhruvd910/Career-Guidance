import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import observability
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import LOOPBACK_HOSTS
from app.providers.embedding import LocalE5Embedding
from app.providers.http import ProviderError, breaker_states
from app.routers import (
    ai, assessment, auth, career, careers, colleges, conversation, exams, memory, mentor, mock_tests, practice,
    predictions, roadmap, saved_items, student,
)

settings = get_settings()
# The app's own INFO lines (per-turn timings above all) next to uvicorn's in the API log, as JSON
# lines with the request id (app/core/observability.py).
observability.setup_logging(settings.log_format)
logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Background work for the server's lifetime: closing idle sessions and writing their memory."""
    sweeper = None
    if settings.memory_sweeper:
        from app.memory.lifecycle import sweep_forever

        sweeper = asyncio.create_task(sweep_forever())
    yield
    if sweeper is not None:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Every request: an id (returned as X-Request-ID, carried by its log lines) and its latency."""
    rid = observability.new_request_id(request.headers.get("x-request-id"))
    token = observability.request_id.set(rid)
    started = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", "unmatched")
        observability.record_request(request.method, route, status_code, (time.monotonic() - started) * 1000)
        observability.request_id.reset(token)


@app.exception_handler(ProviderError)
async def provider_unavailable(_request: Request, exc: ProviderError) -> JSONResponse:
    """An AI service failing (no credits, outage, timeout) is "unavailable right now", not a bug."""
    logger.warning("AI provider failed: %s", exc)
    return JSONResponse(status_code=503, content={"detail": f"The {exc.provider} service is unavailable right now."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Dev convenience: also allow the Next.js dev server when reached via a LAN IP
    # (e.g. from a phone/laptop on the same network as this Pi), not just localhost.
    # Auth uses a Bearer token, not cookies, so allow_credentials=False is correct here
    # and lets us pair a broad regex with allow_origins without violating CORS rules.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}):3000",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(student.router)
app.include_router(exams.router)
app.include_router(mock_tests.router)
app.include_router(practice.router)
# Before careers: /api/careers/{career_id} would otherwise claim /api/careers/directions.
app.include_router(assessment.directions_router)
app.include_router(careers.router)
app.include_router(assessment.router)
app.include_router(career.router)
app.include_router(career.skills_router)
app.include_router(colleges.router)
app.include_router(predictions.router)
app.include_router(roadmap.router)
app.include_router(roadmap.progress_router)
app.include_router(saved_items.router)
app.include_router(mentor.router)
app.include_router(ai.router)
app.include_router(conversation.router)
app.include_router(memory.router)
app.include_router(memory.memory_router)
app.include_router(memory.counselling_router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Up, and how each part is doing: the database, each AI service (configured? its circuit breaker
    and last failure), the on-device embedding model. "degraded" when something is down — the app
    still answers what it can. Never includes keys."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception as e:  # noqa: BLE001 — reported, not raised
        database = f"error: {type(e).__name__}"
    breakers = breaker_states()
    services = {
        "llm": {"configured": bool(settings.openrouter_api_key or settings.llm_base_url),
                "model": settings.openrouter_model if settings.llm_provider == "openrouter" else settings.llm_model,
                "fallbacks": settings.openrouter_fallback_models},
        "background_llm": {"model": settings.memory_model or "the live model"},
        "stt": {"configured": settings.stt_provider != "none" and bool(settings.groq_api_key), "model": settings.groq_stt_model},
        "tts": {"configured": settings.tts_provider != "none" and bool(settings.cartesia_api_key and settings.cartesia_voice_id)},
        "embedding": {"available": settings.embedding_provider != "none"
                      and LocalE5Embedding.available(Path(settings.embedding_model_dir))},
    }
    degraded = database != "ok" or any(b["state"] == "open" for b in breakers.values())
    return {"status": "degraded" if degraded else "ok", "environment": settings.environment, "version": app.version,
            "database": database, "services": services, "breakers": breakers}


@app.get("/api/metrics")
def metrics(request: Request) -> dict:
    """Counters since the API started: requests by route (with p50/p95 latency), model calls with
    tokens and cost, rate-limited requests. From the device itself only."""
    if not (request.client and request.client.host in LOOPBACK_HOSTS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Metrics are only served to the device itself.")
    return observability.snapshot()
