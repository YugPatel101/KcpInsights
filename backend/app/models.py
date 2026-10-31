"""Normalised relational schema for KcpInsights.

Conventions
-----------
* All timestamps are stored as naive UTC datetimes (``utcnow()``).
* Money amounts in financial tables are stored in **INR crore** after unit
  conversion. The raw value and unit as received are kept in ``SourceRecord.raw_payload``.
* Every sourced row carries a ``data_status`` (see ``DataStatus``) and, where
  applicable, a ``source_record_id`` pointing to its provenance.
"""
from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class DataStatus(enum.StrEnum):
    verified = "verified"  # checked against an official/primary source
    imported = "imported"  # user-supplied dataset with stated provenance
    estimated = "estimated"  # analyst estimate / derived assumption
    synthetic = "synthetic"  # demonstration fixture – never a real fact
    secondary_source = "secondary_source"  # non-authoritative public source (discovery / cross-check only)
    extracted = "extracted"  # read from an official document by the parser; no reconciliation check covers it
    requires_review = "requires_review"  # read from an official document but an accounting check failed
    unavailable = "unavailable"


class DataMode(enum.StrEnum):
    demo = "demo"  # Mode A – synthetic demonstration
    imported = "imported"  # Mode B – user imported research
    source = "source"  # Mode C – source-connected


DATA_STATUS_VALUES = [s.value for s in DataStatus]


# ---------------------------------------------------------------------------
# Users, sessions, auditing
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
class ImportedDataset(Base):
    __tablename__ = "imported_datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))  # financials_csv | bundle_json | demo_fixture
    status: Mapped[str] = mapped_column(String(32))  # validated | committed | rejected
    record_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("imported_datasets.id", ondelete="CASCADE"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SourceDocument(Base):
    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int | None] = mapped_column(ForeignKey("ipo_issues.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(32))  # drhp | rhp | prospectus | annual_report | disclosure | other
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)  # internal; never returned
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    data_status: Mapped[str] = mapped_column(String(16), default=DataStatus.imported.value)
    injection_flags: Mapped[int] = mapped_column(Integer, default=0)
    # --- automatic retrieval (official exchange archives) -------------------------------
    source_key: Mapped[str | None] = mapped_column(String(48), nullable=True)  # e.g. nse_ipo
    archive_url: Mapped[str | None] = mapped_column(String(1000), nullable=True, index=True)  # URL the file was found at
    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_etag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    http_last_modified: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    original_retained: Mapped[bool] = mapped_column(Boolean, default=True)  # False once pruned to save disk space
    # pending | extracted | partial | failed | not_found | skipped
    extraction_status: Mapped[str] = mapped_column(String(24), default="pending")
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(16), nullable=True)  # text | ocr | text+ocr
    # retry with exponential backoff; after the configured number of attempts the document is a dead letter
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentExtraction(Base):
    """One run of the financial-statement extractor over one document (kept as an audit trail)."""

    __tablename__ = "document_extractions"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), index=True)
    parser_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))  # extracted | partial | failed | not_found
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
    statements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # page, kind, basis, unit, periods
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # accounting reconciliation results
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    injection_suspected: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[SourceDocument] = relationship(back_populates="chunks")


class SourceRecord(Base):
    """Provenance for one or more stored values."""

    __tablename__ = "source_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32))  # official_url | document | manual | import | synthetic_fixture
    title: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True)
    document_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("imported_datasets.id", ondelete="SET NULL"), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reporting_period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data_status: Mapped[str] = mapped_column(String(16))
    transformation: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Companies and IPOs
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    sector: Mapped[str] = mapped_column(String(80), index=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    revenue_sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Share of revenue from top-N customers (percent) – only when disclosed.
    customer_concentration_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    customer_concentration_basis: Mapped[str | None] = mapped_column(String(80), nullable=True)
    customer_concentration_source_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)
    # analysis profile chosen by the industry classifier (lender | insurer | technology | manufacturing | ... | general)
    industry_profile: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # how the sector was determined: {method, status, evidence: [{phrase, count, pages}], document_id, classified_at}
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    data_status: Mapped[str] = mapped_column(String(16), default=DataStatus.imported.value)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    ipos: Mapped[list[IPOIssue]] = relationship(back_populates="company")
    statements: Mapped[list[FinancialStatement]] = relationship(back_populates="company")


