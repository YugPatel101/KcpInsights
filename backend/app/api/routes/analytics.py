"""Historical listing performance, industry benchmarks, methodology, the field registry and system health."""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.financials.ocr import tesseract_available
from app.financials.statement_parser import PARSER_VERSION
from app.models import FieldObservation, FinancialStatement, IngestionJob, ResearchScore, ScoringConfigVersion, SourceDocument, utcnow
from app.services import quant_engine as qe
from app.services.field_registry import GROUP_WEIGHTS, GROUPS, registry
from app.services.ipo_service import (
    EMPTY_SUMMARY,
    all_ipos,
    cached_score_summaries,
    effective_status,
    get_active_config_row,
    include_demo_default,
    latest_subscription,
    listing_close_return_pct,
    listing_return_pct,
)

router = APIRouter(prefix="/api", tags=["analytics"])

SIZE_BUCKETS = [("< ₹50 cr", 0, 50), ("₹50–250 cr", 50, 250), ("₹250–1,000 cr", 250, 1000), ("₹1,000–5,000 cr", 1000, 5000), ("> ₹5,000 cr", 5000, 1e12)]


def _pct(a: float | None, b: float | None) -> float | None:
    return round((a - b) / b * 100, 2) if a is not None and b else None


def _published(doc: SourceDocument) -> date | None:
    """When an offer document became public: SEBI filing date, else the server's Last-Modified header."""
    if doc.published_date:
        return doc.published_date
    if doc.http_last_modified:
        try:
            return parsedate_to_datetime(doc.http_last_modified).date()
        except (TypeError, ValueError):
            return None
    return None


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation (average ranks for ties)."""
    n = len(xs)
    if n < 3:
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(num / den, 3) if den else None


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "positive_share": None, "min": None, "max": None}
    return {"n": len(values), "mean": round(statistics.fmean(values), 2), "median": round(statistics.median(values), 2),
            "positive_share": round(sum(1 for v in values if v > 0) / len(values) * 100, 1), "min": round(min(values), 2), "max": round(max(values), 2)}


@router.get("/history")
def listing_history(db: Session = Depends(get_db), issue_type: str | None = Query(None, pattern="^(mainboard|sme)$"),
                    sector: str | None = Query(None, max_length=120), since: date | None = None, include_demo: bool | None = None) -> dict[str, Any]:
    """Listed IPOs with verified listing-day prices, outcome statistics and score-versus-outcome analysis.

    Listing gain = (listing-day open − final issue price) ÷ final issue price × 100; the closing return uses the listing-day close.
    Only scores computed from information published before the listing date are compared with outcomes.
    """
    today = date.today()
    show_demo = include_demo_default(db) if include_demo is None else include_demo
    scores = cached_score_summaries(db)
    latest_rows = {r.ipo_id: r for r in db.execute(select(ResearchScore).where(
        ResearchScore.id.in_(select(func.max(ResearchScore.id)).group_by(ResearchScore.ipo_id)))).scalars()}
    docs = {d.id: d for d in db.execute(select(SourceDocument)).scalars()}
    rows = []
    for ipo in all_ipos(db):
        if (not show_demo and ipo.data_mode == "demo") or effective_status(ipo, today) != "listed":
            continue
        if issue_type and ipo.issue_type != issue_type:
            continue
        if sector and ipo.company.sector != sector:
            continue
        if since and (ipo.listing_date is None or ipo.listing_date < since):
            continue
        sc = scores.get(ipo.id) or EMPTY_SUMMARY
        sub = latest_subscription(ipo)
        # point-in-time check: every document behind the score's statements must predate the listing
        cutoff_ok, cutoff_note = None, None
        row = latest_rows.get(ipo.id)
        if row is not None and sc["composite"] is not None:
            used = [docs.get(p.get("document_id")) for p in (row.breakdown.get("period_sources") or [])]
            dates = [_published(d) for d in used if d is not None]
            if ipo.data_mode == "demo":
                cutoff_ok, cutoff_note = False, "synthetic demonstration data"
            elif not used or any(d is None for d in used):
                cutoff_ok, cutoff_note = False, "statements not traceable to a dated official document"
            elif any(x is None for x in dates):
                cutoff_ok, cutoff_note = False, "publication date of the offer document unknown"
            elif ipo.listing_date and all(x <= ipo.listing_date for x in dates if x is not None):
                cutoff_ok, cutoff_note = True, "score inputs (offer document, final issue price, listed peers) were all public before listing"
            else:
                cutoff_ok, cutoff_note = False, "uses a document published after the listing date"
        rows.append({
            "id": ipo.id, "company_name": ipo.company.name, "sector": ipo.company.sector, "issue_type": ipo.issue_type,
            "listing_date": ipo.listing_date.isoformat() if ipo.listing_date else None, "issue_size_cr": ipo.issue_size_cr,
            "final_issue_price": ipo.final_issue_price, "listing_open": ipo.listing_price, "listing_high": ipo.listing_high_price,
            "listing_low": ipo.listing_low_price, "listing_close": ipo.listing_close_price,
            "listing_gain_pct": listing_return_pct(ipo), "listing_close_return_pct": listing_close_return_pct(ipo),
            "listing_high_return_pct": _pct(ipo.listing_high_price, ipo.final_issue_price),
            "listing_low_return_pct": _pct(ipo.listing_low_price, ipo.final_issue_price),
            "listing_data_status": ipo.listing_data_status, "subscription_total": (sub or {}).get("categories", {}).get("total"),
            "subscription_as_of": (sub or {}).get("as_of"), "pre_listing_score": sc["composite"] if cutoff_ok else None,
            "score_classification": sc["classification"] if cutoff_ok else None, "risk": sc["risk"] if cutoff_ok else None,
            "score_available": sc["composite"] is not None, "point_in_time_ok": cutoff_ok, "point_in_time_note": cutoff_note,
            "data_mode": ipo.data_mode,
        })
    rows.sort(key=lambda r: r["listing_date"] or "", reverse=True)
    priced = [r for r in rows if r["listing_gain_pct"] is not None]

    def group(key: str) -> list[dict[str, Any]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for r in priced:
            out.setdefault(r[key] or "Unclassified", []).append(r)
        return sorted(({"group": k, **_summary([x["listing_gain_pct"] for x in v]),
                        "median_close_return": round(statistics.median([x["listing_close_return_pct"] for x in v if x["listing_close_return_pct"] is not None]), 2)
                        if any(x["listing_close_return_pct"] is not None for x in v) else None} for k, v in out.items()), key=lambda g: -g["n"])

    by_size = []
    for label, lo, hi in SIZE_BUCKETS:
        v = [r["listing_gain_pct"] for r in priced if r["issue_size_cr"] is not None and lo <= r["issue_size_cr"] < hi]
        by_size.append({"group": label, **_summary(v)})
    pairs = [(r["pre_listing_score"], r["listing_gain_pct"]) for r in priced if r["pre_listing_score"] is not None]
    rho = _spearman([a for a, _ in pairs], [b for _, b in pairs])
    return {
        "items": rows, "count": len(rows), "with_listing_price": len(priced),
        "summary": {"listing_gain": _summary([r["listing_gain_pct"] for r in priced]),
                    "listing_close_return": _summary([r["listing_close_return_pct"] for r in priced if r["listing_close_return_pct"] is not None])},
        "by_sector": group("sector"), "by_issue_type": group("issue_type"), "by_issue_size": by_size,
        "score_vs_outcome": {"pairs": [{"score": a, "listing_gain_pct": b} for a, b in pairs], "n": len(pairs), "spearman_rho": rho,
                             "note": ("Rank correlation between the pre-listing fundamental score and the listing gain. With fewer than 30 "
                                      "observations it is descriptive only, and listing-day moves reflect demand and market conditions that "
                                      "the fundamental score does not measure. Past outcomes do not predict future performance.")},
        "formulas": {"listing_gain": "Listing gain = (listing-day open − final issue price) ÷ final issue price × 100",
                     "listing_close_return": "Listing-day closing return = (listing-day close − final issue price) ÷ final issue price × 100"},
        "source": "Final issue price and listing date: NSE past issues. Listing-day open, high, low and close: NSE bhavcopy of the listing date.",
    }


@router.get("/industries")
def industries(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Sectors on record with their analysis profile and median ratios across scored IPOs (benchmarks), plus the profile registry."""
    cfg = get_active_config_row(db).config
    latest = {r.ipo_id: r for r in db.execute(select(ResearchScore).where(
        ResearchScore.id.in_(select(func.max(ResearchScore.id)).group_by(ResearchScore.ipo_id)))).scalars()}
    keys = ("roe", "roce", "roa", "net_margin", "ebitda_margin", "revenue_cagr", "pat_cagr", "current_ratio", "debt_to_equity", "interest_coverage",
            "ocf_to_pat", "receivable_days", "inventory_days", "pe", "pb")
    sectors: dict[str, dict[str, Any]] = {}
    for ipo in all_ipos(db):
        if ipo.data_mode == "demo":
            continue
        c = ipo.company
        sec = sectors.setdefault(c.sector, {"sector": c.sector, "profile": c.industry_profile or "general", "ipos": 0, "scored": 0, "_vals": {}})
        sec["ipos"] += 1
        row = latest.get(ipo.id)
        if row is None or not row.breakdown.get("periods_used"):
            continue
        sec["scored"] += 1
        for k in keys:
            mt = (row.breakdown.get("metrics") or {}).get(k) or {}
            if mt.get("status") == "ok" and mt.get("value") is not None:
                sec["_vals"].setdefault(k, []).append(mt["value"])
    out = []
    for sec in sectors.values():
        vals = sec.pop("_vals")
        sec["benchmarks"] = {k: {"median": round(statistics.median(v), 2), "n": len(v)} for k, v in vals.items()}
        sec["indicative_only"] = sec["scored"] < 3
        out.append(sec)
    profiles = [{"key": k, "label": v.get("label"), "not_applicable": v.get("not_applicable", []), "reasons": v.get("reasons", {}),
                 "not_applicable_components": v.get("not_applicable_components", []), "weights": v.get("weights", {}),
                 "ranges": v.get("ranges", {})} for k, v in (cfg.get("profiles") or {}).items()]
    return {"sectors": sorted(out, key=lambda s: -s["ipos"]), "profiles": profiles,
            "note": ("Benchmarks are medians across IPOs on record in each sector, from verified statements only. With fewer than three "
                     "scored IPOs a benchmark is indicative only.")}


