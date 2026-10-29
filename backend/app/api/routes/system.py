"""Health, model/provider status, dashboard summary and listing-model training."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import AuthContext, audit, optional_user, require_admin
from app.config import get_settings
from app.db import get_db
from app.models import DocumentChunk, ResearchReport, SourceDocument, WatchlistItem
from app.services import prediction
from app.services.ipo_service import all_ipos, get_active_config_row, score_ipo, score_summary, serialize_ipo_summary
from app.services.llm_provider import reset_health_cache, select_provider

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "version": __version__, "database": "ok" if db_ok else "unavailable",
            "environment": get_settings().environment}


@router.get("/models/status")
def models_status(db: Session = Depends(get_db), refresh: bool = False) -> dict[str, Any]:
    if refresh:
        reset_health_cache()
    s = get_settings()
    sel = select_provider(s)
    cfg = get_active_config_row(db)
    n_chunks = db.execute(select(func.count(DocumentChunk.id))).scalar_one()
    n_emb = db.execute(select(func.count(DocumentChunk.id)).where(DocumentChunk.embedding.is_not(None))).scalar_one()
    return {
        "ai": {
            "configured_provider": s.ai_provider,
            "active_mode": sel.mode,
            "generative_available": sel.provider is not None,
            "reason": sel.reason,
            "ollama": {"base_url": s.ollama_base_url, "model": s.active_ollama_model, "small_model": s.ollama_small_model,
                       "using_small_model": s.ollama_use_small_model, "embed_model": s.ollama_embed_model},
            "providers": sel.health,
            "fallback": "Deterministic research engine (no generative AI): answers are composed from stored data and engine outputs.",
        },
        "retrieval": {"chunks": n_chunks, "embedded_chunks": n_emb, "mode": "embedding+keyword" if n_emb else "keyword (BM25)"},
        "scoring": {"active_version": cfg.version, "description": cfg.description},
        "listing_model": {"models": prediction.models_overview(db), "real_listed_ipos": prediction.real_data_count(db),
                          "min_samples": cfg.config["listing_model"]["min_samples"], "warning": prediction.WARNING},
    }


class TrainIn(BaseModel):
    synthetic: bool = False


@router.post("/models/train")
def train_model(body: TrainIn, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    res = prediction.run_training(db, synthetic=body.synthetic)
    audit(db, request, "model_train", ctx.user.id, synthetic=body.synthetic, status=res["status"])
    res.pop("params", None)
    return res


@router.get("/dashboard/summary")
def dashboard(db: Session = Depends(get_db), ctx: AuthContext | None = Depends(optional_user)) -> dict[str, Any]:
    today = date.today()
    ipos = all_ipos(db)
    rows = []
    stale = []
    for ipo in ipos:
        s = serialize_ipo_summary(ipo, today)
        res = score_ipo(db, ipo)
        s["scores"] = score_summary(res)
        rows.append(s)
        if res["evidence"]["financials_stale"]:
            stale.append(ipo.company.name)
    by_status: dict[str, int] = {}
    sectors: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        sec = sectors.setdefault(r["sector"], {"sector": r["sector"], "count": 0, "issue_size_cr": 0.0})
        sec["count"] += 1
        sec["issue_size_cr"] += r["issue_size_cr"] or 0.0
    size_buckets = [("< ₹100 cr", 0, 100), ("₹100–500 cr", 100, 500), ("₹500–1,000 cr", 500, 1000), ("₹1,000–2,500 cr", 1000, 2500), ("> ₹2,500 cr", 2500, 1e12)]
    sizes = [{"bucket": b, "count": sum(1 for r in rows if r["issue_size_cr"] is not None and lo <= r["issue_size_cr"] < hi)} for b, lo, hi in size_buckets]
    recent_cut = today - timedelta(days=120)
    upcoming = sorted([r for r in rows if r["status"] in ("open", "upcoming")], key=lambda r: (r["status"] != "open", r["open_date"] or ""))
    listed = sorted([r for r in rows if r["status"] == "listed" and r["listing_date"] and r["listing_date"] >= recent_cut.isoformat()],
                    key=lambda r: r["listing_date"], reverse=True)
    scatter = [{"id": r["id"], "name": r["company_name"], "quality": r["scores"]["quality"], "risk": r["scores"]["risk"],
                "composite": r["scores"]["composite"], "data_status": r["data_status"], "sector": r["sector"]}
               for r in rows if r["scores"]["quality"] is not None and r["scores"]["risk"] is not None]
    freshest = max((r["last_updated"] for r in rows if r["last_updated"]), default=None)
    docs = db.execute(select(func.count(SourceDocument.id))).scalar_one()
    out: dict[str, Any] = {
        "as_of": today.isoformat(),
        "totals": {"ipos": len(rows), "by_status": by_status, "documents": docs,
                   "issue_size_open_upcoming_cr": round(sum(r["issue_size_cr"] or 0 for r in upcoming), 2)},
        "data_modes": {m: sum(1 for r in rows if r["data_mode"] == m) for m in ("demo", "imported", "source")},
        "synthetic_share": round(sum(1 for r in rows if r["data_status"] == "synthetic") / len(rows), 4) if rows else 0.0,
        "upcoming": upcoming[:8],
        "recently_listed": listed[:8],
        "scatter": scatter,
        "sectors": sorted(sectors.values(), key=lambda x: -x["count"]),
        "issue_sizes": sizes,
        "freshness": {"latest_record_update": freshest, "stale_financials": stale},
        "watchlist": [],
        "recent_reports": [],
    }
    if ctx is not None:
        ids = [w.ipo_id for w in db.execute(select(WatchlistItem).where(WatchlistItem.user_id == ctx.user.id)).scalars()]
        out["watchlist"] = [r for r in rows if r["id"] in ids]
        out["recent_reports"] = [{"id": r.id, "title": r.title, "ipo_id": r.ipo_id, "generator": r.generator, "created_at": r.created_at.isoformat()}
                                 for r in db.execute(select(ResearchReport).where(ResearchReport.user_id == ctx.user.id)
                                                     .order_by(ResearchReport.created_at.desc()).limit(5)).scalars()]
    return out
