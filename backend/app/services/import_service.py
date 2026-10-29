"""Validated import pipeline for research bundles (JSON) and financial statements (CSV).

Every import is validated first and produces a report of blocking errors and warnings
(missing fields, invalid dates, unit problems, duplicates, accounting sanity checks).
Committing writes rows with provenance (``SourceRecord`` + ``ImportedDataset``), keeps
the raw values, and never overwrites a verified financial period with unverified data.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    DataMode,
    FinancialStatement,
    GreyMarketObservation,
    ImportedDataset,
    IngestionLog,
    IPOIssue,
    IssueEvent,
    PeerSnapshot,
    RiskDisclosure,
    SourceRecord,
    SubscriptionSnapshot,
    utcnow,
)
from app.services.financial_metrics import FIN_FIELDS, UNIT_TO_CRORE, UnitError, to_crore

USER_STATUSES = {"verified", "imported", "estimated"}
MAX_ROWS = 5000


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceIn(_Strict):
    key: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    source_type: Literal["official_url", "document", "manual", "import", "synthetic_fixture"] = "manual"
    url: str | None = Field(default=None, max_length=1000)
    publication_date: date | None = None
    data_status: Literal["verified", "imported", "estimated", "synthetic"] = "imported"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("url must start with http:// or https://")
        return v


class CompanyIn(_Strict):
    name: str = Field(min_length=2, max_length=200)
    sector: str = Field(min_length=2, max_length=80)
    industry: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    business_model: str | None = Field(default=None, max_length=5000)
    revenue_sources: list[dict[str, Any]] | None = None
    website: str | None = Field(default=None, max_length=300)
    customer_concentration_pct: float | None = Field(default=None, ge=0, le=100)
    customer_concentration_basis: str | None = Field(default=None, max_length=80)


class IssueIn(_Strict):
    symbol: str | None = Field(default=None, max_length=32)
    exchange: str = Field(min_length=2, max_length=32)
    issue_type: Literal["mainboard", "sme"]
    open_date: date | None = None
    close_date: date | None = None
    listing_date: date | None = None
    price_band_low: float | None = Field(default=None, gt=0)
    price_band_high: float | None = Field(default=None, gt=0)
    final_issue_price: float | None = Field(default=None, gt=0)
    face_value: float | None = Field(default=None, gt=0)
    lot_size: int | None = Field(default=None, gt=0)
    issue_size_cr: float | None = Field(default=None, gt=0)
    fresh_issue_cr: float | None = Field(default=None, ge=0)
    ofs_cr: float | None = Field(default=None, ge=0)
    pre_issue_shares: float | None = Field(default=None, gt=0)
    post_issue_shares: float | None = Field(default=None, gt=0)
    promoter_holding_pre_pct: float | None = Field(default=None, ge=0, le=100)
    promoter_holding_post_pct: float | None = Field(default=None, ge=0, le=100)
    use_of_proceeds: list[dict[str, Any]] | None = None
    listing_price: float | None = Field(default=None, gt=0)
    risk_disclosures_reviewed: bool = False
    status_override: Literal["withdrawn", "postponed"] | None = None
    research_notes: str | None = Field(default=None, max_length=5000)
    source_key: str

    @model_validator(mode="after")
    def _dates(self) -> IssueIn:
        if self.open_date and self.close_date and self.close_date < self.open_date:
            raise ValueError("close_date is before open_date")
        if self.close_date and self.listing_date and self.listing_date < self.close_date:
            raise ValueError("listing_date is before close_date")
        if self.price_band_low and self.price_band_high and self.price_band_low > self.price_band_high:
            raise ValueError("price_band_low exceeds price_band_high")
        if self.listing_price and not self.listing_date:
            raise ValueError("listing_price requires listing_date")
        return self


class FinancialIn(_Strict):
    period_label: str = Field(min_length=2, max_length=32)
    period_end: date
    period_months: int = Field(default=12, ge=1, le=24)
    currency: Literal["INR"] = "INR"
    revenue: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    pat: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = Field(default=None, description="positive number = outflow")
    interest_expense: float | None = Field(default=None, ge=0)
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_debt: float | None = Field(default=None, ge=0)
    cash_and_equivalents: float | None = Field(default=None, ge=0)
    total_equity: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    source_key: str


class PeerIn(_Strict):
    name: str = Field(min_length=2, max_length=200)
    ticker: str | None = Field(default=None, max_length=32)
    sector: str = Field(min_length=2, max_length=80)
    as_of: date
    market_cap_cr: float | None = Field(default=None, gt=0)
    pe: float | None = None
    ev_ebitda: float | None = None
    pb: float | None = None
    ps: float | None = None
    revenue_cr: float | None = None
    selection_reason: str | None = Field(default=None, max_length=1000)
    source_key: str


class DisclosureIn(_Strict):
    category: Literal["litigation", "regulatory", "related_party", "contingent_liability", "concentration", "promoter", "other"]
    severity: Literal["low", "medium", "high"]
    status: Literal["confirmed_disclosure", "unresolved_concern"]
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3, max_length=5000)
    amount_cr: float | None = None
    page: int | None = Field(default=None, ge=1)
    source_key: str


class SubscriptionIn(_Strict):
    as_of: datetime
    category: Literal["qib", "nii", "retail", "employee", "total"]
    times_subscribed: float = Field(ge=0)
    source_key: str


class GreyMarketIn(_Strict):
    observed_at: datetime
    premium_inr: float
    source_key: str


class EventIn(_Strict):
    event_type: str = Field(max_length=48)
    event_date: date
    description: str = Field(max_length=2000)
    source_key: str | None = None


class IPOBundleItem(_Strict):
    company: CompanyIn
    issue: IssueIn
    unit: str = "crore"
    financials: list[FinancialIn] = Field(default_factory=list, max_length=40)
    peers: list[PeerIn] = Field(default_factory=list, max_length=40)
    disclosures: list[DisclosureIn] = Field(default_factory=list, max_length=200)
    subscriptions: list[SubscriptionIn] = Field(default_factory=list, max_length=200)
    grey_market: list[GreyMarketIn] = Field(default_factory=list, max_length=200)
    events: list[EventIn] = Field(default_factory=list, max_length=100)


class ResearchBundle(_Strict):
    dataset_label: str = Field(default="research bundle", max_length=200)
    sources: list[SourceIn] = Field(min_length=1, max_length=200)
    ipos: list[IPOBundleItem] = Field(min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.info: list[dict[str, Any]] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append({"where": where, "message": msg})

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append({"where": where, "message": msg})

    def note(self, where: str, msg: str) -> None:
        self.info.append({"where": where, "message": msg})

    def as_dict(self) -> dict[str, Any]:
        return {"ok": not self.errors, "errors": self.errors, "warnings": self.warnings, "info": self.info}


KEY_FIELDS = ("revenue", "ebitda", "pat", "operating_cash_flow", "total_equity", "total_debt", "cash_and_equivalents")


def _sanity_check_period(where: str, f: FinancialIn | dict[str, Any], rep: Report, today: date) -> None:
    def g(k: str) -> Any:
        return f.get(k) if isinstance(f, dict) else getattr(f, k)

    if g("period_end") and g("period_end") > today:
        rep.error(where, f"period_end {g('period_end')} is in the future")
    missing = [k for k in KEY_FIELDS if g(k) is None]
    if missing:
        rep.warn(where, f"missing fields: {', '.join(missing)} (dependent metrics will be unavailable)")
    rev = g("revenue")
    if rev is not None and rev < 0:
        rep.error(where, "revenue is negative")
    if rev is not None and rev > 0:
        if g("ebitda") is not None and g("ebitda") > rev:
            rep.warn(where, "EBITDA exceeds revenue — check units or definitions")
        if g("pat") is not None and g("pat") > rev:
            rep.warn(where, "PAT exceeds revenue — check for exceptional items")
    if g("ebit") is not None and g("ebitda") is not None and g("ebit") > g("ebitda") + 1e-9:
        rep.warn(where, "EBIT exceeds EBITDA (implies negative D&A)")
    ta, tl, te = g("total_assets"), g("total_liabilities"), g("total_equity")
    if None not in (ta, tl, te) and ta and abs(ta - (tl + te)) / abs(ta) > 0.02:
        rep.warn(where, "assets ≠ liabilities + equity (difference > 2 %)")


def validate_bundle(payload: dict[str, Any], *, allow_synthetic: bool = False, today: date | None = None) -> tuple[ResearchBundle | None, Report]:
    rep = Report()
    today = today or date.today()
    try:
        bundle = ResearchBundle.model_validate(payload)
    except ValidationError as exc:
        for e in exc.errors()[:200]:
            rep.error(".".join(str(x) for x in e["loc"]), e["msg"])
        return None, rep

    keys = [s.key for s in bundle.sources]
    if len(keys) != len(set(keys)):
        rep.error("sources", "duplicate source keys")
    src = {s.key: s for s in bundle.sources}
    for s in bundle.sources:
        if s.data_status == "synthetic" and not allow_synthetic:
            rep.error(f"sources.{s.key}", "synthetic data can only be loaded by the demo seed command")
        if s.source_type == "synthetic_fixture" and s.data_status != "synthetic":
            rep.error(f"sources.{s.key}", "synthetic_fixture sources must have data_status 'synthetic'")
        if not s.url and s.source_type in ("official_url",):
            rep.warn(f"sources.{s.key}", "official_url source without a URL")

    seen_companies: set[str] = set()
    for i, item in enumerate(bundle.ipos):
        w = f"ipos[{i}] {item.company.name}"
        cname = item.company.name.lower()
        if cname in seen_companies:
            rep.error(w, "company appears twice in this bundle")
        seen_companies.add(cname)
        try:
            factor = UNIT_TO_CRORE[item.unit.strip().lower()]
        except KeyError:
            rep.error(w, f"unsupported unit {item.unit!r}; supported: {sorted(UNIT_TO_CRORE)}")
            factor = None
        if factor is not None and factor != 1.0:
            rep.note(w, f"financial amounts will be converted from {item.unit} to crore (×{factor})")

        refs: list[str] = [item.issue.source_key]
        for group in (item.financials, item.peers, item.disclosures, item.subscriptions, item.grey_market):
            refs += [x.source_key for x in group]
        refs += [e.source_key for e in item.events if e.source_key]
        for r in refs:
            if r not in src:
                rep.error(w, f"unknown source_key {r!r}")
        iss = item.issue
        if iss.issue_size_cr and iss.fresh_issue_cr is not None and iss.ofs_cr is not None:
            if abs(iss.fresh_issue_cr + iss.ofs_cr - iss.issue_size_cr) / iss.issue_size_cr > 0.01:
                rep.warn(w, "fresh issue + OFS differs from issue size by more than 1 %")
        if iss.pre_issue_shares and iss.post_issue_shares and iss.post_issue_shares < iss.pre_issue_shares:
            rep.error(w, "post_issue_shares is below pre_issue_shares")
        if iss.price_band_high is None and iss.final_issue_price is None:
            rep.warn(w, "no price band or issue price: valuation will be unavailable")
        if iss.post_issue_shares is None:
            rep.warn(w, "post_issue_shares missing: market capitalisation cannot be derived")
        if iss.listing_price and iss.listing_date and iss.listing_date > today:
            rep.error(w, "listing price supplied for a future listing date")
        periods = [(f.period_end, f.period_months) for f in item.financials]
        if len(periods) != len(set(periods)):
            rep.error(w, "duplicate financial periods")
        months = {f.period_months for f in item.financials}
        if len(months) > 1:
            rep.note(w, "mixed period lengths: only 12-month periods are used for annual metrics")
        if len([f for f in item.financials if f.period_months == 12]) < 3:
            rep.warn(w, "fewer than 3 annual periods: growth/stability metrics may be unavailable")
        for f in item.financials:
            _sanity_check_period(f"{w} {f.period_label}", f, rep, today)
        for p in item.peers:
            for k in ("pe", "ev_ebitda", "pb", "ps"):
                v = getattr(p, k)
                if v is not None and v <= 0:
                    rep.warn(f"{w} peer {p.name}", f"{k} is non-positive and will be excluded from valuation")
        if len(item.peers) < 3:
            rep.warn(w, "fewer than 3 peers: valuation score will likely be unavailable")
        if not iss.risk_disclosures_reviewed and not item.disclosures:
            rep.note(w, "risk disclosures not marked as reviewed: governance disclosure item will be left out")
        for snap in item.subscriptions:
            if iss.open_date and snap.as_of.date() < iss.open_date:
                rep.error(w, f"subscription snapshot {snap.as_of} precedes the issue opening")
    return bundle, rep


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------
def _effective_status(declared: str, is_admin: bool, rep: Report, where: str) -> str:
    if declared == "verified" and not is_admin:
        rep.warn(where, "only administrators can mark data as verified; stored as 'imported'")
        return "imported"
    return declared


def upsert_statement(db: Session, company_id: int, values: dict[str, Any], status: str, source_id: int | None, rep: Report, where: str) -> str:
    """Insert a period, versioning instead of overwriting. Returns 'inserted'|'unchanged'|'versioned'|'kept_verified'."""
    existing = db.execute(
        select(FinancialStatement).where(
            FinancialStatement.company_id == company_id,
            FinancialStatement.period_end == values["period_end"],
            FinancialStatement.period_months == values["period_months"],
            FinancialStatement.is_current.is_(True),
        )
    ).scalar_one_or_none()
    if existing is not None:
        same = all(getattr(existing, k) == values.get(k) for k in FIN_FIELDS)
        if same:
            return "unchanged"
        if existing.data_status == "verified" and status != "verified":
            rep.warn(where, "a verified snapshot exists for this period with different values; it was kept and the new values were not applied")
            return "kept_verified"
        existing.is_current = False
    row = FinancialStatement(
        company_id=company_id, data_status=status, source_record_id=source_id, is_current=True,
        supersedes_id=existing.id if existing else None, **values,
    )
    db.add(row)
    return "versioned" if existing else "inserted"


def commit_bundle(
    db: Session,
    bundle: ResearchBundle,
    rep: Report,
    *,
    user_id: int | None,
    is_admin: bool,
    filename: str,
    data_mode: str = DataMode.imported.value,
) -> dict[str, Any]:
    ds = ImportedDataset(user_id=user_id, filename=filename[:255], kind="bundle_json" if data_mode != "demo" else "demo_fixture", status="committed")
    db.add(ds)
    db.flush()
    src_status: dict[str, str] = {}
    src_ids: dict[str, int] = {}
    for s in bundle.sources:
        st = s.data_status if s.data_status == "synthetic" else _effective_status(s.data_status, is_admin, rep, f"sources.{s.key}")
        rec = SourceRecord(
            source_type=s.source_type, title=s.title, source_url=s.url, publication_date=s.publication_date,
            data_status=st, dataset_id=ds.id, notes=s.notes, currency="INR",
            raw_payload={"source": s.model_dump(mode="json")},
        )
        db.add(rec)
        db.flush()
        src_status[s.key], src_ids[s.key] = st, rec.id

    counts = {"companies": 0, "ipos_created": 0, "ipos_updated": 0, "financials": 0, "peers": 0, "disclosures": 0, "subscriptions": 0, "grey_market": 0}
    for item in bundle.ipos:
        cin = item.company
        company = db.execute(select(Company).where(func.lower(Company.name) == cin.name.lower())).scalar_one_or_none()
        iss_status = src_status[item.issue.source_key]
        if company is None:
            company = Company(name=cin.name, sector=cin.sector, created_by=user_id, data_status=iss_status)
            db.add(company)
            counts["companies"] += 1
        for k, v in cin.model_dump(exclude={"name"}).items():
            if v is not None:
                setattr(company, k, v)
        company.data_status = iss_status
        db.flush()

        q = select(IPOIssue).where(IPOIssue.company_id == company.id)
        ipo = db.execute(q.order_by(IPOIssue.id.desc())).scalars().first()
        issue_vals = item.issue.model_dump(exclude={"source_key"})
        if ipo is None:
            ipo = IPOIssue(company_id=company.id, created_by=user_id, **issue_vals)
            db.add(ipo)
            counts["ipos_created"] += 1
        else:
            if ipo.data_status == "verified" and iss_status != "verified":
                rep.warn(item.company.name, "existing issue record is verified; issue fields were not overwritten")
            else:
                for k, v in issue_vals.items():
                    if v is not None:
                        setattr(ipo, k, v)
            counts["ipos_updated"] += 1
        ipo.data_mode = data_mode
        ipo.data_status = iss_status if not (ipo.data_status == "verified" and iss_status != "verified") else ipo.data_status
        ipo.source_record_id = src_ids[item.issue.source_key]
        if item.issue.listing_price is not None:
            ipo.listing_data_status = iss_status
        db.flush()

        for f in item.financials:
            vals = f.model_dump(exclude={"source_key", "currency"})
            raw = dict(vals)
            for k in FIN_FIELDS:
                vals[k] = to_crore(vals[k], item.unit)
            vals["unit"], vals["currency"] = "crore", "INR"
            rec_id = src_ids[f.source_key]
            src_rec = db.get(SourceRecord, rec_id)
            if src_rec is not None and item.unit.lower() not in ("crore", "cr"):
                src_rec.transformation = f"amounts converted from {item.unit} to INR crore"
            if src_rec is not None:
                payload = dict(src_rec.raw_payload or {})
                payload.setdefault("raw_financials", []).append({"company": cin.name, "unit": item.unit, **{k: (str(v) if isinstance(v, date) else v) for k, v in raw.items()}})
                src_rec.raw_payload = payload
                src_rec.reporting_period = src_rec.reporting_period or f.period_label
            res = upsert_statement(db, company.id, vals, src_status[f.source_key], rec_id, rep, f"{cin.name} {f.period_label}")
            if res in ("inserted", "versioned"):
                counts["financials"] += 1

        existing_peers = {(p.name.lower(), p.as_of) for p in ipo.peers}
        for p in item.peers:
            if (p.name.lower(), p.as_of) in existing_peers:
                continue
            db.add(PeerSnapshot(ipo_id=ipo.id, data_status=src_status[p.source_key], source_record_id=src_ids[p.source_key], **p.model_dump(exclude={"source_key"})))
            counts["peers"] += 1
        existing_disc = {d.title.lower() for d in ipo.disclosures}
        for d in item.disclosures:
            if d.title.lower() in existing_disc:
                continue
            db.add(RiskDisclosure(ipo_id=ipo.id, data_status=src_status[d.source_key], source_record_id=src_ids[d.source_key], **d.model_dump(exclude={"source_key", "page"})))
            counts["disclosures"] += 1
        existing_subs = {(s.as_of, s.category) for s in ipo.subscriptions}
        for snap in item.subscriptions:
            if (snap.as_of.replace(tzinfo=None), snap.category) in existing_subs:
                continue
            db.add(SubscriptionSnapshot(ipo_id=ipo.id, as_of=snap.as_of.replace(tzinfo=None), category=snap.category, times_subscribed=snap.times_subscribed,
                                        data_status=src_status[snap.source_key], source_record_id=src_ids[snap.source_key]))
            counts["subscriptions"] += 1
        for g in item.grey_market:
            db.add(GreyMarketObservation(ipo_id=ipo.id, observed_at=g.observed_at.replace(tzinfo=None), premium_inr=g.premium_inr,
                                         data_status=src_status[g.source_key], source_record_id=src_ids[g.source_key]))
            counts["grey_market"] += 1
        for e in item.events:
            db.add(IssueEvent(ipo_id=ipo.id, event_type=e.event_type, event_date=e.event_date, description=e.description,
                              source_record_id=src_ids.get(e.source_key) if e.source_key else None))
    ds.record_counts = counts
    ds.validation_report = rep.as_dict()
    for w in rep.warnings[:500]:
        db.add(IngestionLog(dataset_id=ds.id, level="warning", message=f"{w['where']}: {w['message']}"[:2000]))
    db.commit()
    return {"dataset_id": ds.id, "counts": counts, "report": rep.as_dict()}


# ---------------------------------------------------------------------------
# CSV financial statements
# ---------------------------------------------------------------------------
CSV_REQUIRED = ("company_name", "period_label", "period_end", "unit", "source_title", "data_status")
CSV_COLUMNS = CSV_REQUIRED + ("period_months", "source_url", "publication_date") + FIN_FIELDS


def parse_financials_csv(db: Session, text: str, *, today: date | None = None) -> tuple[list[dict[str, Any]], Report]:
    rep = Report()
    today = today or date.today()
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        rep.error("file", "empty CSV")
        return [], rep
    headers = [h.strip() for h in reader.fieldnames]
    missing = [c for c in CSV_REQUIRED if c not in headers]
    if missing:
        rep.error("header", f"missing required columns: {', '.join(missing)}")
        return [], rep
    unknown = [h for h in headers if h not in CSV_COLUMNS]
    if unknown:
        rep.warn("header", f"ignored unknown columns: {', '.join(unknown)}")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    units_by_company: dict[str, set[str]] = {}
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            rep.error("file", f"more than {MAX_ROWS} rows")
            break
        r = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k}
        where = f"row {n}"
        row: dict[str, Any] = {"row": n}
        name = r.get("company_name") or ""
        comp = db.execute(select(Company).where(func.lower(Company.name) == name.lower())).scalar_one_or_none()
        if comp is None:
            rep.error(where, f"company {name!r} not found — import an IPO bundle for it first")
            continue
        row["company_id"], row["company_name"] = comp.id, comp.name
        try:
            row["period_end"] = date.fromisoformat(r["period_end"])
        except (ValueError, TypeError):
            rep.error(where, f"invalid period_end {r.get('period_end')!r}; use YYYY-MM-DD")
            continue
        try:
            row["period_months"] = int(r.get("period_months") or 12)
            if not 1 <= row["period_months"] <= 24:
                raise ValueError
        except ValueError:
            rep.error(where, "period_months must be an integer between 1 and 24")
            continue
        row["period_label"] = r["period_label"][:32]
        unit = (r.get("unit") or "").lower()
        if unit not in UNIT_TO_CRORE:
            rep.error(where, f"unsupported unit {unit!r}")
            continue
        units_by_company.setdefault(comp.name, set()).add(unit)
        status = (r.get("data_status") or "").lower()
        if status not in USER_STATUSES:
            rep.error(where, f"data_status must be one of {sorted(USER_STATUSES)}")
            continue
        row["data_status"] = status
        row["source_title"] = r["source_title"][:300]
        url = r.get("source_url") or None
        if url and not url.startswith(("http://", "https://")):
            rep.error(where, "source_url must start with http(s)://")
            continue
        row["source_url"] = url
        try:
            row["publication_date"] = date.fromisoformat(r["publication_date"]) if r.get("publication_date") else None
        except ValueError:
            rep.error(where, "invalid publication_date")
            continue
        raw_vals: dict[str, Any] = {}
        bad = False
        for k in FIN_FIELDS:
            v = r.get(k)
            if v in (None, "", "NA", "N/A", "-"):
                row[k] = None
                continue
            try:
                num = float(str(v).replace(",", ""))
            except ValueError:
                rep.error(where, f"{k}: {v!r} is not a number")
                bad = True
                break
            raw_vals[k] = num
            try:
                row[k] = to_crore(num, unit)
            except UnitError as exc:
                rep.error(where, str(exc))
                bad = True
                break
        if bad:
            continue
        row["raw"] = {"unit": unit, **raw_vals}
        key = (comp.name, row["period_end"].isoformat(), row["period_months"])
        if key in seen:
            rep.error(where, f"duplicate period {row['period_label']} for {comp.name}")
            continue
        seen.add(key)
        _sanity_check_period(f"{where} {comp.name} {row['period_label']}", row, rep, today)
        rows.append(row)
    for cname, units in units_by_company.items():
        if len(units) > 1:
            rep.warn(cname, f"mixed units in one company ({', '.join(sorted(units))}); all converted to crore — double-check the source")
    return rows, rep


def commit_financial_rows(db: Session, rows: list[dict[str, Any]], rep: Report, *, user_id: int | None, is_admin: bool, filename: str) -> dict[str, Any]:
    ds = ImportedDataset(user_id=user_id, filename=filename[:255], kind="financials_csv", status="committed")
    db.add(ds)
    db.flush()
    inserted = 0
    for r in rows:
        status = _effective_status(r["data_status"], is_admin, rep, f"row {r['row']}")
        rec = SourceRecord(
            source_type="import", title=r["source_title"], source_url=r["source_url"], publication_date=r["publication_date"],
            reporting_period=r["period_label"], currency="INR", unit="crore", data_status=status, dataset_id=ds.id,
            transformation=None if r["raw"]["unit"] in ("crore", "cr") else f"converted from {r['raw']['unit']} to INR crore",
            raw_payload={"row": r["row"], **r["raw"]},
        )
        db.add(rec)
        db.flush()
        vals = {k: r[k] for k in FIN_FIELDS}
        vals.update(period_label=r["period_label"], period_end=r["period_end"], period_months=r["period_months"], unit="crore", currency="INR")
        res = upsert_statement(db, r["company_id"], vals, status, rec.id, rep, f"row {r['row']}")
        if res in ("inserted", "versioned"):
            inserted += 1
        # touch the company's IPOs so caches/fingerprints refresh
        for ipo in db.execute(select(IPOIssue).where(IPOIssue.company_id == r["company_id"])).scalars():
            ipo.updated_at = utcnow()
            if ipo.data_mode == DataMode.demo.value and status != "synthetic":
                rep.warn(f"row {r['row']}", "real data added to a synthetic demo company; the company remains labelled as demo")
    ds.record_counts = {"financials": inserted, "rows": len(rows)}
    ds.validation_report = rep.as_dict()
    db.commit()
    return {"dataset_id": ds.id, "counts": ds.record_counts, "report": rep.as_dict()}


FINANCIALS_CSV_TEMPLATE = ",".join(CSV_COLUMNS) + "\n" + ",".join(
    [
        "Example Company Ltd", "FY2025", "2025-03-31", "crore", "RHP restated financial statements p.212", "imported",
        "12", "https://www.sebi.gov.in/", "2025-06-30",
        "1250.5", "210.2", "180.0", "120.4", "140.1", "60.0", "12.0", "1500", "700", "300", "90", "800", "600", "350",
    ]
) + "\n"