class IPOIssue(Base):
    __tablename__ = "ipo_issues"
    __table_args__ = (Index("ix_ipo_dates", "open_date", "close_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exchange: Mapped[str] = mapped_column(String(32))  # "NSE", "BSE", "NSE,BSE", "NSE Emerge", "BSE SME"
    issue_type: Mapped[str] = mapped_column(String(16))  # mainboard | sme
    status_override: Mapped[str | None] = mapped_column(String(16), nullable=True)  # withdrawn | postponed
    open_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    listing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    price_band_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_band_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_issue_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_size_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    fresh_issue_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ofs_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    pre_issue_shares: Mapped[float | None] = mapped_column(Float, nullable=True)  # absolute count
    post_issue_shares: Mapped[float | None] = mapped_column(Float, nullable=True)  # absolute count, diluted
    promoter_holding_pre_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    promoter_holding_post_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    use_of_proceeds: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    listing_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # listing-day open
    listing_data_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # --- live-ingestion fields (Mode C) -------------------------------------------------
    nse_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # "actual" once an exchange confirms the listing; "expected" for a computed/announced date
    listing_date_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    listing_price_basis: Mapped[str | None] = mapped_column(String(32), nullable=True)  # listing_day_open
    listing_close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    listing_high_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # listing-day high (bhavcopy HghPric)
    listing_low_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # listing-day low (bhavcopy LwPric)
    allotment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    refund_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    demat_credit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shares_offered: Mapped[float | None] = mapped_column(Float, nullable=True)
    registrar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lead_managers: Mapped[str | None] = mapped_column(Text, nullable=True)
    offer_document_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    basis_of_price_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    issue_size_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    risk_disclosures_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    # facts read from the offer document: {key: {value, page, text, basis, document_id, read_at}}
    document_facts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # cached result of services.completeness (recomputed whenever the IPO is re-scored)
    completeness_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    completeness_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    data_mode: Mapped[str] = mapped_column(String(16), default=DataMode.imported.value, index=True)
    data_status: Mapped[str] = mapped_column(String(16), default=DataStatus.imported.value)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)
    research_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    company: Mapped[Company] = relationship(back_populates="ipos")
    source_record: Mapped[SourceRecord | None] = relationship()
    peers: Mapped[list[PeerSnapshot]] = relationship(back_populates="ipo", cascade="all, delete-orphan")
    disclosures: Mapped[list[RiskDisclosure]] = relationship(back_populates="ipo", cascade="all, delete-orphan")
    subscriptions: Mapped[list[SubscriptionSnapshot]] = relationship(back_populates="ipo", cascade="all, delete-orphan")
    gmp_observations: Mapped[list[GreyMarketObservation]] = relationship(back_populates="ipo", cascade="all, delete-orphan")
    events: Mapped[list[IssueEvent]] = relationship(back_populates="ipo", cascade="all, delete-orphan")


class IssueEvent(Base):
    __tablename__ = "issue_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    event_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)

    ipo: Mapped[IPOIssue] = relationship(back_populates="events")


class SubscriptionSnapshot(Base):
    __tablename__ = "subscription_snapshots"
    __table_args__ = (UniqueConstraint("ipo_id", "as_of", "category", "basis", name="uq_subscription_basis"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime)
    category: Mapped[str] = mapped_column(String(16))  # qib | nii | retail | employee | total
    times_subscribed: Mapped[float] = mapped_column(Float)
    # consolidated = all exchanges (official final basis); nse_only = NSE bidding platform only
    basis: Mapped[str] = mapped_column(String(16), default="consolidated", server_default="consolidated")
    shares_offered: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_status: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)

    ipo: Mapped[IPOIssue] = relationship(back_populates="subscriptions")


class GreyMarketObservation(Base):
    """Grey-market premium. Unofficial, unregulated and frequently unreliable."""

    __tablename__ = "grey_market_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    premium_inr: Mapped[float] = mapped_column(Float)
    data_status: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)

    ipo: Mapped[IPOIssue] = relationship(back_populates="gmp_observations")


