"""Mode C — source adapters for permitted official publications.

``OfficialDocumentAdapter`` fetches a single, user-supplied URL from an allow-listed
official host (SEBI / NSE / BSE by default) and ingests it as a source document.
It is deliberately conservative:

* https only, host must be on the allow-list, every resolved IP must be public (SSRF);
* redirects are followed manually (max 3) and re-validated at every hop;
* robots.txt is honoured; a minimum interval between requests per host is enforced;
* response size and time are capped; responses are cached on disk (24 h);
* it never solves CAPTCHAs, logs in, rotates identities or bypasses anti-bot controls.
  If a site blocks programmatic access (NSE frequently does), use manual upload.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services import rag

CACHE_TTL = 24 * 3600


class SourceFetchError(RuntimeError):
    pass


@dataclass
class Fetched:
    url: str
    content_type: str
    body: bytes
    from_cache: bool


_last_hit: dict[str, float] = {}
_lock = threading.Lock()


def validate_url(url: str, settings: Settings, resolver=socket.getaddrinfo) -> str:
    p = urlparse(url)
    if p.scheme != "https":
        raise SourceFetchError("only https URLs are allowed")
    host = (p.hostname or "").lower()
    if not host or host not in settings.allowed_source_hosts:
        raise SourceFetchError(f"host '{host}' is not on the allow-list ({', '.join(sorted(settings.allowed_source_hosts))})")
    if p.username or p.password:
        raise SourceFetchError("credentials in URLs are not allowed")
    if p.port not in (None, 443):
        raise SourceFetchError("non-standard ports are not allowed")
    try:
        infos = resolver(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SourceFetchError(f"cannot resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SourceFetchError(f"{host} resolves to a non-public address")
    return url


def _robots_allowed(client: httpx.Client, url: str, ua: str) -> bool:
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        r = client.get(robots_url, timeout=8, follow_redirects=False)
    except httpx.HTTPError:
        return True  # unreachable robots.txt: RFC 9309 treats as allow; the fetch itself may still fail
    if r.status_code >= 500 or r.status_code == 429:
        return False  # treat server errors as "disallow" (conservative)
    if r.status_code >= 400:
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(ua, url)


def _throttle(host: str, min_interval: float) -> None:
    with _lock:
        last = _last_hit.get(host, 0.0)
        now = time.monotonic()
        if now - last < min_interval:
            raise SourceFetchError(f"please wait {min_interval - (now - last):.0f}s between requests to {host}")
        _last_hit[host] = now


class OfficialDocumentAdapter:
    name = "official_document"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.s = settings or get_settings()
        self.client = client or httpx.Client(headers={"User-Agent": self.s.source_user_agent}, timeout=self.s.source_fetch_timeout_seconds)

    def _cache_paths(self, url: str):
        h = hashlib.sha256(url.encode()).hexdigest()
        d = self.s.cache_dir
        return d / f"{h}.bin", d / f"{h}.json"

    def fetch(self, url: str) -> Fetched:
        validate_url(url, self.s)
        body_p, meta_p = self._cache_paths(url)
        if meta_p.exists() and body_p.exists():
            meta = json.loads(meta_p.read_text())
            if time.time() - meta["fetched_at"] < CACHE_TTL:
                return Fetched(meta["url"], meta["content_type"], body_p.read_bytes(), True)
        if not _robots_allowed(self.client, url, self.s.source_user_agent):
            raise SourceFetchError("robots.txt disallows fetching this URL; download it manually and upload it instead")
        current = url
        limit = self.s.source_fetch_max_mb * 1024 * 1024
        for _hop in range(4):
            _throttle(urlparse(current).hostname or "", self.s.source_fetch_min_interval_seconds if _hop == 0 else 0)
            try:
                with self.client.stream("GET", current, follow_redirects=False) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        nxt = urljoin(current, r.headers.get("location", ""))
                        validate_url(nxt, self.s)
                        current = nxt
                        continue
                    if r.status_code in (401, 403, 429):
                        raise SourceFetchError(f"source refused programmatic access (HTTP {r.status_code}); use manual upload")
                    if r.status_code >= 400:
                        raise SourceFetchError(f"HTTP {r.status_code}")
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype not in ("application/pdf", "text/html", "text/plain"):
                        raise SourceFetchError(f"unsupported content type {ctype or 'unknown'}")
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > limit:
                            raise SourceFetchError(f"response larger than {self.s.source_fetch_max_mb} MB")
            except httpx.TimeoutException as exc:
                raise SourceFetchError("source timed out") from exc
            except httpx.HTTPError as exc:
                raise SourceFetchError(f"network error: {type(exc).__name__}") from exc
            self.s.cache_dir.mkdir(parents=True, exist_ok=True)
            body_p.write_bytes(bytes(buf))
            meta_p.write_text(json.dumps({"url": current, "content_type": ctype, "fetched_at": time.time()}))
            return Fetched(current, ctype, bytes(buf), False)
        raise SourceFetchError("too many redirects")


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def ingest_official_url(db: Session, *, url: str, ipo_id: int | None, title: str, doc_type: str, user_id: int | None,
                        adapter: OfficialDocumentAdapter | None = None):
    fetched = (adapter or OfficialDocumentAdapter()).fetch(url)
    if fetched.content_type == "application/pdf":
        doc = rag.ingest_pdf_document(db, ipo_id=ipo_id, title=title, doc_type=doc_type, data=fetched.body, source_url=fetched.url, user_id=user_id)
    else:
        text = fetched.body.decode("utf-8", errors="replace")
        if fetched.content_type == "text/html":
            text = html_to_text(text)
        doc = rag.ingest_text_document(db, ipo_id=ipo_id, title=title, doc_type=doc_type, text=text[:2_000_000], source_url=fetched.url, user_id=user_id)
    return doc, fetched
