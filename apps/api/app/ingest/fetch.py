"""Fetching official pages and documents, politely (docs/design/15-phase6-plan.md, P6-9).

- robots.txt is respected; a disallowed URL isn't fetched, and the reason is returned.
- One request every 2 seconds per host, with a couple of retries for timeouts and server errors.
- The app identifies itself; no personal details go in the user agent.
- Raw bytes are kept under data/sources/<sha[:2]>/<sha>.<ext>, so a fact can always point at the
  exact document it was read from, and an unchanged document isn't stored twice.

Jobs use this offline (never inside a student's request). Tests pass an httpx.MockTransport, so
they never touch the web.
"""

from __future__ import annotations

import hashlib
import mimetypes
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

USER_AGENT = "MAYA-career-counsellor/0.6 (offline research for a student counselling kiosk; respects robots.txt)"
MAX_BYTES = 25 * 1024 * 1024
EXTENSIONS = {"text/html": ".html", "application/pdf": ".pdf", "application/json": ".json",
              "application/sparql-results+json": ".json", "text/plain": ".txt", "text/csv": ".csv",
              "application/xml": ".xml", "text/xml": ".xml"}


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int | None
    mime: str | None
    body: bytes
    sha256: str | None
    retrieved_at: datetime
    storage_path: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Fetcher:
    def __init__(self, store_dir: str | Path, *, min_interval: float = 2.0, timeout: float = 30.0, retries: int = 2,
                 respect_robots: bool = True, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.store = Path(store_dir)
        self.min_interval, self.retries, self.respect_robots = min_interval, retries, respect_robots
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True,
                                   transport=transport)
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._sleep, self._clock = sleep, clock

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = self.min_interval - (self._clock() - last)
            if gap > 0:
                self._sleep(gap)
        self._last[host] = self._clock()

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                self._wait(parts.netloc)
                r = self.client.get(f"{origin}/robots.txt")
                if r.status_code == 200 and "html" not in r.headers.get("content-type", ""):
                    parser.parse(r.text.splitlines())
                else:
                    parser = None  # no usable robots.txt: everything is allowed
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def _keep(self, body: bytes, mime: str | None, url: str) -> tuple[str, str]:
        sha = hashlib.sha256(body).hexdigest()
        ext = EXTENSIONS.get((mime or "").split(";")[0].strip()) or Path(urlsplit(url).path).suffix[:6] \
            or mimetypes.guess_extension((mime or "").split(";")[0].strip() or "") or ".bin"
        path = self.store / sha[:2] / f"{sha}{ext}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return sha, str(path)

    def get(self, url: str, *, params: dict | None = None, data: dict | None = None,
            headers: dict | None = None, keep: bool = True, api: bool = False) -> Fetched:
        """api=True only for documented public APIs (Wikidata's API, Nominatim, Overpass): their
        robots.txt is written for crawlers, and their own usage policies — identify yourself, go
        slowly — are what apply, and are followed here."""
        now = datetime.now(timezone.utc)
        if not api and not self.allowed(url):
            return Fetched(url, url, None, None, b"", None, now, None, error="disallowed by robots.txt")
        host = urlsplit(url).netloc
        error = None
        for attempt in range(self.retries + 1):
            self._wait(host)
            try:
                if data is not None:
                    r = self.client.post(url, params=params, data=data, headers=headers)
                else:
                    r = self.client.get(url, params=params, headers=headers)
            except httpx.HTTPError as e:
                error = f"{type(e).__name__}: {e}"[:300]
                continue
            if r.status_code == 429 and attempt < self.retries:
                # Too many requests: wait as long as the server asks (or a minute), then try again.
                wait = r.headers.get("retry-after", "")
                self._sleep(float(wait) if wait.isdigit() else 60.0)
                error = "HTTP 429"
                continue
            if r.status_code >= 500 and attempt < self.retries:
                error = f"HTTP {r.status_code}"
                continue
            body = r.content[:MAX_BYTES + 1]
            mime = r.headers.get("content-type")
            if len(body) > MAX_BYTES:
                return Fetched(url, str(r.url), r.status_code, mime, b"", None, now, None, error="larger than 25 MB")
            sha, path = self._keep(body, mime, str(r.url)) if keep and r.status_code < 400 else (None, None)
            return Fetched(url, str(r.url), r.status_code, mime, body, sha, now, path,
                           error=None if r.status_code < 400 else f"HTTP {r.status_code}")
        return Fetched(url, url, None, None, b"", None, now, None, error=error or "failed")
