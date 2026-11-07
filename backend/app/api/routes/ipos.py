from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, audit, optional_user, require_user
from app.core.errors import ApiError, not_found
from app.core.rate_limit import client_ip, limiter
from app.db import get_db
from app.models import (
    FinancialLineItem,
    FinancialStatement,
    ResearchScore,
    SourceDocument,
    SourceRecord,
    WatchlistItem,
)
from app.services import quant_engine as qe
from app.services.ipo_service import (
    EMPTY_SUMMARY,
    STATUS_ORDER,
    all_ipos,
    build_engine_inputs,
    cached_score_summaries,
    current_statements,
    get_active_config,
    get_ipo,
    include_demo_default,
    score_ipo,
    score_summary,
    serialize_ipo_detail,
    serialize_ipo_summary,
    serialize_statements,
)
from app.services.issue_facts import issue_facts

router = APIRouter(prefix="/api/ipos", tags=["ipos"])

SortKey = Literal["open_date", "-open_date", "composite", "-composite", "risk", "-risk", "issue_size", "-issue_size", "name", "listing_date",
                  "-listing_date", "coverage", "-coverage", "completeness", "-completeness"]


def _csv(v: str | None) -> set[str]:
    return {x.strip().lower() for x in v.split(",") if x.strip()} if v else set()


@router.get("")
def list_ipos(
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, description="comma-separated: pipeline,upcoming,open,closed,listed,withdrawn"),
    exchange: str | None = Query(None, max_length=60),
    issue_type: Literal["mainboard", "sme"] | None = None,
    sector: str | None = Query(None, max_length=200),
    industry: str | None = Query(None, max_length=200),
    stage: str | None = Query(None, description="comma-separated: upcoming,open,awaiting_allotment,awaiting_listing,listing_unconfirmed,listed"),
    opening_from: date | None = None,
    opening_to: date | None = None,
    data_mode: Literal["demo", "imported", "source"] | None = None,
    include_demo: bool | None = Query(None, description="default: demo IPOs only while no real data exists"),
    min_issue_size: float | None = Query(None, ge=0),
    max_issue_size: float | None = Query(None, ge=0),
    min_score: float | None = Query(None, ge=0, le=100, description="minimum fundamental score Q"),
    max_score: float | None = Query(None, ge=0, le=100),
    min_valuation: float | None = Query(None, ge=0, le=100),
    max_risk: float | None = Query(None, ge=0, le=100),
    risk_level: Literal["low", "moderate", "elevated", "high"] | None = None,
    scored_only: bool = False,
    min_completeness: float | None = Query(None, ge=0, le=100, description="minimum data completeness (%)"),
    profile: str | None = Query(None, max_length=32, description="industry analysis profile, e.g. lender, manufacturing"),
    sort: SortKey = "-open_date",
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    statuses, sectors, exchanges, industries, stages = _csv(status), _csv(sector), _csv(exchange), _csv(industry), _csv(stage)
    show_demo = include_demo if include_demo is not None else (include_demo_default(db) or data_mode == "demo")
    scores = cached_score_summaries(db)  # stored results; never recomputed per request
    rows = []
    for ipo in all_ipos(db):
        if not show_demo and ipo.data_mode == "demo":
            continue
        s = serialize_ipo_summary(ipo)
        if q and q.lower() not in f"{s['company_name']} {s['symbol'] or ''} {s['sector']} {s['industry'] or ''}".lower():
            continue
        if statuses and s["status"] not in statuses:
            continue
        if sectors and s["sector"].lower() not in sectors:
            continue
        if industries and (s["industry"] or "").lower() not in industries:
            continue
        if stages and s["stage"] not in stages:
            continue
        if opening_from and (s["open_date"] is None or s["open_date"] < opening_from.isoformat()):
            continue
        if opening_to and (s["open_date"] is None or s["open_date"] > opening_to.isoformat()):
            continue
        if exchanges and not any(e in s["exchange"].lower() for e in exchanges):
            continue
        if issue_type and s["issue_type"] != issue_type:
            continue
        if data_mode and s["data_mode"] != data_mode:
            continue
        size = s["issue_size_cr"]
        if min_issue_size is not None and (size is None or size < min_issue_size):
            continue
        if max_issue_size is not None and (size is None or size > max_issue_size):
            continue
        if min_completeness is not None and (s["completeness_pct"] is None or s["completeness_pct"] < min_completeness):
            continue
        if profile and s["industry_profile"] != profile:
            continue
        sc = scores.get(ipo.id) or EMPTY_SUMMARY
        if scored_only and sc["composite"] is None:
            continue
        if min_score is not None and (sc["composite"] is None or sc["composite"] < min_score):
            continue
        if max_score is not None and (sc["composite"] is None or sc["composite"] > max_score):
            continue
        if min_valuation is not None and (sc["valuation"] is None or sc["valuation"] < min_valuation):
            continue
        if max_risk is not None and (sc["risk"] is None or sc["risk"] > max_risk):
            continue
        if risk_level and sc["risk_level"] != risk_level:
            continue
        s["scores"] = sc
        rows.append(s)

    desc = sort.startswith("-")
    key = sort.lstrip("-")

    def sort_key(r: dict[str, Any]) -> tuple:
        v: Any
        if key in ("open_date", "listing_date"):
            v = r[key] or None
        elif key == "name":
            v = r["company_name"].lower()
        elif key == "issue_size":
            v = r["issue_size_cr"]
        elif key == "completeness":
            v = r["completeness_pct"]
        else:
            v = r["scores"][key]
        # missing values always sort last
        return (v is None, v if not desc or v is None else _neg(v))

    rows.sort(key=sort_key)
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start : start + page_size], "total": total, "page": page, "page_size": page_size, "demo_included": show_demo}