@router.get("/methodology")
def methodology(db: Session = Depends(get_db)) -> dict[str, Any]:
    """The active scoring configuration, every formula and the configuration history — rendered by the methodology page."""
    row = get_active_config_row(db)
    versions = db.execute(select(ScoringConfigVersion).order_by(ScoringConfigVersion.id.desc()).limit(20)).scalars()
    return {"active_version": row.version, "description": row.description, "config": row.config, "formulas": qe.FORMULAS,
            "component_labels": qe.COMPONENT_LABELS, "disclaimer": qe.DISCLAIMER, "parser_version": PARSER_VERSION,
            "versions": [{"version": v.version, "is_active": v.is_active, "created_at": v.created_at.isoformat(), "description": v.description}
                         for v in versions]}


class FieldRegistryOut(BaseModel):
    groups: dict[str, str]
    group_weights: dict[str, float]
    fields: list[dict[str, Any]]


@router.get("/fields", response_model=FieldRegistryOut)
def fields() -> dict[str, Any]:
    """The central field registry: sources, precedence, normalisation, validation, refresh and staleness per field."""
    return {"groups": GROUPS, "group_weights": GROUP_WEIGHTS, "fields": registry()}


@router.get("/system/health")
def system_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Pipeline monitoring: scheduler, sources, jobs, document processing, dead letters, completeness and conflicts."""
    from app.ingestion import data_quality_service as dq
    from app.ingestion.ingestion_scheduler import scheduler_status
    from app.services import operations as ops

    s = get_settings()
    now = utcnow()
    since = now - timedelta(hours=24)
    jobs = list(db.execute(select(IngestionJob).where(IngestionJob.started_at >= since)).scalars())
    by_type: dict[str, dict[str, Any]] = {}
    for j in jobs:
        t = by_type.setdefault(j.job_type, {"job_type": j.job_type, "runs": 0, "success": 0, "partial": 0, "failed": 0, "skipped": 0,
                                            "requests": 0, "last_status": None, "last_finished_at": None, "last_error": None})
        t["runs"] += 1
        t[j.status] = t.get(j.status, 0) + 1
        t["requests"] += j.requests_made or 0
        if t["last_finished_at"] is None or (j.finished_at and j.finished_at.isoformat() > t["last_finished_at"]):
            t["last_status"], t["last_finished_at"] = j.status, j.finished_at.isoformat() if j.finished_at else None
            t["last_error"] = (j.errors[-1].get("error") if j.errors else None)
    docs = list(db.execute(select(SourceDocument).where(SourceDocument.source_key.is_not(None))).scalars())
    matrix: dict[str, dict[str, int]] = {}
    for d in docs:
        matrix.setdefault(d.source_key or "other", {})[d.extraction_status] = matrix.setdefault(d.source_key or "other", {}).get(d.extraction_status, 0) + 1
    dead = [d for d in docs if d.extraction_status == "failed" and (d.attempts or 0) >= s.document_max_attempts]
    backing_off = [d for d in docs if d.next_attempt_at and d.next_attempt_at > now]
    stale_parser = sum(1 for d in docs if d.parser_version and d.parser_version != PARSER_VERSION and d.extraction_status not in ("duplicate", "pending"))
    ipos = [i for i in all_ipos(db) if i.data_mode != "demo"]
    funnel_keys = ("discovered", "located", "downloaded", "extracted", "validated", "calculated", "scored")
    funnel = {k: {"done": 0, "failed": 0, "pending": 0} for k in funnel_keys}
    for i in ipos:
        for k, st in ((i.completeness_summary or {}).get("pipeline") or {}).items():
            if k in funnel and st in funnel[k]:
                funnel[k][st] += 1
    comp = [i.completeness_pct for i in ipos if i.completeness_pct is not None]
    stale_live = [i for i in ipos if effective_status(i) in ("open", "upcoming") and i.last_verified_at
                  and now - i.last_verified_at > timedelta(hours=s.stale_issue_details_hours)]
    return {
        "as_of": now.isoformat(), "scheduler": scheduler_status(), "sources": dq.source_overview(db),
        "jobs_24h": sorted(by_type.values(), key=lambda t: t["job_type"]),
        "documents": {"by_source_and_status": matrix, "total": len(docs), "parser_version": PARSER_VERSION, "awaiting_reprocessing": stale_parser,
                      "retained_mb": round(sum(d.size_bytes or 0 for d in docs if d.original_retained) / 1024 / 1024, 1),
                      "storage_limit_mb": s.documents_max_total_mb, "ocr_available": tesseract_available(), "ocr_enabled": s.ocr_enabled,
                      "max_attempts": s.document_max_attempts},
        "dead_letters": [{"document_id": d.id, "ipo_id": d.ipo_id, "title": d.title, "attempts": d.attempts, "error": d.extraction_error} for d in dead],
        "backing_off": [{"document_id": d.id, "ipo_id": d.ipo_id, "title": d.title, "attempts": d.attempts,
                         "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None, "error": d.extraction_error} for d in backing_off],
        "pipeline_funnel": [{"stage": k, **funnel[k]} for k in funnel_keys],
        "completeness": {"ipos": len(ipos), "computed": len(comp), "median": round(statistics.median(comp), 1) if comp else None,
                         "below_50": sum(1 for c in comp if c < 50)},
        "integrity": {"statements_requiring_review": db.execute(select(func.count(FinancialStatement.id)).where(
                          FinancialStatement.is_current.is_(True), FinancialStatement.data_status == "requires_review")).scalar_one(),
                      "field_conflicts": db.execute(select(func.count(FieldObservation.id)).where(FieldObservation.conflict.is_(True))).scalar_one(),
                      "stale_live_issues": [{"ipo_id": i.id, "company_name": i.company.name,
                                             "last_verified_at": i.last_verified_at.isoformat() if i.last_verified_at else None} for i in stale_live]},
        "hosting_note": ("Scheduled jobs run only while the API process (or `python -m app.cli worker`) is running. A host that sleeps when idle "
                         "does not run them; see docs/DEPLOYMENT.md."),
        "problems": ops.health_problems(db),
        "backups": {"enabled": s.backup_enabled, "every_hours": s.backup_hours, "keep": s.backup_keep, "count": len(ops.list_backups()),
                    "last_at": last.isoformat() if (last := ops.last_backup_at()) else None},
    }
