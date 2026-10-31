"""Database-facing IPO helpers: status, serialisation, scoring inputs, persisted scores."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    DataMode,
    FinancialStatement,
    IPOIssue,
    PeerSnapshot,
    ResearchScore,
    RiskDisclosure,
    ScoringConfigVersion,
    SourceRecord,
    SubscriptionSnapshot,
)
from app.services import quant_engine as qe
from app.services.scoring_config import SUPERSEDED_DEFAULT_VERSIONS, ConfigError, get_default_config, validate_config

STATUS_ORDER = ["open", "upcoming", "pipeline", "closed", "listed", "withdrawn"]


def effective_status(ipo: IPOIssue, today: date | None = None) -> str:
    """Status derived from dates so that stored records never go stale."""
    today = today or date.today()
    if ipo.status_override in ("withdrawn", "postponed"):
        return "withdrawn"
    # an *expected* listing date never makes an issue "listed" — only a confirmed one does
    if ipo.listing_date and ipo.listing_date <= today and ipo.listing_date_status != "expected":
        return "listed"
    if ipo.open_date and today < ipo.open_date:
        return "upcoming"
    if ipo.open_date and ipo.close_date and ipo.open_date <= today <= ipo.close_date:
        return "open"
    if ipo.close_date and today > ipo.close_date:
        return "closed"
    if ipo.open_date is None and ipo.close_date is None and ipo.listing_date is None:
        return "pipeline"  # an offer document is on file (e.g. a SEBI DRHP/RHP filing) but no dates are announced
    return "upcoming" if ipo.open_date is None else "closed"


def issue_stage(ipo: IPOIssue, status: str, today: date | None = None) -> str:
    """Finer lifecycle stage for closed issues: awaiting allotment → awaiting listing → listing unconfirmed."""
    today = today or date.today()
    if status != "closed":
        return status
    if ipo.allotment_date and today < ipo.allotment_date:
        return "awaiting_allotment"
    if ipo.listing_date and today <= ipo.listing_date:
        return "awaiting_listing"
    if ipo.listing_date and ipo.listing_date_status == "expected":
        return "listing_unconfirmed"
    return "awaiting_listing" if ipo.listing_date is None else "closed"


def issue_price(ipo: IPOIssue) -> float | None:
    return ipo.final_issue_price or ipo.price_band_high


def listing_return_pct(ipo: IPOIssue) -> float | None:
    """Listing gain = (listing-day open − final issue price) ÷ final issue price × 100. Never computed from a price band."""
    p = ipo.final_issue_price
    if ipo.listing_price is None or not p:
        return None
    return round((ipo.listing_price - p) / p * 100, 2)


def listing_close_return_pct(ipo: IPOIssue) -> float | None:
    """Listing-day closing return = (listing-day close − final issue price) ÷ final issue price × 100."""
    p = ipo.final_issue_price
    if ipo.listing_close_price is None or not p:
        return None
    return round((ipo.listing_close_price - p) / p * 100, 2)


def source_brief(rec: SourceRecord | None) -> dict[str, Any] | None:
    if rec is None:
        return None
    return {
        "id": rec.id,
        "title": rec.title,
        "url": rec.source_url,
        "source_type": rec.source_type,
        "data_status": rec.data_status,
        "retrieved_at": rec.retrieved_at.isoformat() if rec.retrieved_at else None,
    }


def latest_subscription(ipo: IPOIssue) -> dict[str, Any] | None:
    subs = [s for s in ipo.subscriptions if s.basis == "consolidated"] or list(ipo.subscriptions)
    if not subs:
        return None
    last_ts = max(s.as_of for s in subs)
    cats = {s.category: s for s in subs if s.as_of == last_ts}
    return {
        "as_of": last_ts.isoformat(),
        "timezone": "IST" if ipo.nse_symbol else None,
        "basis": next(iter(cats.values())).basis,
        "categories": {k: v.times_subscribed for k, v in cats.items()},
        "data_status": sorted({v.data_status for v in cats.values()}),
    }


def key_dates(ipo: IPOIssue) -> list[dict[str, Any]]:
    """Issue timeline with an explicit status per date (actual vs expected/estimated)."""
    live = bool(ipo.nse_symbol)
    rows = [
        ("open", "Bidding opens", ipo.open_date, "verified" if live else ipo.data_status),
        ("close", "Bidding closes", ipo.close_date, "verified" if live else ipo.data_status),
        ("allotment", "Allotment (expected)", ipo.allotment_date, "estimated"),
        ("refund", "Refunds (expected)", ipo.refund_date, "estimated"),
        ("demat_credit", "Demat credit (expected)", ipo.demat_credit_date, "estimated"),
    ]
    if ipo.listing_date_status == "expected":
        rows.append(("listing", "Listing (expected)", ipo.listing_date, "estimated"))
    else:
        rows.append(("listing", "Listing", ipo.listing_date, "verified" if live and ipo.listing_date_status == "actual" else ipo.data_status))
    return [{"key": k, "label": lbl, "date": d.isoformat() if d else None, "status": st if d else "unavailable"} for k, lbl, d, st in rows]


def serialize_ipo_summary(ipo: IPOIssue, today: date | None = None) -> dict[str, Any]:
    c = ipo.company
    lr = listing_return_pct(ipo)
    return {
        "id": ipo.id,
        "company_id": c.id,
        "company_name": c.name,
        "symbol": ipo.symbol,
        "sector": c.sector,
        "industry": c.industry,
        "exchange": ipo.exchange,
        "issue_type": ipo.issue_type,
        "status": (st := effective_status(ipo, today)),
        "stage": issue_stage(ipo, st, today),
        "open_date": ipo.open_date.isoformat() if ipo.open_date else None,
        "close_date": ipo.close_date.isoformat() if ipo.close_date else None,
        "listing_date": ipo.listing_date.isoformat() if ipo.listing_date else None,
        "price_band_low": ipo.price_band_low,
        "price_band_high": ipo.price_band_high,
        "final_issue_price": ipo.final_issue_price,
        "lot_size": ipo.lot_size,
        "min_investment_inr": round(ipo.lot_size * ipo.price_band_high, 2) if ipo.lot_size and ipo.price_band_high else None,
        "issue_size_cr": ipo.issue_size_cr,
        "fresh_issue_cr": ipo.fresh_issue_cr,
        "ofs_cr": ipo.ofs_cr,
        "listing_price": ipo.listing_price,
        "listing_close_price": ipo.listing_close_price,
        "listing_price_basis": ipo.listing_price_basis,
        "listing_return_pct": lr,
        "listing_close_return_pct": listing_close_return_pct(ipo),
        "listing_high_price": ipo.listing_high_price,
        "listing_low_price": ipo.listing_low_price,
        "industry_profile": c.industry_profile or "general",
        "completeness_pct": ipo.completeness_pct,
        "completeness": ipo.completeness_summary,
        "listing_data_status": ipo.listing_data_status if ipo.listing_price is not None else None,
        "listing_date_status": ipo.listing_date_status if ipo.listing_date else None,
        "nse_symbol": ipo.nse_symbol,
        "freshness": _freshness(ipo, today),
        "subscription": latest_subscription(ipo),
        "data_mode": ipo.data_mode,
        "data_status": ipo.data_status,
        "last_updated": ipo.updated_at.isoformat() if ipo.updated_at else None,
        "source": source_brief(ipo.source_record),
    }


def _freshness(ipo: IPOIssue, today: date | None) -> dict[str, Any]:
    from app.ingestion.data_quality_service import ipo_freshness

    return ipo_freshness(ipo, effective_status(ipo, today))


def serialize_ipo_detail(ipo: IPOIssue, today: date | None = None) -> dict[str, Any]:
    c = ipo.company
    out = serialize_ipo_summary(ipo, today)
    gmp = sorted(ipo.gmp_observations, key=lambda g: g.observed_at)
    out.update(
        {
            "description": c.description,
            "business_model": c.business_model,
            "revenue_sources": c.revenue_sources,
            "website": c.website,
            "customer_concentration_pct": c.customer_concentration_pct,
            "customer_concentration_basis": c.customer_concentration_basis,
            "face_value": ipo.face_value,
            "pre_issue_shares": ipo.pre_issue_shares,
            "post_issue_shares": ipo.post_issue_shares,
            "dilution_pct": round((ipo.post_issue_shares - ipo.pre_issue_shares) / ipo.post_issue_shares * 100, 3)
            if ipo.post_issue_shares and ipo.pre_issue_shares
            else None,
            "promoter_holding_pre_pct": ipo.promoter_holding_pre_pct,
            "promoter_holding_post_pct": ipo.promoter_holding_post_pct,
            "use_of_proceeds": ipo.use_of_proceeds,
            "risk_disclosures_reviewed": ipo.risk_disclosures_reviewed,
            "research_notes": ipo.research_notes,
            "created_by": ipo.created_by,
            "registrar": ipo.registrar,
            "lead_managers": ipo.lead_managers,
            "offer_document_url": ipo.offer_document_url,
            "basis_of_price_url": ipo.basis_of_price_url,
            "issue_size_text": ipo.issue_size_text,
            "shares_offered": ipo.shares_offered,
            "key_dates": key_dates(ipo),
            "subscription_history": [
                {"as_of": s.as_of.isoformat(), "category": s.category, "times_subscribed": s.times_subscribed, "basis": s.basis,
                 "shares_offered": s.shares_offered, "shares_bid": s.shares_bid, "data_status": s.data_status, "source_record_id": s.source_record_id}
                for s in sorted(ipo.subscriptions, key=lambda s: (s.as_of, s.category))
            ],
            "grey_market": {
                "caveat": (
                    "Grey-market premium is an unofficial, unregulated indication with no verifiable "
                    "order book. It is shown only when sourced and is not used in any score."
                ),
                "observations": [
                    {"observed_at": g.observed_at.isoformat(), "premium_inr": g.premium_inr,
                     "data_status": g.data_status, "source_record_id": g.source_record_id}
                    for g in gmp
                ],
            },
            "peers": [
                {"id": p.id, "name": p.name, "ticker": p.ticker, "sector": p.sector, "as_of": p.as_of.isoformat(),
                 "market_cap_cr": p.market_cap_cr, "pe": p.pe, "ev_ebitda": p.ev_ebitda, "pb": p.pb, "ps": p.ps,
                 "revenue_cr": p.revenue_cr, "selection_reason": p.selection_reason, "data_status": p.data_status,
                 "basis": p.basis, "period_label": p.period_label, "face_value": p.face_value, "closing_price": p.closing_price,
                 "eps_basic": p.eps_basic, "eps_diluted": p.eps_diluted, "nav_per_share": p.nav_per_share, "ronw_pct": p.ronw_pct,
                 "document_id": p.document_id, "page": p.page, "check_note": p.check_note,
                 "nse_symbol": p.nse_symbol, "latest_price": p.latest_price,
                 "latest_price_date": p.latest_price_date.isoformat() if p.latest_price_date else None,
                 "pe_at_latest_price": round(p.latest_price / p.eps_diluted, 2) if p.latest_price and p.eps_diluted and p.eps_diluted > 0 else None,
                 "source": source_brief(p.source_record)}
                for p in ipo.peers
            ],
            "disclosures": [
                {"id": d.id, "category": d.category, "severity": d.severity, "status": d.status, "title": d.title,
                 "description": d.description, "amount_cr": d.amount_cr, "data_status": d.data_status,
                 "source": source_brief(d.source_record)}
                for d in ipo.disclosures
            ],
            "document_facts": ipo.document_facts or {},
            "classification": c.classification,
            "events": [
                {"type": e.event_type, "date": e.event_date.isoformat(), "description": e.description}
                for e in sorted(ipo.events, key=lambda e: e.event_date)
            ],
        }
    )
    return out


IPO_LOAD_OPTIONS = (
    selectinload(IPOIssue.company),
    selectinload(IPOIssue.source_record),
    selectinload(IPOIssue.subscriptions),
    selectinload(IPOIssue.peers).selectinload(PeerSnapshot.source_record),
    selectinload(IPOIssue.disclosures).selectinload(RiskDisclosure.source_record),
    selectinload(IPOIssue.gmp_observations),
    selectinload(IPOIssue.events),
)


def get_ipo(db: Session, ipo_id: int) -> IPOIssue | None:
    return db.execute(select(IPOIssue).where(IPOIssue.id == ipo_id).options(*IPO_LOAD_OPTIONS)).scalar_one_or_none()


def include_demo_default(db: Session) -> bool:
    """Synthetic demo IPOs are shown only while no real (imported or live) IPO exists."""
    real = db.execute(select(IPOIssue.id).where(IPOIssue.data_mode != DataMode.demo.value).limit(1)).first()
    return real is None


def all_ipos(db: Session) -> list[IPOIssue]:
    return list(db.execute(select(IPOIssue).options(*IPO_LOAD_OPTIONS)).scalars().all())


def current_statements(db: Session, company_id: int) -> list[FinancialStatement]:
    rows = db.execute(
        select(FinancialStatement)
        .where(FinancialStatement.company_id == company_id, FinancialStatement.is_current.is_(True))
        .options(selectinload(FinancialStatement.source_record))
        .order_by(FinancialStatement.period_end)
    ).scalars()
    return list(rows)


STATEMENT_COLUMNS = (
    "revenue", "other_income", "total_income", "cost_of_materials", "employee_expenses", "other_expenses", "total_expenses", "ebitda",
    "depreciation", "ebit", "interest_expense", "pbt", "tax_expense", "pat", "eps_basic", "eps_diluted",
    "total_assets", "non_current_assets", "current_assets", "inventory", "trade_receivables", "cash_and_equivalents",
    "total_equity", "share_capital", "other_equity", "total_liabilities", "non_current_liabilities", "current_liabilities",
    "borrowings_non_current", "borrowings_current", "total_debt", "lease_liabilities",
    "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "capex",
)
PERIOD_FIELDS = tuple(f for f in qe.FinPeriod.__dataclass_fields__ if f not in ("label", "period_end", "months", "basis", "data_status",
                                                                                "validation_status", "source_record_id"))


def to_period(s: FinancialStatement) -> qe.FinPeriod:
    return qe.FinPeriod(label=s.period_label, period_end=s.period_end, months=s.period_months, basis=s.basis or "unknown",
                        data_status=s.data_status, validation_status=s.validation_status or "not_checked",
                        source_record_id=s.source_record_id, **{f: getattr(s, f) for f in PERIOD_FIELDS})


def serialize_statements(stmts: list[FinancialStatement]) -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "period_label": s.period_label,
            "period_end": s.period_end.isoformat(),
            "period_months": s.period_months,
            "currency": s.currency,
            "unit": s.unit,
            "basis": s.basis,
            **{f: getattr(s, f) for f in STATEMENT_COLUMNS},
            "data_status": s.data_status,
            "validation_status": s.validation_status,
            "validation": s.validation or [],
            "document_id": s.document_id,
            "source": source_brief(s.source_record),
        }
        for s in stmts
    ]


def build_engine_inputs(db: Session, ipo: IPOIssue, as_of: date | None = None) -> qe.EngineInputs:
    c: Company = ipo.company
    facts = ipo.document_facts or {}
    obs_status = None
    if ipo.post_issue_shares is not None:
        from app.models import FieldObservation

        obs = db.execute(select(FieldObservation).where(FieldObservation.ipo_id == ipo.id, FieldObservation.field == "post_issue_shares",
                                                        FieldObservation.applied.is_(True)).order_by(FieldObservation.id.desc()).limit(1)).scalar_one_or_none()
        obs_status = obs.data_status if obs else ipo.data_status
    issue = qe.IssueTerms(
        company_name=c.name, sector=c.sector, issue_type=ipo.issue_type, price_band_low=ipo.price_band_low, price_band_high=ipo.price_band_high,
        final_issue_price=ipo.final_issue_price, pre_issue_shares=ipo.pre_issue_shares, post_issue_shares=ipo.post_issue_shares,
        post_issue_shares_status=obs_status, fresh_issue_cr=ipo.fresh_issue_cr,
    )
    periods = [to_period(s) for s in current_statements(db, c.id)]
    peers = [qe.PeerMultiple(name=p.name, pe=p.pe, pb=p.pb, ronw_pct=p.ronw_pct, basis=p.basis, period_label=p.period_label, data_status=p.data_status)
             for p in ipo.peers]
    risk = qe.RiskFacts(
        customer_concentration_pct=c.customer_concentration_pct, customer_concentration_basis=c.customer_concentration_basis,
        contingent_liabilities_cr=(facts.get("contingent_liabilities_cr") or {}).get("value"),
        contingent_basis=(facts.get("contingent_liabilities_cr") or {}).get("basis"),
        auditor_qualifications=(facts.get("auditor_qualifications") or {}).get("value"),
        disclosures=[{"category": d.category, "severity": d.severity, "status": d.status, "title": d.title} for d in ipo.disclosures],
    )
    risk.lender_kpis = (facts.get("lender_kpis") or {}).get("value") or {}
    ref = as_of or (ipo.open_date if ipo.open_date and ipo.open_date <= date.today() else date.today())
    return qe.EngineInputs(issue=issue, periods=periods, peers=peers, facts=risk, as_of=ref, profile=c.industry_profile or "general")


# ---------------------------------------------------------------------------
# Scoring configuration
# ---------------------------------------------------------------------------
def get_active_config_row(db: Session) -> ScoringConfigVersion:
    row = db.execute(select(ScoringConfigVersion).where(ScoringConfigVersion.is_active.is_(True))).scalar_one_or_none()
    if row is not None:
        try:
            validate_config(row.config)
            stale_default = row.version in SUPERSEDED_DEFAULT_VERSIONS
        except (ConfigError, KeyError, TypeError):
            stale_default = True  # a configuration written for an earlier model version
        if stale_default:
            row.is_active = False  # kept as history
            db.flush()
            row = None
    if row is None:
        cfg = get_default_config()
        validate_config(cfg)
        row = db.execute(select(ScoringConfigVersion).where(ScoringConfigVersion.version == cfg["version"])).scalar_one_or_none()
        if row is None:
            row = ScoringConfigVersion(version=cfg["version"], description=cfg["description"], config=cfg, is_active=True)
            db.add(row)
        else:
            row.is_active = True
        db.commit()
    return row


def get_active_config(db: Session) -> dict[str, Any]:
    return get_active_config_row(db).config


def score_ipo(db: Session, ipo: IPOIssue, persist: bool = True) -> dict[str, Any]:
    """Run the quant engine; store a new score row whenever its inputs or configuration changed.

    Called when an IPO's data changes (ingestion, document processing, imports) and by the periodic refresh —
    list and dashboard requests read the stored rows instead (``cached_score_summaries``).
    """
    from app.services.completeness import refresh_completeness

    cfg = get_active_config(db)
    result = qe.compute(build_engine_inputs(db, ipo), cfg)
    if persist:
        refresh_completeness(db, ipo, result, cfg)
    result["calculated_at"] = None
    last = db.execute(select(ResearchScore).where(ResearchScore.ipo_id == ipo.id).order_by(ResearchScore.id.desc()).limit(1)).scalar_one_or_none()
    if persist and (last is None or last.input_fingerprint != result["input_fingerprint"]):
        comps = result["components"]
        last = ResearchScore(
            ipo_id=ipo.id, config_version=cfg["version"], status=result["status"], composite=result["composite"],
            profitability=comps["profitability"]["score"], growth=comps["growth"]["score"], financial_health=comps["financial_health"]["score"],
            cash_flow=comps["cash_flow"]["score"], valuation=comps["valuation"]["score"], risk=result["risk"]["score"],
            risk_level=result["risk"]["level"], classification=result["classification"], coverage=result["coverage"] or 0.0,
            input_fingerprint=result["input_fingerprint"], breakdown=result,
        )
        db.add(last)
    if persist:
        db.commit()
    if last is not None and last.input_fingerprint == result["input_fingerprint"]:
        result["calculated_at"] = last.calculated_at.isoformat()
    return result


def refresh_scores(db: Session, ipo_ids: set[int] | None = None) -> dict[str, int]:
    """Re-run the engine for the given IPOs (all when None). Rows are only added when inputs or configuration changed."""
    before = db.execute(select(func.count(ResearchScore.id))).scalar_one()
    q = select(IPOIssue).options(*IPO_LOAD_OPTIONS)
    if ipo_ids is not None:
        if not ipo_ids:
            return {"checked": 0, "new_scores": 0}
        q = q.where(IPOIssue.id.in_(ipo_ids))
    n = 0
    for ipo in db.execute(q).scalars():
        score_ipo(db, ipo, persist=True)
        n += 1
    return {"checked": n, "new_scores": db.execute(select(func.count(ResearchScore.id))).scalar_one() - before}


EMPTY_SUMMARY: dict[str, Any] = {k: None for k in ("status", "composite", "classification", "profitability", "growth", "financial_health",
                                                   "cash_flow", "valuation", "risk", "risk_level", "coverage", "basis", "latest_period", "pe",
                                                   "price_status", "config_version", "calculated_at")}


def cached_score_summaries(db: Session) -> dict[int, dict[str, Any]]:
    """Latest stored score per IPO in one query — what lists, the dashboard and comparisons read."""
    latest = select(func.max(ResearchScore.id)).group_by(ResearchScore.ipo_id)
    out: dict[int, dict[str, Any]] = {}
    for r in db.execute(select(ResearchScore).where(ResearchScore.id.in_(latest))).scalars():
        try:
            out[r.ipo_id] = {**score_summary(r.breakdown), "calculated_at": r.calculated_at.isoformat()}
        except (KeyError, TypeError):
            out[r.ipo_id] = {**EMPTY_SUMMARY, "status": "stale", "config_version": r.config_version}
    return out


def score_summary(result: dict[str, Any]) -> dict[str, Any]:
    comps = result["components"]
    return {
        "status": result["status"],
        "composite": result["composite"],
        "classification": result["classification"],
        "profitability": comps["profitability"]["score"],
        "growth": comps["growth"]["score"],
        "financial_health": comps["financial_health"]["score"],
        "cash_flow": comps["cash_flow"]["score"],
        "valuation": comps["valuation"]["score"],
        "risk": result["risk"]["score"],
        "risk_level": result["risk"]["level"],
        "coverage": result["coverage"],
        "basis": result["basis"],
        "latest_period": result["latest_period"],
        "pe": (result["metrics"].get("pe") or {}).get("value"),
        "price_status": result["price"].get("price_status"),
        "config_version": result["config_version"],
        "profile": (result.get("profile") or {}).get("key"),
        "governance_risk": ((result.get("risk") or {}).get("governance_disclosure") or {}).get("score"),
        "calculated_at": result.get("calculated_at"),
    }


def subscription_at(ipo: IPOIssue, ts) -> dict[str, float]:
    """Subscription by category using only snapshots taken at or before ``ts``."""
    snaps = [s for s in ipo.subscriptions if s.as_of <= ts]
    if not snaps:
        return {}
    last = max(s.as_of for s in snaps)
    return {s.category: s.times_subscribed for s in snaps if s.as_of == last}


def subscriptions_query(db: Session, ipo_id: int) -> list[SubscriptionSnapshot]:
    return list(db.execute(select(SubscriptionSnapshot).where(SubscriptionSnapshot.ipo_id == ipo_id)).scalars())