def _neg(v: Any) -> Any:
    if isinstance(v, (int, float)):
        return -v
    # reverse string ordering
    return "".join(chr(0x10FFFF - ord(c)) for c in str(v))


@router.get("/meta")
def ipo_meta(db: Session = Depends(get_db)) -> dict[str, Any]:
    ipos = all_ipos(db)
    sectors: dict[str, int] = {}
    industries: dict[str, int] = {}
    stages: dict[str, int] = {}
    exchanges: set[str] = set()
    statuses: dict[str, int] = {k: 0 for k in STATUS_ORDER}
    modes: dict[str, int] = {}
    for ipo in ipos:
        s = serialize_ipo_summary(ipo)
        sectors[s["sector"]] = sectors.get(s["sector"], 0) + 1
        if s["industry"]:
            industries[s["industry"]] = industries.get(s["industry"], 0) + 1
        stages[s["stage"]] = stages.get(s["stage"], 0) + 1
        for e in s["exchange"].split(","):
            exchanges.add(e.strip())
        statuses[s["status"]] = statuses.get(s["status"], 0) + 1
        modes[s["data_mode"]] = modes.get(s["data_mode"], 0) + 1
    return {"sectors": dict(sorted(sectors.items())), "industries": dict(sorted(industries.items())), "stages": stages,
            "exchanges": sorted(exchanges), "statuses": statuses, "data_modes": modes, "total": len(ipos)}


def _load(db: Session, ipo_id: int):
    ipo = get_ipo(db, ipo_id)
    if ipo is None:
        raise not_found("IPO")
    return ipo


@router.get("/{ipo_id}")
def ipo_detail(ipo_id: int, db: Session = Depends(get_db), ctx: AuthContext | None = Depends(optional_user)) -> dict[str, Any]:
    ipo = _load(db, ipo_id)
    out = serialize_ipo_detail(ipo)
    result = score_ipo(db, ipo)
    out["scores"] = score_summary(result)
    out["issue_facts"] = issue_facts(db, ipo, result=result)
    from app.api.routes.data import _doc_out

    out["documents"] = [_doc_out(d) for d in db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo_id)
                                                        .order_by(SourceDocument.id.desc())).scalars()]
    out["watchlisted"] = bool(
        ctx and db.execute(select(WatchlistItem).where(WatchlistItem.user_id == ctx.user.id, WatchlistItem.ipo_id == ipo_id)).first()
    )
    out["can_edit"] = bool(ctx and (ctx.user.is_admin or (ipo.created_by is not None and ipo.created_by == ctx.user.id)))
    return out


class IPOPatch(BaseModel):
    description: str | None = Field(None, max_length=5000)
    business_model: str | None = Field(None, max_length=5000)
    research_notes: str | None = Field(None, max_length=5000)
    website: str | None = Field(None, max_length=300)
    risk_disclosures_reviewed: bool | None = None


