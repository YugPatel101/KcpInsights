"""Agent chat, reports and watchlist — user-scoped resources."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.ipo_research_agent import IPOResearchAgent
from app.api.deps import AuthContext, audit, optional_user, require_user
from app.core.errors import ApiError, not_found
from app.core.rate_limit import client_ip, limiter
from app.db import get_db
from app.models import AgentConversation, AgentMessage, ResearchReport, ToolCallAudit, WatchlistItem, utcnow
from app.services.ipo_service import get_ipo, score_ipo, score_summary, serialize_ipo_summary
from app.services.report_service import build_report, save_report

router = APIRouter(prefix="/api", tags=["workspace"])


# ---------------------------------------------------------------------------- agent
class ChatIn(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    conversation_id: int | None = None
    ipo_id: int | None = Field(default=None, ge=1)


@router.post("/agent/chat")
def agent_chat(body: ChatIn, request: Request, db: Session = Depends(get_db), ctx: AuthContext | None = Depends(optional_user)) -> dict[str, Any]:
    limiter.hit("agent" if ctx else "agent_anon", str(ctx.user.id) if ctx else client_ip(request))
    convo: AgentConversation | None = None
    if body.conversation_id is not None:
        if ctx is None:
            raise ApiError(401, "unauthorized", "Sign in to continue a saved conversation")
        convo = db.get(AgentConversation, body.conversation_id)
        if convo is None or convo.user_id != ctx.user.id:  # never reveal other users' conversations
            raise not_found("conversation")
    if body.ipo_id is not None and get_ipo(db, body.ipo_id) is None:
        raise not_found("IPO")

    agent = IPOResearchAgent(db, ctx.user if ctx else None)
    result = agent.run(body.message, context_ipo_id=body.ipo_id or (convo.ipo_id if convo else None))

    if ctx is not None:
        if convo is None:
            convo = AgentConversation(user_id=ctx.user.id, title=body.message[:80], ipo_id=body.ipo_id or (result["ipo_ids"][0] if result["ipo_ids"] else None))
            db.add(convo)
            db.flush()
        db.add(AgentMessage(conversation_id=convo.id, role="user", content=body.message))
        db.add(AgentMessage(conversation_id=convo.id, role="assistant", content=result["answer_text"],
                            meta={k: result[k] for k in ("answer", "mode", "evidence", "tool_calls", "warnings", "intents", "ipo_ids", "report_id")}))
        convo.updated_at = utcnow()
    for c in result["tool_calls"]:
        db.add(ToolCallAudit(conversation_id=convo.id if convo else None, user_id=ctx.user.id if ctx else None, tool_name=c["tool"][:64],
                             arguments=c["arguments"], status=c["status"], result_summary=c["summary"][:2000], duration_ms=c["duration_ms"]))
    db.commit()
    result["conversation_id"] = convo.id if convo else None
    result["saved"] = convo is not None
    return result


@router.get("/agent/conversations")
def list_conversations(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> list[dict[str, Any]]:
    rows = db.execute(select(AgentConversation).where(AgentConversation.user_id == ctx.user.id).order_by(AgentConversation.updated_at.desc()).limit(100)).scalars()
    return [{"id": c.id, "title": c.title, "ipo_id": c.ipo_id, "updated_at": c.updated_at.isoformat()} for c in rows]


@router.get("/agent/conversations/{cid}")
def get_conversation(cid: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    c = db.execute(select(AgentConversation).where(AgentConversation.id == cid).options(selectinload(AgentConversation.messages))).scalar_one_or_none()
    if c is None or c.user_id != ctx.user.id:
        raise not_found("conversation")
    return {"id": c.id, "title": c.title, "ipo_id": c.ipo_id,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "meta": m.meta, "created_at": m.created_at.isoformat()} for m in c.messages]}


@router.delete("/agent/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> None:
    c = db.get(AgentConversation, cid)
    if c is None or c.user_id != ctx.user.id:
        raise not_found("conversation")
    db.delete(c)
    db.commit()


# ---------------------------------------------------------------------------- reports
class ReportIn(BaseModel):
    ipo_id: int = Field(ge=1)
    use_ai: bool = True


@router.post("/reports/generate", status_code=201)
def generate_report(body: ReportIn, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    limiter.hit("report", str(ctx.user.id))
    ipo = get_ipo(db, body.ipo_id)
    if ipo is None:
        raise not_found("IPO")
    report = build_report(db, ipo, use_llm=body.use_ai)
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
    for w in items:
        ipo = get_ipo(db, w.ipo_id)
        if ipo is None:
            continue
        s = serialize_ipo_summary(ipo)
        s["scores"] = score_summary(score_ipo(db, ipo))
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

