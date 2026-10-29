"""Database-facing IPO helpers: status, serialisation, scoring inputs, persisted scores."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    FinancialStatement,
    IPOIssue,
    PeerSnapshot,
    ResearchScore,
    RiskDisclosure,
    ScoringConfigVersion,
    SourceRecord,
    SubscriptionSnapshot,
)
from app.services.financial_metrics import FIN_FIELDS, Period, period_ratios
from app.services.scoring_config import get_default_config, validate_config
from app.services.scoring_engine import (
    DisclosureInput,
    IssueInput,
    PeerInput,
    ScoringInputs,
    compute_scores,
)

STATUS_ORDER = ["open", "upcoming", "closed", "listed", "withdrawn"]


def effective_status(ipo: IPOIssue, today: date | None = None) -> str:
    """Status derived from dates so that stored records never go stale."""
    today = today or date.today()
    if ipo.status_override in ("withdrawn", "postponed"):
        return "withdrawn"
    if ipo.listing_date and ipo.listing_date <= today:
        return "listed"
    if ipo.open_date and today < ipo.open_date:
        return "upcoming"
    if ipo.open_date and ipo.close_date and ipo.open_date <= today <= ipo.close_date:
        return "open"
    if ipo.close_date and today > ipo.close_date:
        return "closed"
    return "upcoming" if ipo.open_date is None else "closed"


def issue_price(ipo: IPOIssue) -> float | None:
    return ipo.final_issue_price or ipo.price_band_high


def listing_return_pct(ipo: IPOIssue) -> float | None:
    p = issue_price(ipo)
    if ipo.listing_price is None or not p:
        return None
    return round((ipo.listing_price - p) / p * 100, 2)


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
    if not ipo.subscriptions:
        return None
    last_ts = max(s.as_of for s in ipo.subscriptions)
    cats = {s.category: s for s in ipo.subscriptions if s.as_of == last_ts}
    return {
        "as_of": last_ts.isoformat(),
        "categories": {k: v.times_subscribed for k, v in cats.items()},
        "data_status": sorted({v.data_status for v in cats.values()}),
    }


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
        "status": effective_status(ipo, today),
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
        "listing_return_pct": lr,
        "listing_data_status": ipo.listing_data_status if ipo.listing_price is not None else None,
        "subscription": latest_subscription(ipo),
        "data_mode": ipo.data_mode,
        "data_status": ipo.data_status,
        "last_updated": ipo.updated_at.isoformat() if ipo.updated_at else None,
        "source": source_brief(ipo.source_record),
    }


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
            "subscription_history": [
                {"as_of": s.as_of.isoformat(), "category": s.category, "times_subscribed": s.times_subscribed,
                 "data_status": s.data_status, "source_record_id": s.source_record_id}
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
                 "source": source_brief(p.source_record)}
                for p in ipo.peers
            ],
            "disclosures": [
                {"id": d.id, "category": d.category, "severity": d.severity, "status": d.status, "title": d.title,
                 "description": d.description, "amount_cr": d.amount_cr, "data_status": d.data_status,
                 "source": source_brief(d.source_record)}
                for d in ipo.disclosures
            ],
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


def to_period(s: FinancialStatement) -> Period:
    return Period(
        label=s.period_label,
        period_end=s.period_end,
        months=s.period_months,
        data_status=s.data_status,
        source_record_id=s.source_record_id,
        **{f: getattr(s, f) for f in FIN_FIELDS},
    )


def serialize_statements(stmts: list[FinancialStatement]) -> list[dict[str, Any]]:
    out = []
    for s in stmts:
        p = to_period(s)
        out.append(
            {
                "id": s.id,
                "period_label": s.period_label,
                "period_end": s.period_end.isoformat(),
                "period_months": s.period_months,
                "currency": s.currency,
                "unit": s.unit,
                **{f: getattr(s, f) for f in FIN_FIELDS},
                "derived": period_ratios(p),
                "data_status": s.data_status,
                "source": source_brief(s.source_record),
            }
        )
    return out


def build_scoring_inputs(db: Session, ipo: IPOIssue, as_of: date | None = None) -> ScoringInputs:
    c: Company = ipo.company
    issue = IssueInput(
        ipo_id=ipo.id,
        company_name=c.name,
        sector=c.sector,
        issue_type=ipo.issue_type,
        price_band_low=ipo.price_band_low,
        price_band_high=ipo.price_band_high,
        final_issue_price=ipo.final_issue_price,
        post_issue_shares=ipo.post_issue_shares,
        issue_size_cr=ipo.issue_size_cr,
        fresh_issue_cr=ipo.fresh_issue_cr,
        ofs_cr=ipo.ofs_cr,
        promoter_holding_post_pct=ipo.promoter_holding_post_pct,
        risk_disclosures_reviewed=ipo.risk_disclosures_reviewed,
        open_date=ipo.open_date,
        data_status=ipo.data_status,
        source_record_id=ipo.source_record_id,
        customer_concentration_pct=c.customer_concentration_pct,
        customer_concentration_status=c.data_status if c.customer_concentration_pct is not None else None,
    )
    periods = [to_period(s) for s in current_statements(db, c.id)]
    peers = [
        PeerInput(name=p.name, ticker=p.ticker, as_of=p.as_of, pe=p.pe, ev_ebitda=p.ev_ebitda, pb=p.pb, ps=p.ps,
                  data_status=p.data_status, source_record_id=p.source_record_id)
        for p in ipo.peers
    ]
    disclosures = [
        DisclosureInput(id=d.id, category=d.category, severity=d.severity, status=d.status, title=d.title,
                        data_status=d.data_status, source_record_id=d.source_record_id)
        for d in ipo.disclosures
    ]
    # Reference date: the issue opening date if it has passed (score as at the issue),
    # otherwise today (upcoming issues).
    ref = as_of or (ipo.open_date if ipo.open_date and ipo.open_date <= date.today() else date.today())
    return ScoringInputs(issue=issue, periods=periods, peers=peers, disclosures=disclosures, as_of=ref)


# ---------------------------------------------------------------------------
# Scoring configuration
# ---------------------------------------------------------------------------
def get_active_config_row(db: Session) -> ScoringConfigVersion:
    row = db.execute(select(ScoringConfigVersion).where(ScoringConfigVersion.is_active.is_(True))).scalar_one_or_none()
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
    cfg = get_active_config(db)
    inputs = build_scoring_inputs(db, ipo)
    result = compute_scores(inputs, cfg)
    if persist:
        last = db.execute(
            select(ResearchScore).where(ResearchScore.ipo_id == ipo.id).order_by(ResearchScore.id.desc()).limit(1)
        ).scalar_one_or_none()
        if last is None or last.input_fingerprint != result["input_fingerprint"]:
            db.add(
                ResearchScore(
                    ipo_id=ipo.id,
                    config_version=cfg["version"],
                    status=result["status"],
                    composite=result["composite"],
                    quality=result["quality"]["score"],
                    valuation=result["valuation"]["score"],
                    risk=result["risk"]["score"],
                    coverage=result["coverage"],
                    input_fingerprint=result["input_fingerprint"],
                    breakdown=result,
                )
            )
            db.commit()
    return result


def score_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result["status"],
        "composite": result["composite"],
        "quality": result["quality"]["score"],
        "valuation": result["valuation"]["score"],
        "risk": result["risk"]["score"],
        "risk_level": result["risk"]["level"],
        "coverage": result["coverage"],
        "input_completeness": result["evidence"]["input_completeness"],
        "valuation_multiple": result["valuation"].get("multiple_label"),
        "ipo_multiple": result["valuation"].get("ipo_multiple"),
        "config_version": result["config_version"],
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
