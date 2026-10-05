"""Rate limits (spec §30): token buckets per student (or per address before login), in the API
process's memory — there is one process on the Pi.

The limits protect the paid AI services and the login from runaway clients; they're far above
what a person talking or tapping does. A request over the limit gets 429 with Retry-After.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from jwt import PyJWTError

from app.core import observability
from app.core.security import decode_access_token

# name → (requests, per seconds)
LIMITS = {
    "ai": (30, 60),  # replies, transcriptions, speech: about one every two seconds, sustained
    "login": (10, 60),
    "register": (5, 300),
    "refresh": (10, 3600),  # "Check for updates" on colleges
}


@dataclass
class _Bucket:
    tokens: float
    updated: float


_buckets: dict[tuple[str, str], _Bucket] = {}
_lock = threading.Lock()


def allow(name: str, key: str, now: float | None = None) -> float:
    """0 if this request may go ahead (and takes a token), else the seconds until it may."""
    capacity, period = LIMITS[name]
    rate = capacity / period
    now = time.monotonic() if now is None else now
    with _lock:
        bucket = _buckets.setdefault((name, key), _Bucket(float(capacity), now))
        bucket.tokens = min(capacity, bucket.tokens + (now - bucket.updated) * rate)
        bucket.updated = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return 0.0
        return (1 - bucket.tokens) / rate


def client_key(request: Request) -> str:
    """The student, when the request carries their token; otherwise the caller's address."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            return f"user:{decode_access_token(header[7:])['sub']}"
        except (PyJWTError, KeyError):
            pass
    return f"ip:{request.client.host if request.client else 'unknown'}"


def limit(name: str):
    """A FastAPI dependency: Depends(limit("ai"))."""

    def check(request: Request) -> None:
        wait = allow(name, client_key(request))
        if wait:
            observability.count(f"rate_limited.{name}")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests — please wait a moment.",
                                headers={"Retry-After": str(int(wait) + 1)})

    return check


def reset() -> None:
    with _lock:
        _buckets.clear()