@router.patch("/{ipo_id}")
def update_ipo(ipo_id: int, body: IPOPatch, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    ipo = _load(db, ipo_id)
    if not (ctx.user.is_admin or (ipo.created_by is not None and ipo.created_by == ctx.user.id)):
        raise ApiError(403, "forbidden", "Only the importer of this IPO or an administrator can edit it")
    changes = body.model_dump(exclude_unset=True)
    if "website" in changes and changes["website"] and not changes["website"].startswith(("http://", "https://")):
        raise ApiError(422, "invalid_url", "website must start with http(s)://")
    for k, v in changes.items():
        if k in ("description", "business_model", "website"):
            setattr(ipo.company, k, v)
        else:
            setattr(ipo, k, v)
    db.commit()
    audit(db, request, "ipo_edit", ctx.user.id, ipo_id=ipo_id, fields=sorted(changes))
    return serialize_ipo_detail(_load(db, ipo_id))


@router.get("/{ipo_id}/financials")
def ipo_financials(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Every current statement period (both bases, interim included) plus the engine's ratios and history."""
    ipo = _load(db, ipo_id)
    stmts = current_statements(db, ipo.company_id)
    cfg = get_active_config(db)
    inputs = build_engine_inputs(db, ipo)
    result = score_ipo(db, ipo)
    history = db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.is_current.is_(False))
                         .order_by(FinancialStatement.created_at.desc()).limit(50)).scalars()
    return {
        "ipo_id": ipo_id,
        "company_name": ipo.company.name,
        "currency": "INR",
        "unit": "crore",
        "basis_used": result["basis"],
        "statements": serialize_statements(stmts),
        "metrics": result["metrics"],
        "ratio_history": qe.ratio_history(inputs, cfg),
        "superseded": [{"id": h.id, "period_label": h.period_label, "basis": h.basis, "data_status": h.data_status,
                        "created_at": h.created_at.isoformat(), "document_id": h.document_id} for h in history],
        "formulas": qe.FORMULAS,
        "note": ("Amounts in INR crore (per-share figures in INR) as restated in the offer document. Ratios use 12-month periods of one "
                 "reporting basis only; interim periods are shown but not annualised."),
    }


