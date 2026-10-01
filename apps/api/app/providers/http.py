"""Shared HTTP plumbing for the providers: pooled clients, timeouts, retries, circuit breakers.

- One AsyncClient per base URL and event loop: a fresh TLS handshake for every sentence of
  speech would cost more than synthesizing it. Keyed by loop because a client can't outlive the
  loop it was made on (each test case runs on its own).
- Retries only for what a retry can fix — 429, 5xx, a connection that never opened — with
  jittered backoff, and only before a response has started. A streamed reply is never replayed:
  that would repeat words the student already heard.
- A circuit breaker per provider: after repeated failures it stops calling for a cool-down, so
  a dead service (no credits, revoked key) costs one instant "unavailable" instead of a timeout
  on every turn.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
# Students pause between turns far longer than httpx's default 5 s keep-alive; reconnecting
# (TLS) costs ~0.35 s per service per turn, and the first request on a new connection ~1.4 s.
LIMITS = httpx.Limits(keepalive_expiry=60.0)
MAX_ATTEMPTS = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Failures that say the service is unusable for now (key, credits, outage) — as opposed to a
# 400 about one particular request, which says nothing about the next.
BREAKER_STATUSES = {401, 402, 403} | RETRY_STATUSES
# Transport errors where the request never reached the provider, so sending it again is safe.
RETRYABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.RemoteProtocolError)


class ProviderError(Exception):
    """The provider failed; callers treat it as "unavailable right now"."""

    def __init__(self, provider: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status


class ProviderUnavailable(ProviderError):
    """The circuit breaker is open: not even trying."""


class CircuitBreaker:
    def __init__(self, name: str, threshold: int = 3, cooldown: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self.name, self.threshold, self.cooldown, self._clock = name, threshold, cooldown, clock
        self.failures = 0
        self._open_until: float | None = None

    def check(self) -> None:
        if self._open_until is not None and self._clock() < self._open_until:
            raise ProviderUnavailable(self.name, f"skipped for {self._open_until - self._clock():.0f}s more "
                                                 f"after {self.failures} failures in a row")

    def record_success(self) -> None:
        self.failures, self._open_until = 0, None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            # Half-open after the cool-down: one call goes through, and a failure re-opens at once.
            self._open_until = self._clock() + self.cooldown
            logger.warning("%s failed %d times in a row; not calling it for %.0fs",
                           self.name, self.failures, self.cooldown)


_breakers: dict[str, CircuitBreaker] = {}


def breaker(name: str) -> CircuitBreaker:
    """One breaker per provider name, shared by every instance of it."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]


_clients: dict[str, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def client_for(base_url: str) -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    held = _clients.get(base_url)
    if held is None or held[0] is not loop or held[1].is_closed:
        held = (loop, httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT, limits=LIMITS))
        _clients[base_url] = held
    return held[1]


async def warm(base_url: str) -> None:
    """Opens the connection before the first real request needs it — a cold one costs over a
    second of the student's wait. Any answer will do; a failure is left for the real request."""
    try:
        await client_for(base_url).head("", timeout=5.0)
    except httpx.HTTPError:
        pass


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), 5.0)
        except ValueError:
            pass
    return min(0.5 * 2 ** (attempt - 1), 4.0) * random.uniform(0.75, 1.25)


async def send(client: httpx.AsyncClient, build: Callable[[], httpx.Request], *, provider: str,
               stream: bool = False) -> httpx.Response:
    """Sends with retries and the provider's breaker. Returns a successful response — for
    `stream=True` still open, for the caller to read and close — or raises ProviderError."""
    guard = breaker(provider)
    guard.check()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        retry_after = None
        try:
            response = await client.send(build(), stream=stream)
        except RETRYABLE_ERRORS as e:
            error, retryable, counts = ProviderError(provider, f"{type(e).__name__}: {e}"), True, True
        except httpx.HTTPError as e:  # e.g. a read timeout: the provider had it, don't resend
            guard.record_failure()
            raise ProviderError(provider, f"{type(e).__name__}: {e}") from e
        else:
            if response.status_code < 400:
                guard.record_success()
                return response
            body = (await response.aread())[:300].decode("utf-8", "replace")
            await response.aclose()
            status = response.status_code
            error = ProviderError(provider, f"HTTP {status}: {body}", status)
            retryable, counts = status in RETRY_STATUSES, status in BREAKER_STATUSES
            retry_after = response.headers.get("retry-after")
        if not retryable or attempt == MAX_ATTEMPTS:
            if counts:
                guard.record_failure()
            raise error
        delay = _backoff(attempt, retry_after)
        logger.info("%s; retrying in %.1fs (attempt %d of %d)", error, delay, attempt + 1, MAX_ATTEMPTS)
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")
