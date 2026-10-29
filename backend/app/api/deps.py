"""Request dependencies: DB session, authentication, CSRF and audit logging."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import ApiError
from app.core.rate_limit import client_ip
from app.core.security import hash_token, tokens_equal
from app.db import get_db
from app.models import AuditLog, User, UserSession, utcnow

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class AuthContext:
    user: User
    session: UserSession


def _load_session(request: Request, db: Session) -> AuthContext | None:
    s = get_settings()
    token = request.cookies.get(s.session_cookie_name)
    if not token or len(token) > 200:
        return None
    sess = db.execute(select(UserSession).where(UserSession.token_hash == hash_token(token))).scalar_one_or_none()
    if sess is None or sess.revoked:
        return None
    now = utcnow()
    if sess.expires_at <= now or sess.last_seen_at + timedelta(hours=s.session_idle_hours) <= now:
        sess.revoked = True
        db.commit()
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    if now - sess.last_seen_at > timedelta(minutes=5):
        sess.last_seen_at = now
        db.commit()
    return AuthContext(user=user, session=sess)


def _check_csrf(request: Request, ctx: AuthContext) -> None:
    if request.method in UNSAFE_METHODS and not tokens_equal(request.headers.get("x-csrf-token"), ctx.session.csrf_token):
        raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token")


def optional_user(request: Request, db: Session = Depends(get_db)) -> AuthContext | None:
    ctx = _load_session(request, db)
    if ctx is not None:
        _check_csrf(request, ctx)
    return ctx


def require_user(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    ctx = _load_session(request, db)
    if ctx is None:
        raise ApiError(401, "unauthorized", "Sign in required")
    _check_csrf(request, ctx)
    return ctx


def require_admin(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    if not ctx.user.is_admin:
        raise ApiError(403, "forbidden", "Administrator privileges required")
    return ctx


def audit(db: Session, request: Request | None, action: str, user_id: int | None, **detail: Any) -> None:
    redacted = {k: ("***" if any(s in k.lower() for s in ("password", "token", "secret", "key")) else v) for k, v in detail.items()}
    db.add(AuditLog(user_id=user_id, action=action, detail=redacted, ip_address=client_ip(request) if request else None))
    db.commit()