@router.get("/{ipo_id}/financials/{statement_id}/provenance")
def statement_provenance(ipo_id: int, statement_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    ipo = _load(db, ipo_id)
    st = db.get(FinancialStatement, statement_id)
    if st is None or st.company_id != ipo.company_id:
        raise not_found("statement")
    items = db.execute(select(FinancialLineItem).where(FinancialLineItem.statement_id == statement_id).order_by(FinancialLineItem.id)).scalars()
    return {"statement_id": statement_id, "period_label": st.period_label, "basis": st.basis, "data_status": st.data_status,
            "validation_status": st.validation_status, "checks": st.validation or [], "document_id": st.document_id,
            "items": [{"field": i.field, "raw_label": i.raw_label, "raw_text": i.raw_text, "unit": i.unit, "value": i.value, "page": i.page,
                       "status": i.status, "validation_status": i.validation_status} for i in items]}


@router.get("/{ipo_id}/completeness")
def ipo_completeness(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Field-by-field data completeness with sources, freshness and the reason for every gap."""
    from app.services.completeness import refresh_completeness

    ipo = _load(db, ipo_id)
    cfg = get_active_config(db)
    result = qe.compute(build_engine_inputs(db, ipo), cfg)
    out = refresh_completeness(db, ipo, result, cfg)
    db.commit()
    return out


@router.get("/{ipo_id}/peers")
def ipo_peers(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Listed peers named in the offer document (with quartile benchmarks and staleness) plus similar IPOs on record."""
    from app.config import get_settings

    ipo = _load(db, ipo_id)
    result = score_ipo(db, ipo)
    detail = serialize_ipo_detail(ipo)
    ref = ipo.open_date or date.today()
    stale_days = get_settings().stale_peer_price_days
    peers = []
    for p in detail["peers"]:
        age = (ref - date.fromisoformat(p["as_of"])).days if p["as_of"] else None
        peers.append({**p, "price_age_days": age,
                      "stale": age is not None and age > stale_days,
                      "used_in_median": p["data_status"] == "verified" and bool(p["pe"] and p["pe"] > 0)})
    pr = result.get("peers") or {}
    ipo_pe = (result["metrics"].get("pe") or {}).get("value")
    ipo_pb = (result["metrics"].get("pb") or {}).get("value")
    scores = cached_score_summaries(db)
    similar = []
    if ipo.company.sector and ipo.company.sector != "Unclassified":
        for other in all_ipos(db):
            if other.id == ipo.id or other.company.sector != ipo.company.sector or other.data_mode == "demo":
                continue
            sc = scores.get(other.id) or EMPTY_SUMMARY
            similar.append({"id": other.id, "company_name": other.company.name, "issue_type": other.issue_type,
                            "open_date": other.open_date.isoformat() if other.open_date else None, "issue_size_cr": other.issue_size_cr,
                            "composite": sc["composite"], "risk": sc["risk"], "pe": sc["pe"], "completeness_pct": other.completeness_pct})
    warnings = []
    if any(p["stale"] for p in peers):
        warnings.append(f"Some peer prices are more than {stale_days} days older than the issue's opening date; their multiples may not reflect current valuations.")
    if pr.get("with_pe", 0) < (pr.get("min_peers") or 2):
        warnings.append("Insufficient peer coverage: fewer than two listed peers with a positive, consistent P/E. Valuation uses absolute ranges instead.")
    if pr.get("excluded_loss_making"):
        warnings.append(f"{pr['excluded_loss_making']} peer(s) without a positive P/E (loss-making or not disclosed) are excluded from the P/E median.")
    return {
        "ipo_id": ipo_id, "peers": peers, "benchmarks": pr,
        "ipo_multiples": {"pe": ipo_pe, "pb": ipo_pb, "price_basis": result["price"].get("price_basis"),
                          "pe_vs_median_pct": round((ipo_pe / pr["median_pe"] - 1) * 100, 1) if ipo_pe and pr.get("median_pe") else None,
                          "pb_vs_median_pct": round((ipo_pb / pr["median_pb"] - 1) * 100, 1) if ipo_pb and pr.get("median_pb") else None},
        "selection_rationale": ("Peers are the listed companies the issuer itself names as comparable in the 'Basis for Issue Price' section of its "
                                "offer document. A peer row is used only when its printed P/E agrees with its closing price ÷ diluted EPS within 10%. "
                                "KcpInsights does not add or remove peers by its own judgement."),
        "similar_ipos": sorted(similar, key=lambda x: x["open_date"] or "", reverse=True)[:12],
        "similar_basis": f"other IPOs on record classified as {ipo.company.sector}" if similar else None,
        "warnings": warnings,
        "note": ("Peer figures are as printed in the offer document on its stated basis and period; the latest close (NSE bhavcopy) "
                 "is shown separately where the peer could be matched to an NSE symbol."),
    }


@router.get("/{ipo_id}/scores")
def ipo_scores(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return score_ipo(db, _load(db, ipo_id))


@router.get("/{ipo_id}/scores/history")
def ipo_score_history(ipo_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _load(db, ipo_id)
    rows = db.execute(select(ResearchScore).where(ResearchScore.ipo_id == ipo_id).order_by(ResearchScore.id.desc()).limit(50)).scalars()
    return [
        {"id": r.id, "calculated_at": r.calculated_at.isoformat(), "config_version": r.config_version, "status": r.status,
         "composite": r.composite, "profitability": r.profitability, "growth": r.growth, "financial_health": r.financial_health,
         "cash_flow": r.cash_flow, "valuation": r.valuation, "risk": r.risk, "risk_level": r.risk_level,
         "classification": r.classification, "coverage": r.coverage, "input_fingerprint": r.input_fingerprint}
        for r in rows
    ]


@router.post("/{ipo_id}/analyze")
def analyze_ipo(ipo_id: int, request: Request, db: Session = Depends(get_db), ctx: AuthContext | None = Depends(optional_user)) -> dict[str, Any]:
    limiter.hit("analyze", client_ip(request))
    ipo = _load(db, ipo_id)
    result = score_ipo(db, ipo, persist=True)
    stored = db.execute(select(ResearchScore).where(ResearchScore.ipo_id == ipo_id).order_by(ResearchScore.id.desc()).limit(1)).scalar_one_or_none()
    return {"score_record_id": stored.id if stored else None, "result": result}


class CompareIn(BaseModel):
    ipo_ids: list[int] = Field(min_length=2, max_length=4)


@router.post("/compare")
def compare_ipos(body: CompareIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if len(set(body.ipo_ids)) != len(body.ipo_ids):
        raise ApiError(422, "duplicate_ids", "IPO ids must be distinct")
    items = []
    for i in body.ipo_ids:
        ipo = _load(db, i)
        res = score_ipo(db, ipo)
        stmts = [x for x in current_statements(db, ipo.company_id) if x.period_months == 12 and x.basis == res["basis"]]
        items.append({
            "ipo": serialize_ipo_summary(ipo),
            "scores": score_summary(res),
            "components": {k: {"score": v["score"], "coverage": v["coverage"]} for k, v in res["components"].items()},
            "risk_components": {c["key"]: c["points"] for c in res["risk"]["components"]},
            "metrics": {k: {"value": m["value"], "unit": m["unit"], "status": m["status"], "label": m["label"]} for k, m in res["metrics"].items()},
            "peers": res["peers"],
            "price": res["price"],
            "profile": res.get("profile"),
            "governance": res["risk"].get("governance_disclosure"),
            "completeness_pct": ipo.completeness_pct,
            "completeness": ipo.completeness_summary,
            "latest_financials": serialize_statements(stmts)[-1] if stmts else None,
            "warnings": res["warnings"],
        })
    return {"items": items, "config_version": get_active_config(db)["version"],
            "note": "Side-by-side educational comparison. Scores share one configuration version so they are comparable."}


@router.get("/{ipo_id}/valuation-sensitivity")
def valuation_sensitivity(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Multiples and scores at each end of the price band and at the final price (same formulas as the score)."""
    ipo = _load(db, ipo_id)
    return {"ipo_id": ipo_id, "rows": qe.price_sensitivity(build_engine_inputs(db, ipo), get_active_config(db)),
            "note": "Post-issue shares change with the price because the fresh issue raises a fixed amount."}


def collect_sources(db: Session, ipo) -> list[dict[str, Any]]:
    uses: dict[int, set[str]] = {}

    def add(rid: int | None, use: str) -> None:
        if rid:
            uses.setdefault(rid, set()).add(use)

    add(ipo.source_record_id, "issue details")
    for s in current_statements(db, ipo.company_id):
        add(s.source_record_id, f"financials {s.period_label}")
    for p in ipo.peers:
        add(p.source_record_id, f"peer {p.name}")
    for d in ipo.disclosures:
        add(d.source_record_id, f"risk: {d.title}")
    for s in ipo.subscriptions:
        add(s.source_record_id, "subscription")
    for g in ipo.gmp_observations:
        add(g.source_record_id, "grey-market premium (unofficial)")
    docs = db.execute(select(SourceDocument.id).where(SourceDocument.ipo_id == ipo.id)).scalars().all()
    if docs:
        for r in db.execute(select(SourceRecord).where(SourceRecord.document_id.in_(docs))).scalars():
            add(r.id, "document")
    out = []
    for r in db.execute(select(SourceRecord).where(SourceRecord.id.in_(list(uses)))).scalars():
        out.append({
            "id": r.id, "title": r.title, "url": r.source_url, "source_type": r.source_type, "data_status": r.data_status,
            "document_id": r.document_id, "document_page": r.document_page,
            "retrieved_at": r.retrieved_at.isoformat() if r.retrieved_at else None,
            "publication_date": r.publication_date.isoformat() if r.publication_date else None,
            "reporting_period": r.reporting_period, "currency": r.currency, "unit": r.unit, "transformation": r.transformation,
            "notes": r.notes, "used_for": sorted(uses[r.id]),
        })
    return sorted(out, key=lambda x: x["id"])


@router.get("/{ipo_id}/sources")
def ipo_sources(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    ipo = _load(db, ipo_id)
    return {"ipo_id": ipo_id, "sources": collect_sources(db, ipo)}


@router.post("/{ipo_id}/watch", status_code=201)
def watch(ipo_id: int, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    _load(db, ipo_id)
    existing = db.execute(select(WatchlistItem).where(WatchlistItem.user_id == ctx.user.id, WatchlistItem.ipo_id == ipo_id)).scalar_one_or_none()
    if existing is None:
        db.add(WatchlistItem(user_id=ctx.user.id, ipo_id=ipo_id))
        db.commit()
    return {"ipo_id": ipo_id, "watchlisted": True}


@router.delete("/{ipo_id}/watch")
def unwatch(ipo_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> dict[str, Any]:
    item = db.execute(select(WatchlistItem).where(WatchlistItem.user_id == ctx.user.id, WatchlistItem.ipo_id == ipo_id)).scalar_one_or_none()
    if item is not None:
        db.delete(item)
        db.commit()
    return {"ipo_id": ipo_id, "watchlisted": False}