class FinancialStatement(Base):
    """One reporting period of (restated) financials for a company.

    Values are in INR crore. Rows are versioned: an import that changes values for a
    period adds a new row and marks the previous one ``is_current = False`` — except
    that a verified row is never superseded by a non-verified one.
    """

    __tablename__ = "financial_statements"
    __table_args__ = (Index("ix_fin_company_period", "company_id", "period_end", "is_current"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    period_label: Mapped[str] = mapped_column(String(32))
    period_end: Mapped[date] = mapped_column(Date)
    period_months: Mapped[int] = mapped_column(Integer, default=12)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    unit: Mapped[str] = mapped_column(String(16), default="crore")
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebitda: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebit: Mapped[float | None] = mapped_column(Float, nullable=True)
    pat: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    capex: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_expense: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_liabilities: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_and_equivalents: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_liabilities: Mapped[float | None] = mapped_column(Float, nullable=True)
    # --- detailed line items (prospectus extraction; INR crore unless per-share) --------
    other_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_of_materials: Mapped[float | None] = mapped_column(Float, nullable=True)
    employee_expenses: Mapped[float | None] = mapped_column(Float, nullable=True)
    other_expenses: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_expenses: Mapped[float | None] = mapped_column(Float, nullable=True)
    depreciation: Mapped[float | None] = mapped_column(Float, nullable=True)
    pbt: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_expense: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_basic: Mapped[float | None] = mapped_column(Float, nullable=True)  # INR per share
    eps_diluted: Mapped[float | None] = mapped_column(Float, nullable=True)  # INR per share
    non_current_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    non_current_liabilities: Mapped[float | None] = mapped_column(Float, nullable=True)
    share_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
    other_equity: Mapped[float | None] = mapped_column(Float, nullable=True)  # reserves and surplus
    borrowings_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    borrowings_non_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    lease_liabilities: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_receivables: Mapped[float | None] = mapped_column(Float, nullable=True)
    inventory: Mapped[float | None] = mapped_column(Float, nullable=True)
    investing_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    financing_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    basis: Mapped[str] = mapped_column(String(16), default="unknown")  # consolidated | standalone | unknown
    document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True, index=True)
    validation_status: Mapped[str] = mapped_column(String(16), default="not_checked")  # passed | failed | partial | not_checked
    validation: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    data_status: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("financial_statements.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="statements")
    source_record: Mapped[SourceRecord | None] = relationship()
    line_items: Mapped[list[FinancialLineItem]] = relationship(back_populates="statement", cascade="all, delete-orphan")


class FinancialLineItem(Base):
    """Provenance of one extracted figure: where it was read, as printed, and as normalised."""

    __tablename__ = "financial_line_items"
    __table_args__ = (Index("ix_line_item_statement_field", "statement_id", "field"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("financial_statements.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(48))
    raw_label: Mapped[str] = mapped_column(String(300))
    raw_text: Mapped[str] = mapped_column(String(64))  # the figure exactly as printed, e.g. "(218.38)"
    unit: Mapped[str] = mapped_column(String(24))  # unit stated on the page, e.g. million
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # normalised: INR crore (per-share items: INR)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24))  # extracted | derived
    validation_status: Mapped[str] = mapped_column(String(16), default="not_checked")

    statement: Mapped[FinancialStatement] = relationship(back_populates="line_items")


class PeerSnapshot(Base):
    """A listed comparable company's multiples as of a date, for one IPO's peer set."""

    __tablename__ = "peer_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sector: Mapped[str] = mapped_column(String(80))
    as_of: Mapped[date] = mapped_column(Date)
    market_cap_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_ebitda: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)
    ps: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_status: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)
    # --- from the prospectus "comparison with listed industry peers" table ---------------
    basis: Mapped[str | None] = mapped_column(String(16), nullable=True)  # standalone | consolidated
    period_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    face_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_basic: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_diluted: Mapped[float | None] = mapped_column(Float, nullable=True)
    nav_per_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    ronw_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # latest official closing price (NSE bhavcopy), matched by name to the NSE equity list
    nse_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latest_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_price_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    ipo: Mapped[IPOIssue] = relationship(back_populates="peers")
    source_record: Mapped[SourceRecord | None] = relationship()


class RiskDisclosure(Base):
    """A risk item. ``status`` separates confirmed disclosures from unresolved concerns."""

    __tablename__ = "risk_disclosures"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(48))  # litigation | regulatory | related_party | contingent_liability | concentration | other
    severity: Mapped[str] = mapped_column(String(8))  # low | medium | high
    status: Mapped[str] = mapped_column(String(24))  # confirmed_disclosure | unresolved_concern
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    amount_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_status: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)

    ipo: Mapped[IPOIssue] = relationship(back_populates="disclosures")
    source_record: Mapped[SourceRecord | None] = relationship()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
class ScoringConfigVersion(Base):
    __tablename__ = "scoring_config_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(32), unique=True)
    description: Mapped[str] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchScore(Base):
    __tablename__ = "research_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"), index=True)
    config_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))  # complete | incomplete
    composite: Mapped[float | None] = mapped_column(Float, nullable=True)  # overall fundamental score Q
    profitability: Mapped[float | None] = mapped_column(Float, nullable=True)
    growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    financial_health: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    valuation: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk: Mapped[float | None] = mapped_column(Float, nullable=True)  # higher = more risk
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coverage: Mapped[float] = mapped_column(Float)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# User workspace
# ---------------------------------------------------------------------------
class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "ipo_id", name="uq_watchlist"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchReport(Base):
    __tablename__ = "research_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ipo_id: Mapped[int | None] = mapped_column(ForeignKey("ipo_issues.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    generator: Mapped[str] = mapped_column(String(80))
    config_version: Mapped[str] = mapped_column(String(32))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Live ingestion: sources, jobs, locks, field-level provenance and change history
