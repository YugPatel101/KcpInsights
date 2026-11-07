"""Reports and watchlist — user-scoped resources."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, audit, require_user
from app.core.errors import not_found
from app.core.rate_limit import limiter
from app.db import get_db
from app.models import ResearchReport, WatchlistItem
from app.services.ipo_service import EMPTY_SUMMARY, cached_score_summaries, get_ipo, serialize_ipo_summary
from app.services.report_service import build_report, save_report

router = APIRouter(prefix="/api", tags=["workspace"])


# ---------------------------------------------------------------------------- reports
class ReportIn(BaseModel):
    ipo_id: int = Field(ge=1)


@router.post("/reports/generate", status_code=201)
def generate_report(body: ReportIn, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    limiter.hit("report", str(ctx.user.id))
    ipo = get_ipo(db, body.ipo_id)
    if ipo is None:
        raise not_found("IPO")
    report = build_report(db, ipo)
    row = save_report(db, ctx.user.id, ipo, report)
    audit(db, request, "report_generate", ctx.user.id, report_id=row.id, ipo_id=ipo.id, generator=row.generator)
    return {"id": row.id, **report}


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    q = select(ResearchReport).where(ResearchReport.user_id == ctx.user.id).order_by(ResearchReport.created_at.desc())
    rows = list(db.execute(q).scalars())
    items = [{"id": r.id, "title": r.title, "ipo_id": r.ipo_id, "generator": r.generator, "config_version": r.config_version,
              "created_at": r.created_at.isoformat(), "scores": r.content.get("scores"), "synthetic": r.content.get("synthetic")}
             for r in rows[(page - 1) * page_size : page * page_size]]
    return {"items": items, "total": len(rows), "page": page, "page_size": page_size}


@router.get("/reports/{rid}")
def get_report(rid: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    r = db.get(ResearchReport, rid)
    if r is None or r.user_id != ctx.user.id:
        raise not_found("report")
    return {"id": r.id, "created_at": r.created_at.isoformat(), **r.content}


@router.delete("/reports/{rid}", status_code=204)
def delete_report(rid: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> None:
    r = db.get(ResearchReport, rid)
    if r is None or r.user_id != ctx.user.id:
        raise not_found("report")
    db.delete(r)
    db.commit()


# ---------------------------------------------------------------------------- watchlist
@router.get("/watchlist")
def watchlist(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> list[dict[str, Any]]:
    items = db.execute(select(WatchlistItem).where(WatchlistItem.user_id == ctx.user.id).order_by(WatchlistItem.created_at.desc())).scalars()
    out = []
    scores = cached_score_summaries(db)
    for w in items:
        ipo = get_ipo(db, w.ipo_id)
        if ipo is None:
            continue
        s = serialize_ipo_summary(ipo)
        s["scores"] = scores.get(ipo.id) or EMPTY_SUMMARY
        s["watch_note"] = w.note
        s["watched_at"] = w.created_at.isoformat()
        out.append(s)
    return out


class WatchNote(BaseModel):
    note: str | None = Field(None, max_length=500)


@router.patch("/watchlist/{ipo_id}")
def update_watch_note(ipo_id: int, body: WatchNote, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    w = db.execute(select(WatchlistItem).where(WatchlistItem.user_id == ctx.user.id, WatchlistItem.ipo_id == ipo_id)).scalar_one_or_none()
    if w is None:
        raise not_found("watchlist item")
    w.note = body.note
    db.commit()
    return {"ipo_id": ipo_id, "note": w.note}

