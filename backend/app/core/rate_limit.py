"""In-process sliding-window rate limiter.

Adequate for the single-process local deployment. Behind several workers or hosts,
replace with a shared store (documented limitation).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import ApiError

LIMITS: dict[str, tuple[int, float]] = {
    "login": (8, 300.0),  # per IP+email: 8 attempts / 5 minutes
    "login_ip": (30, 300.0),  # per IP across e-mails
    "register": (5, 3600.0),
    "agent": (20, 60.0),
    "agent_anon": (6, 60.0),
    "report": (10, 60.0),
    "import": (10, 60.0),
    "upload": (10, 300.0),
    "source_fetch": (6, 60.0),
    "analyze": (30, 60.0),
}


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str) -> None:
        limit, window = LIMITS[bucket]
        now = time.monotonic()
        k = f"{bucket}:{key}"
        with self._lock:
            q = self._hits[k]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                retry = int(window - (now - q[0])) + 1
                raise ApiError(429, "rate_limited", f"Too many requests. Try again in {retry} s.", {"retry_after": retry})
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
