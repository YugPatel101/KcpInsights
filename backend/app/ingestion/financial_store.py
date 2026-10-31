"""Persist what the document parsers extracted: statements, line-item provenance, peers, facts.

* Idempotent: re-processing the same document with the same parser changes nothing.
* History is kept: a changed figure for a period adds a new statement row and marks the previous
  one superseded (``is_current = False``); nothing is deleted.
* Status of each period: accounting checks passed → ``verified``; no check applicable →
  ``extracted``; a check failed → ``requires_review`` (stored for inspection, never scored).
  A verified period is never superseded by an unverified one.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.financials.disclosures import Disclosure, PeerTable
from app.financials.industry import Classification
from app.financials.statement_parser import ExtractionResult, PeriodStatement
from app.ingestion.ipo_data_service import UpsertStats, set_field
from app.models import FinancialLineItem, FinancialStatement, IPOIssue, PeerSnapshot, SourceDocument, SourceRecord, utcnow

# FinancialStatement column <- extracted/derived field
STATEMENT_FIELDS = {
    "revenue": "revenue", "other_income": "other_income", "total_income": "total_income", "cost_of_materials": "cost_of_materials",
    "employee_expenses": "employee_expenses", "other_expenses": "other_expenses", "total_expenses": "total_expenses",
    "depreciation": "depreciation", "pbt": "pbt", "tax_expense": "tax_expense", "pat": "pat", "eps_basic": "eps_basic",
    "eps_diluted": "eps_diluted", "ebit": "ebit", "ebitda": "ebitda", "interest_expense": "finance_costs",
    "total_assets": "total_assets", "non_current_assets": "non_current_assets", "current_assets": "current_assets",
    "total_equity": "total_equity", "share_capital": "share_capital", "other_equity": "other_equity",
    "non_current_liabilities": "non_current_liabilities", "current_liabilities": "current_liabilities",
    "total_liabilities": "total_liabilities", "borrowings_current": "borrowings_current", "borrowings_non_current": "borrowings_non_current",
    "total_debt": "total_debt", "lease_liabilities": "lease_liabilities", "cash_and_equivalents": "cash_and_equivalents",
    "trade_receivables": "trade_receivables", "inventory": "inventory", "operating_cash_flow": "operating_cash_flow",
    "investing_cash_flow": "investing_cash_flow", "financing_cash_flow": "financing_cash_flow", "capex": "capex",
}
STATUS_FOR_VALIDATION = {"passed": "verified", "partial": "extracted", "not_checked": "extracted", "failed": "requires_review"}


@dataclass
class StoreStats:
    statements_created: int = 0
    statements_unchanged: int = 0
    statements_superseded: int = 0
    statements_kept_verified: int = 0
    statements_retired: int = 0
    line_items: int = 0
    peers: int = 0
    facts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _values(ps: PeriodStatement) -> dict[str, float | None]:
    return {col: ps.get(src) for col, src in STATEMENT_FIELDS.items()}


def _fingerprint(values: dict[str, float | None], basis: str, months: int) -> str:
    norm = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in sorted(values.items())}
    return hashlib.sha256(json.dumps([norm, basis, months], sort_keys=True).encode()).hexdigest()


def _current(db: Session, company_id: int, ps: PeriodStatement) -> FinancialStatement | None:
    return db.execute(select(FinancialStatement).where(
        FinancialStatement.company_id == company_id, FinancialStatement.period_end == ps.end, FinancialStatement.basis == ps.basis,
        FinancialStatement.period_months == ps.months, FinancialStatement.is_current.is_(True)).limit(1)).scalar_one_or_none()


def store_statements(db: Session, ipo: IPOIssue, doc: SourceDocument, result: ExtractionResult, stats: StoreStats,
                     *, ocr_pages: set[int] | None = None) -> None:
    # A re-read of the same document replaces its earlier reading entirely (an older parser may have mislabelled
    # periods). The rule that a verified period is never replaced by an unverified one applies only across sources.
    new_keys = {(ps.basis, ps.end, ps.months) for ps in result.periods if any(v is not None for v in _values(ps).values())}
    for old in db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.document_id == doc.id,
                                                           FinancialStatement.is_current.is_(True))).scalars():
        if (old.basis, old.period_end, old.period_months) not in new_keys:
            old.is_current = False
            stats.statements_retired += 1
    db.flush()
    for ps in result.periods:
        values = _values(ps)
        if not any(v is not None for v in values.values()):
            continue
        status = STATUS_FOR_VALIDATION[ps.validation_status]
        via_ocr = bool(ocr_pages) and any(f.page in ocr_pages for f in ps.figures.values())  # type: ignore[operator]
        if via_ocr and status == "verified":
            status = "extracted"  # OCR can misread digits outside the checked totals: shown, not scored
        prev = _current(db, ipo.company_id, ps)
        if prev is not None:
            prev_vals = {col: getattr(prev, col) for col in STATEMENT_FIELDS}
            if _fingerprint(prev_vals, prev.basis, prev.period_months) == _fingerprint(values, ps.basis, ps.months) and prev.data_status == status:
                stats.statements_unchanged += 1
                continue
            if prev.data_status == "verified" and status != "verified" and prev.document_id != doc.id:
                stats.statements_kept_verified += 1
                continue
        src = SourceRecord(source_type="document", title=f"{doc.title} — {ps.label} ({ps.basis})"[:300], source_url=doc.archive_url or doc.source_url,
                           document_id=doc.id, data_status=status, retrieved_at=doc.retrieved_at, reporting_period=ps.label,
                           currency="INR", unit="crore",
                           notes=f"Restated financial statements, extracted by parser v{doc.parser_version}"
                                 + (" from OCR'd (scanned) pages" if via_ocr else "") + f"; checks: {ps.validation_status}")
        db.add(src)
        db.flush()
        row = FinancialStatement(company_id=ipo.company_id, period_label=ps.label, period_end=ps.end, period_months=ps.months, currency="INR",
                                 unit="crore", basis=ps.basis, document_id=doc.id, validation_status=ps.validation_status,
                                 validation=ps.checks, data_status=status, source_record_id=src.id, is_current=True,
                                 supersedes_id=prev.id if prev else None, **values)
        if prev is not None:
            prev.is_current = False
            stats.statements_superseded += 1
        db.add(row)
        db.flush()
        for fld, fig in ps.figures.items():
            col = next((c for c, s in STATEMENT_FIELDS.items() if s == fld), fld)
            db.add(FinancialLineItem(statement_id=row.id, field=col, raw_label=fig.raw_label[:300], raw_text=fig.raw_text[:64], unit=fig.unit,
                                     value=fig.value, page=fig.page, document_id=doc.id, status="extracted", validation_status=ps.validation_status))
            stats.line_items += 1
        for fld, (val, formula) in ps.derived.items():
            col = next((c for c, s in STATEMENT_FIELDS.items() if s == fld), fld)
            db.add(FinancialLineItem(statement_id=row.id, field=col, raw_label=formula[:300], raw_text="", unit="INR crore", value=val,
                                     page=None, document_id=doc.id, status="derived", validation_status=ps.validation_status))
            stats.line_items += 1
        stats.statements_created += 1


def store_peers(db: Session, ipo: IPOIssue, doc: SourceDocument, table: PeerTable | None, stats: StoreStats) -> None:
    if table is None:
        return
    for old in db.execute(select(PeerSnapshot).where(PeerSnapshot.ipo_id == ipo.id, PeerSnapshot.document_id.is_not(None))).scalars():
        db.delete(old)  # document-sourced peers are replaced by the latest document's table
    as_of = table.price_date or (doc.published_date or doc.retrieved_at.date())
    for r in table.rows:
        if r.is_company:
            continue
        ok = table.reliable and (r.check_note is None or r.check_note.startswith("P/E consistent"))
        pb = round(r.closing_price / r.nav_per_share, 4) if r.closing_price and r.nav_per_share and r.nav_per_share > 0 else None
        db.add(PeerSnapshot(ipo_id=ipo.id, name=r.name, ticker=None, sector=ipo.company.sector, as_of=as_of, market_cap_cr=None, pe=r.pe,
                            ev_ebitda=None, pb=pb, ps=None, revenue_cr=r.revenue_cr,
                            selection_reason="Listed industry peer named by the company in its offer document (Basis for Issue Price)",
                            data_status="verified" if ok else "requires_review", basis=table.basis, period_label=table.period_label,
                            face_value=r.face_value, closing_price=r.closing_price, eps_basic=r.eps_basic, eps_diluted=r.eps_diluted,
                            nav_per_share=r.nav_per_share, ronw_pct=r.ronw_pct, document_id=doc.id, page=table.page, check_note=r.check_note))
        stats.peers += 1


def store_facts(db: Session, ipo: IPOIssue, doc: SourceDocument, facts: dict[str, Disclosure], stats: StoreStats) -> None:
    out = dict(ipo.document_facts or {})
    for key, d in facts.items():
        out[key] = {"value": d.value, "page": d.page, "text": d.text[:400], "basis": d.basis, "document_id": doc.id, "read_at": utcnow().isoformat()}
        if key == "business_overview":
            out[key]["text"] = d.text[:900]
        stats.facts.append(key)
    ipo.document_facts = out
    url = doc.archive_url or doc.source_url
    st = UpsertStats()
    if "pre_issue_shares" in facts:
        d = facts["pre_issue_shares"]
        set_field(db, ipo, "pre_issue_shares", float(d.value), source_key=doc.source_key or "nse_rhp", source_url=url, status="verified",
                  basis=f"Equity shares outstanding before the issue, offer document p{d.page}", stats=st)
    if "customer_concentration_pct" in facts:
        d = facts["customer_concentration_pct"]
        ipo.company.customer_concentration_pct = float(d.value)
        ipo.company.customer_concentration_basis = (d.basis or "top customers")[:80]
    update_post_issue_shares(db, ipo, url)


def store_classification(db: Session, ipo: IPOIssue, doc: SourceDocument, c: Classification, kpis: dict[str, dict[str, Any]],
                         stats: StoreStats) -> None:
    """Sector and analysis profile from the offer document.

    The sector name is set only when none is on record (NSE's own industry label, a user import or the demo fixture
    is never replaced); the analysis profile always follows the document, since it decides which ratios apply.
    """
    company = ipo.company
    if company.data_status == "synthetic":
        return
    auto = company.sector == "Unclassified" or (company.classification or {}).get("method", "").startswith("weighted")
    company.classification = {**c.as_dict(), "document_id": doc.id, "classified_at": utcnow().isoformat(),
                              "sector_source": "offer document" if auto else "NSE issue data (kept)"}
    if c.status == "extracted":
        company.industry_profile = c.profile
        if auto:
            company.sector, company.industry = c.sector, c.sector
        stats.facts.append("industry")
    elif company.industry_profile is None:
        company.industry_profile = "general"
    if kpis:
        facts = dict(ipo.document_facts or {})
        facts["lender_kpis"] = {"value": kpis, "page": min(k["page"] for k in kpis.values()), "text": "", "basis": "KPI table, as printed",
                                "document_id": doc.id, "read_at": utcnow().isoformat()}
        ipo.document_facts = facts
        stats.facts.append("lender_kpis")


def update_post_issue_shares(db: Session, ipo: IPOIssue, url: str | None) -> None:
    """Post-issue shares = pre-issue shares + fresh-issue shares. Estimated while only the price band is known."""
    if ipo.pre_issue_shares is None or ipo.fresh_issue_cr is None:
        return
    price = ipo.final_issue_price or ipo.price_band_high
    if not price:
        return
    fresh = ipo.fresh_issue_cr * 1e7 / price
    status = "verified" if ipo.final_issue_price else "estimated"
    basis = (f"pre-issue shares + fresh issue ₹{ipo.fresh_issue_cr:g} cr ÷ "
             + (f"final issue price ₹{price:g}" if ipo.final_issue_price else f"upper end of price band ₹{price:g}"))
    set_field(db, ipo, "post_issue_shares", round(ipo.pre_issue_shares + fresh), source_key="nse_rhp:derived", source_url=url,
              status=status, basis=basis, stats=UpsertStats())
