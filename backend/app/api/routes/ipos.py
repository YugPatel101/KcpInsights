from __future__ import annotations

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
    ResearchScore,
    SourceDocument,
    SourceRecord,
    WatchlistItem,
)
from app.services import prediction
from app.services.financial_metrics import compute_quality_metrics
from app.services.ipo_service import (
    STATUS_ORDER,
    all_ipos,
    build_scoring_inputs,
    current_statements,
    get_active_config,
    get_ipo,
    score_ipo,
    score_summary,
    serialize_ipo_detail,
    serialize_ipo_summary,
    serialize_statements,
    to_period,
)
from app.services.scenario import run_scenarios

router = APIRouter(prefix="/api/ipos", tags=["ipos"])

SortKey = Literal["open_date", "-open_date", "composite", "-composite", "quality", "-quality", "risk", "-risk", "issue_size", "-issue_size", "name"]


def _csv(v: str | None) -> set[str]:
    return {x.strip().lower() for x in v.split(",") if x.strip()} if v else set()


@router.get("")
def list_ipos(
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, description="comma-separated: upcoming,open,closed,listed,withdrawn"),
    exchange: str | None = Query(None, max_length=60),
    issue_type: Literal["mainboard", "sme"] | None = None,
    sector: str | None = Query(None, max_length=200),
    data_mode: Literal["demo", "imported", "source"] | None = None,
    min_issue_size: float | None = Query(None, ge=0),
    max_issue_size: float | None = Query(None, ge=0),
    min_quality: float | None = Query(None, ge=0, le=100),
    min_valuation: float | None = Query(None, ge=0, le=100),
    max_risk: float | None = Query(None, ge=0, le=100),
    risk_level: Literal["low", "moderate", "high"] | None = None,
    sort: SortKey = "-open_date",
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    statuses, sectors, exchanges = _csv(status), _csv(sector), _csv(exchange)
    rows = []
    for ipo in all_ipos(db):
        s = serialize_ipo_summary(ipo)
        if q and q.lower() not in f"{s['company_name']} {s['symbol'] or ''} {s['sector']} {s['industry'] or ''}".lower():
            continue
        if statuses and s["status"] not in statuses:
            continue
        if sectors and s["sector"].lower() not in sectors:
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
        sc = score_summary(score_ipo(db, ipo))
        if min_quality is not None and (sc["quality"] is None or sc["quality"] < min_quality):
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
        if key == "open_date":
            v = r["open_date"] or ""
        elif key == "name":
            v = r["company_name"].lower()
        elif key == "issue_size":
            v = r["issue_size_cr"]
        else:
            v = r["scores"][key]
        # missing values always sort last
        return (v is None, v if not desc or v is None else _neg(v))

    rows.sort(key=sort_key)
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start : start + page_size], "total": total, "page": page, "page_size": page_size}


def _neg(v: Any) -> Any:
    if isinstance(v, (int, float)):
        return -v
    # reverse string ordering
    return "".join(chr(0x10FFFF - ord(c)) for c in str(v))


@router.get("/meta")
def ipo_meta(db: Session = Depends(get_db)) -> dict[str, Any]:
    ipos = all_ipos(db)
    sectors: dict[str, int] = {}
    exchanges: set[str] = set()
    statuses: dict[str, int] = {k: 0 for k in STATUS_ORDER}
    modes: dict[str, int] = {}
    for ipo in ipos:
        s = serialize_ipo_summary(ipo)
        sectors[s["sector"]] = sectors.get(s["sector"], 0) + 1
        for e in s["exchange"].split(","):
            exchanges.add(e.strip())
        statuses[s["status"]] = statuses.get(s["status"], 0) + 1
        modes[s["data_mode"]] = modes.get(s["data_mode"], 0) + 1
    return {"sectors": dict(sorted(sectors.items())), "exchanges": sorted(exchanges), "statuses": statuses, "data_modes": modes, "total": len(ipos)}


def _load(db: Session, ipo_id: int):
    ipo = get_ipo(db, ipo_id)
    if ipo is None:
        raise not_found("IPO")
    return ipo


@router.get("/{ipo_id}")
def ipo_detail(ipo_id: int, db: Session = Depends(get_db), ctx: AuthContext | None = Depends(optional_user)) -> dict[str, Any]:
    ipo = _load(db, ipo_id)
    out = serialize_ipo_detail(ipo)
    out["scores"] = score_summary(score_ipo(db, ipo))
    out["documents"] = [
        {"id": d.id, "title": d.title, "doc_type": d.doc_type, "page_count": d.page_count, "source_url": d.source_url,
         "data_status": d.data_status, "retrieved_at": d.retrieved_at.isoformat(), "injection_flags": d.injection_flags}
        for d in db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo_id)).scalars()
    ]
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
    ipo = _load(db, ipo_id)
    stmts = current_statements(db, ipo.company_id)
    metrics = compute_quality_metrics([to_period(s) for s in stmts])
    return {
        "ipo_id": ipo_id,
        "company_name": ipo.company.name,
        "currency": "INR",
        "unit": "crore",
        "statements": serialize_statements(stmts),
        "metrics": {k: m.to_dict() for k, m in metrics.items()},
        "note": "Amounts in INR crore after unit conversion. Only 12-month periods feed annual metrics.",
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
         "composite": r.composite, "quality": r.quality, "valuation": r.valuation, "risk": r.risk, "coverage": r.coverage,
         "input_fingerprint": r.input_fingerprint}
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
        stmts = current_statements(db, ipo.company_id)
        metrics = compute_quality_metrics([to_period(s) for s in stmts])
        items.append({
            "ipo": serialize_ipo_summary(ipo),
            "scores": score_summary(res),
            "quality_components": {k: v["score"] for k, v in res["quality"]["components"].items()},
            "risk_components": {k: v["score"] for k, v in res["risk"]["components"].items()},
            "valuation": {k: res["valuation"].get(k) for k in ("multiple_label", "ipo_multiple", "peer_median", "peer_low", "peer_high",
                                                               "premium_to_median_pct", "market_cap_cr", "reason")},
            "metrics": {k: {"value": m.value, "unit": m.unit, "status": m.status} for k, m in metrics.items()},
            "latest_financials": serialize_statements(stmts)[-1] if stmts else None,
            "warnings": res["warnings"],
        })
    return {"items": items, "config_version": get_active_config(db)["version"],
            "note": "Side-by-side educational comparison. Scores share one configuration version so they are comparable."}


class ScenarioOverride(BaseModel):
    revenue_growth_pct: float | None = Field(None, ge=-90, le=300)
    ebitda_margin_pct: float | None = Field(None, ge=-100, le=100)
    pat_to_ebitda: float | None = Field(None, ge=0, le=1.5)
    multiple: float | None = Field(None, gt=0, le=500)
    market_adjustment_pct: float | None = Field(None, ge=-90, le=200)
    method: Literal["pe", "ev_ebitda"] | None = None


class ScenarioIn(BaseModel):
    overrides: dict[Literal["bear", "base", "bull"], ScenarioOverride] = Field(default_factory=dict)


@router.post("/{ipo_id}/scenario")
def scenario(ipo_id: int, body: ScenarioIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    ipo = _load(db, ipo_id)
    inputs = build_scoring_inputs(db, ipo)
    ov: dict[str, dict[str, Any]] = {str(k): v.model_dump(exclude_none=True) for k, v in body.overrides.items()}
    return run_scenarios(inputs, get_active_config(db), ov)


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


@router.get("/{ipo_id}/prediction")
def ipo_prediction(ipo_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    ipo = _load(db, ipo_id)
    return prediction.prediction_for_ipo(db, ipo)


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
