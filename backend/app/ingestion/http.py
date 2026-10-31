"""Polite HTTP client for public data sources.

* One request at a time per host, with a minimum interval between requests.
* Bounded retries with exponential backoff, only for transient failures
  (timeouts, connection errors, 5xx). 401/403/429 are never retried: they mean the
  source refused automated access, and we stop rather than work around it.
* Short-lived response cache so several jobs in one run share one upstream request.
* An honest User-Agent; no cookies are harvested, no CAPTCHAs or anti-bot checks are bypassed.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings


class SourceError(RuntimeError):
    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind  # access_denied | rate_limited | timeout | network | http | parse
        self.status = status


@dataclass
class _Cached:
    at: float
    body: bytes
    content_type: str


class PoliteClient:
    def __init__(
        self,
        *,
        min_interval: float | None = None,
        max_retries: int = 2,
        backoff_base: float = 2.0,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        s = get_settings()
        self.min_interval = s.ingest_min_request_interval_seconds if min_interval is None else min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.sleep = sleep
        self.client = httpx.Client(
            timeout=timeout or s.source_fetch_timeout_seconds,
            headers={"User-Agent": s.source_user_agent, "Accept": "application/json, text/csv, application/zip, */*"},
            follow_redirects=False,
            transport=transport,
        )
        self._last: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._cache: dict[str, _Cached] = {}
        self.requests_made = 0

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _wait_turn(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < self.min_interval:
                self.sleep(self.min_interval - gap)
        self._last[host] = time.monotonic()

    def get(self, url: str, *, cache_ttl: float = 0.0, max_bytes: int = 30 * 1024 * 1024) -> tuple[bytes, str]:
        cached = self._cache.get(url)
        if cached and cache_ttl and time.monotonic() - cached.at < cache_ttl:
            return cached.body, cached.content_type
        body, ctype, _ = self.request(url, max_bytes=max_bytes)
        if cache_ttl:
            self._cache[url] = _Cached(time.monotonic(), body, ctype)
        return body, ctype

    def head(self, url: str) -> dict[str, str]:
        """Response headers only (ETag, Last-Modified, Content-Length) — used to skip unchanged documents."""
        _, _, headers = self.request(url, method="HEAD")
        return headers

    def request(self, url: str, *, method: str = "GET", max_bytes: int = 30 * 1024 * 1024) -> tuple[bytes, str, dict[str, str]]:
        """One polite request: per-host serialisation and spacing, bounded retries, streamed size limit."""
        host = urlparse(url).hostname or ""
        attempt = 0
        with self._host_lock(host):  # never concurrent requests to the same host
            while True:
                self._wait_turn(host)
                self.requests_made += 1
                try:
                    with self.client.stream(method, url) as r:
                        if r.status_code in (401, 403):
                            raise SourceError("access_denied", f"source refused automated access (HTTP {r.status_code})", r.status_code)
                        if r.status_code == 429:
                            raise SourceError("rate_limited", "source rate limit reached (HTTP 429); backing off until the next run", 429)
                        if r.status_code >= 500:
                            if attempt >= self.max_retries:
                                raise SourceError("http", f"HTTP {r.status_code}", r.status_code)
                        elif r.status_code >= 400 or r.status_code in (301, 302, 303, 307, 308):
                            raise SourceError("http", f"HTTP {r.status_code}", r.status_code)
                        else:
                            declared = int(r.headers.get("content-length") or 0)
                            if method == "GET" and declared > max_bytes:
                                raise SourceError("http", f"response larger than {max_bytes} bytes ({declared})")
                            chunks: list[bytes] = []
                            size = 0
                            if method == "GET":
                                for chunk in r.iter_bytes():
                                    size += len(chunk)
                                    if size > max_bytes:
                                        raise SourceError("http", f"response larger than {max_bytes} bytes")
                                    chunks.append(chunk)
                            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                            return b"".join(chunks), ctype, {k.lower(): v for k, v in r.headers.items()}
                except httpx.TimeoutException as exc:
                    if attempt >= self.max_retries:
                        raise SourceError("timeout", f"timed out fetching {url}") from exc
                except httpx.HTTPError as exc:
                    if attempt >= self.max_retries:
                        raise SourceError("network", f"network error: {type(exc).__name__}") from exc
                attempt += 1
                self.sleep(self.backoff_base * (2 ** (attempt - 1)))

    def get_json(self, url: str, *, cache_ttl: float = 0.0) -> Any:
        import json

        body, ctype = self.get(url, cache_ttl=cache_ttl)
        if "html" in ctype:
            raise SourceError("parse", "expected JSON but received HTML (endpoint changed or access page)")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise SourceError("parse", "invalid JSON from source") from exc
