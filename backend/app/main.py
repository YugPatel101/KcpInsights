"""KcpInsights API — FastAPI application factory."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app import __version__
from app.api.routes import analytics, auth, data, ipos, live, research, system, workspace
from app.config import get_settings
from app.core.errors import install_error_handlers

log = logging.getLogger("kcp")


class _JsonFormatter(logging.Formatter):
    """One JSON object per line (KCP_LOG_FORMAT=json) for log shippers; same redaction as text logs."""

    def format(self, record: logging.LogRecord) -> str:
        out = {"time": self.formatTime(record), "level": record.levelname, "logger": record.name, "message": record.getMessage()}
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


class _RedactFilter(logging.Filter):
    """Keep secrets and session cookies out of logs."""

    SENSITIVE = ("password", "kcp_session", "authorization", "api_key", "x-csrf-token")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage()).lower()
        if any(s in msg for s in self.SENSITIVE):
            record.msg, record.args = "[redacted log line containing sensitive data]", ()
        return True


def create_app() -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if s.log_format == "json":
        for h in logging.getLogger().handlers:
            h.setFormatter(_JsonFormatter())
    for name in ("kcp", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(_RedactFilter())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Live-data scheduler runs inside the API process unless disabled (tests, separate worker).
        if s.scheduler_enabled and s.ingest_enabled and s.environment != "test":
            from app.ingestion.ingestion_scheduler import start_scheduler, stop_scheduler

            start_scheduler()
            yield
            stop_scheduler()
        else:
            yield

    app = FastAPI(
        lifespan=lifespan,
        title="KcpInsights API",
        version=__version__,
        description=(
            "Educational IPO research platform: automated IPO and prospectus data, standard financial ratios and "
            "transparent quantitative scoring with provenance. Nothing here is investment advice."
        ),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    allowed_origins = {o.rstrip("/") for o in s.cors_origin_list}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Reject cross-site state-changing requests whose Origin is not allowed (defence in depth with CSRF tokens).
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in allowed_origins:
                host = request.headers.get("host", "")
                if urlparse(origin).netloc != host:
                    return JSONResponse({"error": {"code": "origin_rejected", "message": "Cross-origin request rejected", "details": None}}, status_code=403)
        try:
            response = await asyncio.wait_for(call_next(request), timeout=s.request_timeout_seconds)
        except TimeoutError:
            return JSONResponse({"error": {"code": "timeout", "message": "Request timed out", "details": None}}, status_code=504)
        if request.method == "GET" and response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json"):
            # Conditional requests: identical snapshots answer 304, so polling clients re-download nothing.
            body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
            etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            if request.headers.get("if-none-match") == etag:
                response = Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, no-cache"})
            else:
                response = Response(content=body, status_code=200, media_type="application/json",
                                    headers={k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")})
                response.headers["ETag"] = etag
                response.headers["Cache-Control"] = "private, no-cache"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if s.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    # live.router first: its /api/ipos/upcoming etc. must match before /api/ipos/{ipo_id}
    for r in (system.router, auth.router, live.router, research.router, analytics.router, ipos.router, workspace.router, data.router):
        app.include_router(r)
    return app


app = create_app()
