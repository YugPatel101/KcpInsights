from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, audit, optional_user, require_user
from app.config import get_settings
from app.core.errors import ApiError
from app.core.rate_limit import client_ip, limiter
from app.core.security import (
    hash_password,
    hash_token,
    needs_rehash,
    new_csrf_token,
    new_session_token,
    password_problems,
    verify_password,
)
from app.db import get_db
from app.models import User, UserSession, utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: str


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, display_name=u.display_name, is_admin=u.is_admin)


def _start_session(db: Session, response: Response, request: Request, user: User) -> SessionOut:
    s = get_settings()
    token = new_session_token()
    sess = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_csrf_token(),
        expires_at=utcnow() + timedelta(hours=s.session_ttl_hours),
        user_agent=(request.headers.get("user-agent") or "")[:255],
    )
    db.add(sess)
    user.last_login_at = utcnow()
    db.commit()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        secure=s.is_production,
        samesite="lax",
        path="/",
    )
    return SessionOut(user=_user_out(user), csrf_token=sess.csrf_token, expires_at=sess.expires_at.isoformat())


@router.post("/register", response_model=SessionOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    limiter.hit("register", client_ip(request))
    email = body.email.lower()
    problems = password_problems(body.password, email)
    if problems:
        raise ApiError(422, "weak_password", "Password requirements: " + "; ".join(problems))
    if db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none():
        raise ApiError(409, "email_taken", "An account with this e-mail already exists")
    user = User(email=email, display_name=body.display_name.strip(), password_hash=hash_password(body.password), is_admin=False)
    db.add(user)
    db.commit()
    audit(db, request, "register", user.id)
    return _start_session(db, response, request, user)


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    email = body.email.lower()
    ip = client_ip(request)
    limiter.hit("login_ip", ip)
    limiter.hit("login", f"{ip}:{email}")
    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, body.password) or user is None or not user.is_active:
        audit(db, request, "login_failed", user.id if user else None, email_domain=email.split("@")[-1])
        raise ApiError(401, "invalid_credentials", "Invalid e-mail or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    out = _start_session(db, response, request, user)
    audit(db, request, "login", user.id)
    return out


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, ctx: AuthContext = Depends(require_user), db: Session = Depends(get_db)) -> Response:
    sess = db.get(UserSession, ctx.session.id)
    if sess is not None:
        sess.revoked = True
        db.commit()
    audit(db, request, "logout", ctx.user.id)
    s = get_settings()
    response.delete_cookie(s.session_cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=SessionOut | None)
def me(ctx: AuthContext | None = Depends(optional_user)) -> SessionOut | None:
    if ctx is None:
        return None
    return SessionOut(user=_user_out(ctx.user), csrf_token=ctx.session.csrf_token, expires_at=ctx.session.expires_at.isoformat())
