"""Health, configuration status and the dashboard summary."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import AuthContext, optional_user
from app.config import get_settings
from app.db import get_db
from app.models import DocumentChunk, ResearchReport, SourceDocument, WatchlistItem
from app.services.ipo_service import EMPTY_SUMMARY, all_ipos, cached_score_summaries, get_active_config_row, include_demo_default, serialize_ipo_summary

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
def models_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = get_active_config_row(db)
    n_chunks = db.execute(select(func.count(DocumentChunk.id))).scalar_one()
    return {
        "retrieval": {"chunks": n_chunks, "mode": "keyword (BM25)"},
        "scoring": {"active_version": cfg.version, "description": cfg.description},
    }


@router.get("/dashboard/summary")
def dashboard(db: Session = Depends(get_db), ctx: AuthContext | None = Depends(optional_user), include_demo: bool | None = None) -> dict[str, Any]:
    today = date.today()
    show_demo = include_demo_default(db) if include_demo is None else include_demo
    ipos = [i for i in all_ipos(db) if show_demo or i.data_mode != "demo"]
    scores = cached_score_summaries(db)  # stored results: the dashboard never recomputes scores
    rows = []
    for ipo in ipos:
        s = serialize_ipo_summary(ipo, today)
        s["scores"] = scores.get(ipo.id) or EMPTY_SUMMARY
        rows.append(s)
    by_status: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    sectors: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
        sec = sectors.setdefault(r["sector"], {"sector": r["sector"], "count": 0, "issue_size_cr": 0.0})
        sec["count"] += 1
        sec["issue_size_cr"] += r["issue_size_cr"] or 0.0
    size_buckets = [("< ₹100 cr", 0, 100), ("₹100–500 cr", 100, 500), ("₹500–1,000 cr", 500, 1000), ("₹1,000–2,500 cr", 1000, 2500), ("> ₹2,500 cr", 2500, 1e12)]
    sizes = [{"bucket": b, "count": sum(1 for r in rows if r["issue_size_cr"] is not None and lo <= r["issue_size_cr"] < hi)} for b, lo, hi in size_buckets]
    recent_cut = (today - timedelta(days=30)).isoformat()
    upcoming = sorted([r for r in rows if r["status"] in ("open", "upcoming")], key=lambda r: (r["status"] != "open", r["open_date"] or ""))
    awaiting = sorted([r for r in rows if r["stage"] in ("awaiting_allotment", "awaiting_listing")], key=lambda r: r["listing_date"] or "9999")
    listed = sorted([r for r in rows if r["status"] == "listed" and r["listing_date"] and r["listing_date"] >= recent_cut],
                    key=lambda r: r["listing_date"], reverse=True)
    closed_cut = (today - timedelta(days=14)).isoformat()
    recently_closed = sorted([r for r in rows if r["status"] == "closed" and r["close_date"] and r["close_date"] >= closed_cut],
                             key=lambda r: r["close_date"], reverse=True)
    pipeline = sorted([r for r in rows if r["status"] == "pipeline"], key=lambda r: -r["id"])
    # data health: how complete the stored records are (completeness is not a confidence level)
    comp = [r["completeness_pct"] for r in rows if r["completeness_pct"] is not None]
    readiness: dict[str, int] = {"ready": 0, "partial": 0, "insufficient": 0}
    for r in rows:
        lvl = (r["completeness"] or {}).get("readiness")
        if lvl in readiness:
            readiness[lvl] += 1
    buckets = [("0–25%", 0, 25), ("25–50%", 25, 50), ("50–75%", 50, 75), ("75–100%", 75, 101)]
    data_health = {"median_completeness": round(sorted(comp)[len(comp) // 2], 1) if comp else None, "readiness": readiness,
                   "distribution": [{"bucket": b, "count": sum(1 for c in comp if lo <= c < hi)} for b, lo, hi in buckets],
                   "not_computed": len(rows) - len(comp)}
    # score distribution by descriptive class, risk distribution by level (only IPOs with a score)
    cfg = get_active_config_row(db).config
    classes = [lbl for _, lbl in cfg["classification"]]
    score_dist = [{"label": lbl, "count": sum(1 for r in rows if r["scores"]["classification"] == lbl)} for lbl in classes]
    risk_dist = [{"level": lv, "count": sum(1 for r in rows if r["scores"]["risk_level"] == lv)} for lv in ("low", "moderate", "elevated", "high")]
    scored = sum(1 for r in rows if r["scores"]["composite"] is not None)
    # IPO openings by month (last 6 months and next 2), from stored dates
    months: dict[str, dict[str, Any]] = {}
    for k in range(-6, 3):
        m = (today.replace(day=1) + timedelta(days=32 * k)).replace(day=1)
        months[m.strftime("%Y-%m")] = {"month": m.strftime("%Y-%m"), "mainboard": 0, "sme": 0, "issue_size_cr": 0.0}
    for r in rows:
        key = (r["open_date"] or "")[:7]
        if key in months:
            months[key]["sme" if r["issue_type"] == "sme" else "mainboard"] += 1
            months[key]["issue_size_cr"] += r["issue_size_cr"] or 0.0
    # next 21 days of dated events
    horizon = (today + timedelta(days=21)).isoformat()
    events = []
    for r in rows:
        for kind, d, est in (("opens", r["open_date"], False), ("closes", r["close_date"], False),
                             ("lists", r["listing_date"], r["listing_date_status"] == "expected")):
            if d and today.isoformat() <= d <= horizon:
                events.append({"date": d, "event": kind, "estimated": est, "ipo_id": r["id"], "company_name": r["company_name"], "issue_type": r["issue_type"]})
    events.sort(key=lambda e: (e["date"], e["event"]))
    freshest = max((r["last_updated"] for r in rows if r["last_updated"]), default=None)
    docs = db.execute(select(func.count(SourceDocument.id))).scalar_one()
    docs_extracted = db.execute(select(func.count(SourceDocument.id)).where(SourceDocument.extraction_status.in_(("extracted", "partial")))).scalar_one()
    from app.ingestion import data_quality_service as dq
    from app.ingestion.ipo_data_service import recent_changes

    last = dq.last_successful_job(db)
    names = {r["id"]: r["company_name"] for r in rows}
    changes = [c | {"company_name": names.get(c["ipo_id"])} for c in recent_changes(db, limit=60) if c["ipo_id"] in names][:12]
    out: dict[str, Any] = {
        "as_of": today.isoformat(),
        "totals": {"ipos": len(rows), "by_status": by_status, "by_stage": by_stage, "documents": docs, "documents_extracted": docs_extracted,
                   "pipeline": len(pipeline), "recently_closed_14d": len(recently_closed),
                   "scored": scored, "recently_listed_30d": len(listed),
                   "issue_size_open_upcoming_cr": round(sum(r["issue_size_cr"] or 0 for r in upcoming), 2)},
        "data_modes": {m: sum(1 for r in rows if r["data_mode"] == m) for m in ("demo", "imported", "source")},
        "demo_included": show_demo,
        "demo_available": any(i.data_mode == "demo" for i in all_ipos(db)),
        "synthetic_share": round(sum(1 for r in rows if r["data_status"] == "synthetic") / len(rows), 4) if rows else 0.0,
        "upcoming": upcoming[:10],
        "awaiting": awaiting[:10],
        "recently_closed": recently_closed[:10],
        "recently_listed": listed[:10],
        "pipeline": pipeline[:10],
        "data_health": data_health,
        "calendar": events[:40],
        "activity": list(months.values()),
        "scatter": [{"id": r["id"], "name": r["company_name"], "score": r["scores"]["composite"], "risk": r["scores"]["risk"],
                     "data_status": r["data_status"], "sector": r["sector"], "issue_type": r["issue_type"]}
                    for r in rows if r["scores"]["composite"] is not None and r["scores"]["risk"] is not None],
        "score_distribution": score_dist,
        "risk_distribution": risk_dist,
        "sectors": sorted(sectors.values(), key=lambda x: -x["count"]),
        "issue_sizes": sizes,
        "recent_changes": changes,
        "sources": dq.source_overview(db),
        "freshness": {"latest_record_update": freshest, "last_successful_sync_at": last.finished_at.isoformat() if last and last.finished_at else None,
                      "last_successful_job": last.job_type if last else None},
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
