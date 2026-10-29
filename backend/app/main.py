"""KcpInsights API — FastAPI application factory."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import auth, data, ipos, system, workspace
from app.config import get_settings
from app.core.errors import install_error_handlers

log = logging.getLogger("kcp")


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
    for name in ("kcp", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(_RedactFilter())

    app = FastAPI(
        title="KcpInsights API",
        version=__version__,
        description=(
            "Educational IPO research platform: transparent quantitative scoring, provenance-tracked data and a "
            "tool-using research agent. Nothing here is investment advice."
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
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if s.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    for r in (system.router, auth.router, ipos.router, workspace.router, data.router):
        app.include_router(r)
    return app


app = create_app()
