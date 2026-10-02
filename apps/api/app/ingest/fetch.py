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
import json
import mimetypes
import re
import ssl
import subprocess
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import certifi
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


def _openssl(args: list[str], data: bytes) -> bytes:
    return subprocess.run(["openssl", *args], input=data, capture_output=True, timeout=30, check=False).stdout


def missing_intermediate(host: str, port: int = 443) -> ssl.SSLContext | None:
    """Many institutional sites send their own certificate but not the intermediate that links
    it to a trusted root. Like a browser, fetch that intermediate from the address in the
    certificate (AIA) and verify the whole chain against the usual roots. None if that fails."""
    try:
        leaf = ssl.get_server_certificate((host, port), timeout=20).encode()
    except (OSError, ssl.SSLError):
        return None
    aia = _openssl(["x509", "-noout", "-ext", "authorityInfoAccess"], leaf).decode()
    url = next(iter(re.findall(r"CA Issuers - URI:(\S+)", aia)), None)
    if not url:
        return None
    try:
        der = httpx.get(url, timeout=20, follow_redirects=True).content
    except httpx.HTTPError:
        return None
    pem = _openssl(["x509", "-inform", "DER" if not der.startswith(b"-----") else "PEM"], der).decode()
    if "BEGIN CERTIFICATE" not in pem:  # some point at a PKCS#7 bundle (.p7c) instead
        pem = _openssl(["pkcs7", "-inform", "DER" if not der.startswith(b"-----") else "PEM", "-print_certs"], der).decode()
    if "BEGIN CERTIFICATE" not in pem:
        return None
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cadata=pem)
    return context


class Fetcher:
    def __init__(self, store_dir: str | Path, *, min_interval: float = 2.0, timeout: float = 30.0, retries: int = 2,
                 respect_robots: bool = True, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.store = Path(store_dir)
        self.min_interval, self.retries, self.respect_robots = min_interval, retries, respect_robots
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True,
                                   transport=transport)
        self._last: dict[str, float] = {}
        self._repaired: dict[str, httpx.Client] = {}  # hosts that needed their intermediate certificate
        self._timeout, self._transport = timeout, transport
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._sleep, self._clock = sleep, clock

    def close(self) -> None:
        self.client.close()
        for client in self._repaired.values():
            client.close()

    def _client_for(self, host: str) -> httpx.Client:
        return self._repaired.get(host, self.client)

    def _repair(self, host: str) -> bool:
        if self._transport is not None or host in self._repaired:
            return False
        context = missing_intermediate(host)
        if context is None:
            return False
        self._repaired[host] = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=self._timeout,
                                            follow_redirects=True, verify=context)
        return True

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

    def _cache_key(self, url: str, params: dict | None, data: dict | None) -> Path:
        key = hashlib.sha256(json.dumps([url, sorted((params or {}).items()), sorted((data or {}).items())]).encode()).hexdigest()
        return self.store / "cache" / key[:2] / f"{key}.json"

    def _cached(self, url: str, params: dict | None, data: dict | None, days: int) -> Fetched | None:
        index = self._cache_key(url, params, data)
        if not index.exists():
            return None
        meta = json.loads(index.read_text())
        retrieved = datetime.fromisoformat(meta["retrieved_at"])
        if (datetime.now(timezone.utc) - retrieved).days > days or not Path(meta["storage_path"]).exists():
            return None
        return Fetched(url, meta["final_url"], meta["status"], meta["mime"], Path(meta["storage_path"]).read_bytes(),
                       meta["sha256"], retrieved, meta["storage_path"])

    def get(self, url: str, *, params: dict | None = None, data: dict | None = None,
            headers: dict | None = None, keep: bool = True, api: bool = False, cache_days: int | None = None) -> Fetched:
        """cache_days: reuse this exact request's answer if it was fetched within that many days."""
        if cache_days is not None:
            hit = self._cached(url, params, data, cache_days)
            if hit is not None:
                return hit
        page = self._get(url, params=params, data=data, headers=headers, keep=keep or cache_days is not None, api=api)
        if cache_days is not None and page.ok and page.storage_path:
            index = self._cache_key(url, params, data)
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(json.dumps({"final_url": page.final_url, "status": page.status, "mime": page.mime,
                                         "sha256": page.sha256, "storage_path": page.storage_path,
                                         "retrieved_at": page.retrieved_at.isoformat()}))
        return page

    def _get(self, url: str, *, params: dict | None = None, data: dict | None = None,
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
            client = self._client_for(host)
            try:
                if data is not None:
                    r = client.post(url, params=params, data=data, headers=headers)
                else:
                    r = client.get(url, params=params, headers=headers)
            except httpx.ConnectError as e:
                error = f"{type(e).__name__}: {e}"[:300]
                if "CERTIFICATE_VERIFY_FAILED" in str(e) and self._repair(host):
                    continue
                if "CERTIFICATE_VERIFY_FAILED" in str(e):
                    error = "the site's security certificate couldn't be verified"
                    break
                continue
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
