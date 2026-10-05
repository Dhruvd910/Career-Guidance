"""Logs, request ids and metrics (spec §29).

- Every HTTP request gets an id (the caller's X-Request-ID, or a new one), returned in the
  response's X-Request-ID header and carried by every log line written while handling it — so one
  grep finds everything a request did. A live conversation's lines carry its session instead.
- Logs are JSON lines by default (LOG_FORMAT=json; "text" for reading by eye).
- Metrics are counters kept in the process (one API process on the Pi): requests by route and
  status with their latencies, model calls with tokens and cost, provider failures. GET /api/metrics.

Nothing here logs request bodies, tokens or keys.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname, "logger": record.name,
                "msg": record.getMessage()}
        if getattr(record, "request_id", None):
            line["request_id"] = record.request_id
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        rid = getattr(record, "request_id", None)
        return f"{text} [{rid}]" if rid else text


def setup_logging(fmt: str = "json", level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_ContextFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else
                         _TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def new_request_id(given: str | None = None) -> str:
    """The caller's id if it's a sane one, else a fresh one."""
    if given and len(given) <= 64 and all(c.isalnum() or c in "-_." for c in given):
        return given
    return uuid.uuid4().hex[:16]


# ---------------- audit ----------------

_audit = logging.getLogger("app.audit")


def audit(action: str, **fields) -> None:
    """A sensitive action (spec §30): logins, permissions, deletions, profile edits — who and what,
    by id and field name only, never the values."""
    _audit.info("%s %s", action, " ".join(f"{k}={v}" for k, v in fields.items()))


# ---------------- metrics ----------------

_lock = threading.Lock()
_started = time.time()
_requests: dict[tuple[str, str, int], int] = defaultdict(int)
_latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))  # route → recent ms
_llm: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0,
                                             "cost_usd": 0.0})
_events: dict[str, int] = defaultdict(int)


def record_request(method: str, route: str, status: int, ms: float) -> None:
    with _lock:
        _requests[(method, route, status)] += 1
        _latencies[f"{method} {route}"].append(ms)


def record_llm(model: str | None, tokens_in: int, tokens_cached: int, tokens_out: int, cost: float | None) -> None:
    with _lock:
        m = _llm[model or "unknown"]
        m["calls"] += 1
        m["tokens_in"] += tokens_in
        m["tokens_cached"] += tokens_cached
        m["tokens_out"] += tokens_out
        m["cost_usd"] += cost or 0.0


def count(event: str, n: int = 1) -> None:
    """Anything worth counting: turns, interruptions, rate-limited requests, retrieval failures."""
    with _lock:
        _events[event] += n


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))], 1)


def snapshot() -> dict:
    with _lock:
        routes: dict[str, dict] = {}
        for (method, route, status), n in _requests.items():
            r = routes.setdefault(f"{method} {route}", {"count": 0, "by_status": {}})
            r["count"] += n
            r["by_status"][str(status)] = r["by_status"].get(str(status), 0) + n
        for key, values in _latencies.items():
            if key in routes and values:
                routes[key]["p50_ms"], routes[key]["p95_ms"] = _percentile(list(values), 0.5), _percentile(list(values), 0.95)
        llm = {m: {**v, "cost_usd": round(v["cost_usd"], 6)} for m, v in _llm.items()}
        return {"uptime_s": int(time.time() - _started), "requests": routes, "llm": llm,
                "llm_cost_usd": round(sum(v["cost_usd"] for v in _llm.values()), 6), "events": dict(_events)}


def reset() -> None:
    with _lock:
        _requests.clear(), _latencies.clear(), _llm.clear(), _events.clear()