# ---------------------------------------------------------------------------
class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(500))
    authority: Mapped[str] = mapped_column(String(24))  # official | secondary | manual
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    access_mode: Mapped[str] = mapped_column(String(24))  # automatic | manual_only
    health_status: Mapped[str] = mapped_column(String(24), default="unknown")  # healthy | degraded | down | blocked | unknown
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    requests_made: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(48), index=True)
    trigger: Mapped[str] = mapped_column(String(24))  # schedule | admin | startup | cli
    status: Mapped[str] = mapped_column(String(16))  # running | success | partial | failed | skipped
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    records_discovered: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    fields_changed: Mapped[int] = mapped_column(Integer, default=0)
    requests_made: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class JobLock(Base):
    """Cross-process mutex so the same job never runs twice concurrently."""

    __tablename__ = "job_locks"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class FieldObservation(Base):
    """One observed value of one IPO field from one source at one time (history is kept)."""

    __tablename__ = "field_observations"
    __table_args__ = (Index("ix_obs_ipo_field", "ipo_id", "field", "observed_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(48))
    value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded
    source_key: Mapped[str] = mapped_column(String(48))
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)  # first seen
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)  # last time the source confirmed it
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    data_status: Mapped[str] = mapped_column(String(24))
    basis: Mapped[str | None] = mapped_column(String(200), nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=True)  # false when a higher-authority value was kept
    conflict: Mapped[bool] = mapped_column(Boolean, default=False)


class FieldChange(Base):
    """Audit trail of changes to important IPO fields (dates, price band, listing)."""

    __tablename__ = "field_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo_issues.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(48))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_key: Mapped[str] = mapped_column(String(48))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
