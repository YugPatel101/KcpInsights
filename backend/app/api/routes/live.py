"""Live-data endpoints: market overview, convenience IPO lists, freshness and sync control.

All reads come from the database. Upstream sources are contacted only by scheduled
ingestion jobs (or an administrator's manual sync), never per browser request, so a
source outage returns the latest stored snapshot with stale-data indicators.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, audit, require_admin
from app.config import get_settings
from app.core.errors import ApiError, not_found
from app.db import get_db
from app.ingestion import data_quality_service as dq
from app.ingestion.ingestion_scheduler import JOB_TYPES, run_in_background, scheduler_status
from app.ingestion.ipo_data_service import field_provenance, recent_changes
from app.ingestion.source_registry import ensure_sources
from app.models import IngestionJob
from app.services.ipo_service import (
    EMPTY_SUMMARY,
    all_ipos,
    cached_score_summaries,
    effective_status,
    get_ipo,
    include_demo_default,
    serialize_ipo_summary,
)

router = APIRouter(prefix="/api", tags=["live data"])


def _rows(db: Session, include_demo: bool | None) -> list[dict[str, Any]]:
    inc = include_demo_default(db) if include_demo is None else include_demo
    today = date.today()
    scores = cached_score_summaries(db)
    out = []
    for ipo in all_ipos(db):
        if not inc and ipo.data_mode == "demo":
            continue
        r = serialize_ipo_summary(ipo, today)
        r["scores"] = scores.get(ipo.id) or EMPTY_SUMMARY
        out.append(r)
    return out


def _between(d: str | None, lo: date, hi: date) -> bool:
    return d is not None and lo.isoformat() <= d <= hi.isoformat()


@router.get("/ipos/upcoming")
def upcoming(db: Session = Depends(get_db), days: int = Query(30, ge=1, le=180), include_demo: bool | None = None) -> dict[str, Any]:
    today = date.today()
    items = sorted([r for r in _rows(db, include_demo) if r["status"] == "upcoming" and (r["open_date"] is None or _between(r["open_date"], today, today + timedelta(days=days)))],
                   key=lambda r: r["open_date"] or "9999")
    return {"items": items, "total": len(items), "window_days": days}


@router.get("/ipos/open")
def open_now(db: Session = Depends(get_db), include_demo: bool | None = None) -> dict[str, Any]:
    items = sorted([r for r in _rows(db, include_demo) if r["status"] == "open"], key=lambda r: r["close_date"] or "")
    return {"items": items, "total": len(items)}


@router.get("/ipos/recently-listed")
def recently_listed(db: Session = Depends(get_db), days: int = Query(60, ge=1, le=365), include_demo: bool | None = None) -> dict[str, Any]:
    today = date.today()
    items = sorted([r for r in _rows(db, include_demo) if r["status"] == "listed" and _between(r["listing_date"], today - timedelta(days=days), today)],
                   key=lambda r: r["listing_date"] or "", reverse=True)
    return {"items": items, "total": len(items), "window_days": days,
            "note": "Listing return = (listing-day open − final issue price) / final issue price. Shown only when both are verified."}


@router.get("/market/overview")
def market_overview(db: Session = Depends(get_db), include_demo: bool | None = None) -> dict[str, Any]:
    rows = _rows(db, include_demo)
    today = date.today()
    week_end = today + timedelta(days=(6 - today.weekday()) + 7)
    listed_recent = [r for r in rows if r["status"] == "listed" and _between(r["listing_date"], today - timedelta(days=30), today)]
    returns = [r["listing_return_pct"] for r in listed_recent if r["listing_return_pct"] is not None]
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    last = dq.last_successful_job(db, "discover")
    return {
        "as_of": today.isoformat(),
        "counts": by_status,
        "open": sorted([r for r in rows if r["status"] == "open"], key=lambda r: r["close_date"] or ""),
        "opening_soon": sorted([r for r in rows if r["status"] == "upcoming" and _between(r["open_date"], today, week_end)], key=lambda r: r["open_date"] or ""),
        "listing_soon": sorted([r for r in rows if r["status"] == "closed" and not r["freshness"].get("listing_unconfirmed")],
                               key=lambda r: r["listing_date"] or "9999"),
        "listing_unconfirmed": [r for r in rows if r["freshness"].get("listing_unconfirmed")],
        "recently_listed": sorted(listed_recent, key=lambda r: r["listing_date"] or "", reverse=True)[:12],
        "listing_stats_30d": {
            "count_with_verified_return": len(returns),
            "positive": sum(1 for x in returns if x > 0),
            "negative": sum(1 for x in returns if x < 0),
            "median_return_pct": sorted(returns)[len(returns) // 2] if returns else None,
            "note": "Descriptive statistics of past listings; not a forecast.",
        },
        "data": {
            "last_successful_sync_at": last.finished_at.isoformat() if last and last.finished_at else None,
            "stale_records": sum(1 for r in rows if r["freshness"]["is_stale"]),
            "live_records": sum(1 for r in rows if r["data_mode"] == "source"),
            "demo_records_included": any(r["data_mode"] == "demo" for r in rows),
        },
    }


@router.get("/ipos/{ipo_id}/subscription")
def subscription(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    ipo = get_ipo(db, ipo_id)
    if ipo is None:
        raise not_found("IPO")
    snaps = dq.subscription_rows(db, ipo_id)
    latest = max((s.as_of for s in snaps if s.basis == "consolidated"), default=None)
    status = effective_status(ipo)
    return {
        "ipo_id": ipo_id,
        "company_name": ipo.company.name,
        "status": status,
        "latest_as_of": latest.isoformat() if latest else None,
        "timezone": "IST" if ipo.nse_symbol else None,
        "basis_note": "Consolidated multiple per category (all exchanges) as published by NSE, with its 'Updated as on' time.",
        "latest": [{"category": s.category, "times_subscribed": s.times_subscribed, "shares_offered": s.shares_offered, "shares_bid": s.shares_bid,
                    "data_status": s.data_status} for s in snaps if s.as_of == latest and s.basis == "consolidated"],
        "history": [{"as_of": s.as_of.isoformat(), "category": s.category, "times_subscribed": s.times_subscribed, "basis": s.basis} for s in snaps],
        "freshness": dq.ipo_freshness(ipo, status),
        "source_url": ipo.source_record.source_url if ipo.source_record else None,
    }


@router.get("/ipos/{ipo_id}/changes")
def changes(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if get_ipo(db, ipo_id) is None:
        raise not_found("IPO")
    return {"ipo_id": ipo_id, "changes": recent_changes(db, ipo_id, limit=100)}


@router.get("/ipos/{ipo_id}/provenance")
def provenance(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if get_ipo(db, ipo_id) is None:
        raise not_found("IPO")
    return {"ipo_id": ipo_id, "fields": field_provenance(db, ipo_id),
            "statuses": {"verified": "from an official source, parsed and validated", "estimated": "derived (e.g. SEBI T+3 timeline, upper-band price)",
                         "imported": "user import", "synthetic": "fictional demo data", "secondary_source": "non-authoritative cross-check"}}


@router.get("/data/freshness")
def freshness(db: Session = Depends(get_db), include_demo: bool | None = None) -> dict[str, Any]:
    ensure_sources(db)
    rows = _rows(db, include_demo)
    stale = [{"id": r["id"], "company_name": r["company_name"], "status": r["status"], "reasons": r["freshness"]["stale_reasons"]}
             for r in rows if r["freshness"]["is_stale"]]
    missing = [{"id": r["id"], "company_name": r["company_name"], "status": r["status"], "missing": r["freshness"]["missing_critical"]}
               for r in rows if r["freshness"]["missing_critical"] and r["status"] in ("upcoming", "open", "closed")]
    last = dq.last_successful_job(db)
    return {
        "last_successful_sync_at": last.finished_at.isoformat() if last and last.finished_at else None,
        "last_successful_job": last.job_type if last else None,
        "sources": dq.source_overview(db),
        "stale_records": stale,
        "missing_critical_fields": missing[:50],
        "recent_changes": recent_changes(db, since=None, limit=20),
        "scheduler": scheduler_status(),
    }


@router.get("/data/sync-status")
def sync_status(db: Session = Depends(get_db), limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    ensure_sources(db)
    jobs = db.execute(select(IngestionJob).order_by(IngestionJob.id.desc()).limit(limit)).scalars()
    s = get_settings()
    return {
        "scheduler": scheduler_status(),
        "intervals_minutes": {"discover": s.ingest_discovery_minutes, "details": s.ingest_details_minutes, "subscriptions": s.ingest_subscription_minutes,
                              "listings": s.ingest_listing_minutes, "health": s.ingest_health_minutes, "documents": s.ingest_documents_minutes,
                              "filings": s.ingest_filings_minutes, "peers": s.ingest_peer_prices_minutes,
                              "enrichment": s.ingest_enrichment_minutes},
        "jobs": [{"id": j.id, "job_type": j.job_type, "trigger": j.trigger, "status": j.status, "started_at": j.started_at.isoformat(),
                  "finished_at": j.finished_at.isoformat() if j.finished_at else None, "records_discovered": j.records_discovered,
                  "records_created": j.records_created, "records_updated": j.records_updated, "fields_changed": j.fields_changed,
                  "requests_made": j.requests_made, "errors": j.errors[:10], "detail": {k: v for k, v in (j.detail or {}).items() if k != "warnings"},
                  "warning_count": len((j.detail or {}).get("warnings", []))} for j in jobs],
        "sources": dq.source_overview(db),
    }


class SyncIn(BaseModel):
    job: Literal["all", "discover", "details", "subscriptions", "listings", "filings", "documents", "peers", "enrichment", "health"] = "all"


@router.post("/admin/data-sync", status_code=202)
def admin_sync(body: SyncIn, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    if body.job not in (*JOB_TYPES, "all"):
        raise ApiError(422, "unknown_job", f"job must be one of: all, {', '.join(JOB_TYPES)}")
    run_in_background(body.job, "admin")
    audit(db, request, "data_sync", ctx.user.id, job=body.job)
    return {"accepted": True, "job": body.job, "note": "Running in the background; follow progress in GET /api/data/sync-status."}
