"""Central field registry: where every important field comes from and how it is checked.

Each entry states the field's type and unit, its primary and fallback sources (field-specific
precedence, not one global ranking), the normalisation and validation applied, how often it is
refreshed, when it counts as stale, and what happens when no source provides it. The registry
drives the completeness service (``services.completeness``), the API (``GET /api/fields``) and
docs/DATA_DICTIONARY.md.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

GROUPS = {
    "issue": "IPO information",
    "financials": "Financial statements",
    "ratios": "Financial ratios",
    "valuation": "Valuation",
    "risk": "Risk information",
    "verification": "Source verification",
}

# weight of each group in the overall analysis-readiness percentage
GROUP_WEIGHTS = {"issue": 0.20, "financials": 0.30, "ratios": 0.20, "valuation": 0.15, "risk": 0.10, "verification": 0.05}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    dtype: str  # date | number | text | url | count | ratio | status
    unit: str | None
    primary: str
    secondary: tuple[str, ...] = ()
    normalization: str = ""
    validation: str = ""
    refresh: str = ""
    stale_after_hours: int | None = None
    fallback: str = "shown as unavailable with the reason; never replaced by zero or an average"
    stages: tuple[str, ...] = ()  # issue stages for which the field is expected; empty = always
    statement_field: str | None = None  # FinancialStatement column, for financial fields
    metric: str | None = None  # quant-engine metric key, for ratio and valuation fields

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["group_label"] = GROUPS[self.group]
        return d


NSE = "NSE public issue data (official)"
RHP = "Offer document — restated financial information (official)"
_ISSUE_REFRESH = "every 6 h while upcoming/open; on listing"
_LIVE = ("upcoming", "open", "closed", "awaiting_allotment", "awaiting_listing", "listing_unconfirmed", "listed")
_PRICED = ("open", "closed", "awaiting_allotment", "awaiting_listing", "listing_unconfirmed", "listed")
_AFTER_CLOSE = ("closed", "awaiting_allotment", "awaiting_listing", "listing_unconfirmed", "listed")

FIELDS: list[FieldSpec] = [
    # ---------------------------------------------------------------- issue
    FieldSpec("open_date", "Opening date", "issue", "date", None, NSE, ("SEBI RHP (dates printed on the cover)",),
              "ISO date (Asia/Kolkata calendar day)", "open ≤ close; later dates must not precede earlier ones", _ISSUE_REFRESH, 24,
              stages=_LIVE),
    FieldSpec("close_date", "Closing date", "issue", "date", None, NSE, ("SEBI RHP",), "ISO date", "close ≥ open", _ISSUE_REFRESH, 24, stages=_LIVE),
    FieldSpec("price_band", "Price band", "issue", "number", "₹ per share", NSE, ("Price-band advertisement / RHP addendum (SEBI)",),
              "low and high ₹ per share", "low ≤ high; both positive", _ISSUE_REFRESH, 24, stages=_PRICED),
    FieldSpec("final_issue_price", "Final issue price", "issue", "number", "₹ per share", "NSE past issues (final price)",
              ("Basis of allotment / prospectus",), "₹ per share", "within or equal to the price band", "daily after close", 48,
              fallback="valuation uses the upper end of the price band, labelled estimated", stages=("listed",)),
    FieldSpec("lot_size", "Lot size", "issue", "count", "shares", NSE, ("RHP",), "integer shares", "positive integer", _ISSUE_REFRESH, 24, stages=_PRICED),
    FieldSpec("issue_size_cr", "Issue size", "issue", "number", "₹ crore", NSE + " (issue-size sentence)", ("RHP cover page",),
              "rupee amounts as stated; share counts × final price (verified) or × upper band (estimated)", "fresh + OFS = total",
              _ISSUE_REFRESH, 24, fallback="share counts × upper end of band, labelled estimated", stages=_PRICED),
    FieldSpec("fresh_issue_cr", "Fresh issue", "issue", "number", "₹ crore", NSE, ("RHP",), "₹ crore", "≥ 0", _ISSUE_REFRESH, 24, stages=_PRICED),
    FieldSpec("pre_issue_shares", "Shares before the issue", "issue", "count", "shares", RHP, ("SEBI RHP",), "absolute count",
              "positive; read from the capital-structure section", "when the offer document is (re)processed", None),
    FieldSpec("post_issue_shares", "Post-issue shares", "issue", "count", "shares", "Derived: pre-issue shares + fresh issue ÷ price", (),
              "absolute count", "> pre-issue shares when there is a fresh issue", "recomputed when price or shares change", None,
              fallback="valuation multiples unavailable"),
    FieldSpec("allotment_date", "Allotment date", "issue", "date", None, "NSE / registrar announcement",
              ("SEBI T+3 timeline from the close date (estimated)",), "ISO date", "after close", "with issue details", None,
              fallback="estimated from the SEBI T+3 timeline and labelled expected", stages=_AFTER_CLOSE),
    FieldSpec("listing_date", "Listing date", "issue", "date", None, "NSE past issues (actual)", ("SEBI T+3 timeline (expected)",), "ISO date",
              "an expected date is never shown as actual", "every 45 min around listing", 24, stages=_AFTER_CLOSE),
    FieldSpec("listing_price", "Listing-day open", "issue", "number", "₹ per share", "NSE bhavcopy of the listing date (OpnPric)", (),
              "₹ per share", "bhavcopy previous close must equal the issue price (±0.5%)", "on listing day", None, stages=("listed",)),
    FieldSpec("subscription", "Subscription (consolidated)", "issue", "ratio", "times", "NSE consolidated bid details (all exchanges)", (),
              "times subscribed per category with 'as of' timestamp", "category totals non-negative", "every 20 min while open", 2,
              stages=_PRICED),
    FieldSpec("registrar", "Registrar", "issue", "text", None, NSE, ("RHP",), "as published", "non-empty", _ISSUE_REFRESH, None, stages=_LIVE),
    FieldSpec("offer_document", "Offer document (RHP)", "issue", "url", None, "NSE issue page (RHP archive)",
              ("SEBI red herring filings", "SEBI draft (DRHP) filings"), "allowlisted official URL", "host allowlist; SHA-256 of the file",
              "hourly document job; re-checked every 3 days while upcoming/open", None),
    FieldSpec("business_overview", "Business overview", "issue", "text", None, "Offer document — 'Our Business' section (quoted)", (),
              "first descriptive paragraph, whitespace normalised", "starts with the company's self-description", "when the offer document is processed",
              None, fallback="shown as unavailable; never written by KcpInsights"),
    FieldSpec("sector", "Sector", "issue", "text", None, "Offer document (industry classifier)", ("User import",),
              "one of the classifier's sectors, with evidence", "clear lead over the runner-up", "when the offer document is processed", None,
              fallback="'Unclassified' (general analysis profile)"),
    # ---------------------------------------------------------------- financial statements (latest annual period)
    FieldSpec("revenue", "Revenue from operations", "financials", "number", "₹ crore", RHP, ("SEBI RHP", "SEBI DRHP", "User import"),
              "₹ million / lakh / crore → crore", "total income = revenue + other income", "per document version", None, statement_field="revenue"),
    FieldSpec("pat", "Profit after tax", "financials", "number", "₹ crore", RHP, ("SEBI RHP", "User import"), "→ crore",
              "PAT = PBT − tax", "per document version", None, statement_field="pat"),
    FieldSpec("ebitda", "EBITDA", "financials", "number", "₹ crore", "Derived: PBT + finance costs + depreciation", (), "→ crore",
              "inputs from one period and basis", "per document version", None, statement_field="ebitda"),
    FieldSpec("total_assets", "Total assets", "financials", "number", "₹ crore", RHP, ("SEBI RHP", "User import"), "→ crore",
              "assets = equity + liabilities", "per document version", None, statement_field="total_assets"),
    FieldSpec("total_equity", "Total equity", "financials", "number", "₹ crore", RHP, ("SEBI RHP", "User import"), "→ crore",
              "equity = share capital + other equity (soft)", "per document version", None, statement_field="total_equity"),
    FieldSpec("total_debt", "Borrowings", "financials", "number", "₹ crore", "Derived: current + non-current borrowings", (),
              "lease liabilities excluded", "≥ 0", "per document version", None, statement_field="total_debt"),
    FieldSpec("cash_and_equivalents", "Cash and equivalents", "financials", "number", "₹ crore", RHP, (), "→ crore", "≥ 0",
              "per document version", None, statement_field="cash_and_equivalents"),
    FieldSpec("current_assets", "Current assets", "financials", "number", "₹ crore", RHP, (), "→ crore", "assets = current + non-current",
              "per document version", None, statement_field="current_assets"),
    FieldSpec("current_liabilities", "Current liabilities", "financials", "number", "₹ crore", RHP, (), "→ crore",
              "equity + non-current + current liabilities = total", "per document version", None, statement_field="current_liabilities"),
    FieldSpec("operating_cash_flow", "Operating cash flow", "financials", "number", "₹ crore", RHP, (), "→ crore",
              "cash-flow PBT = P&L PBT", "per document version", None, statement_field="operating_cash_flow"),
    FieldSpec("capex", "Capital expenditure", "financials", "number", "₹ crore", RHP + " (cash-flow statement)", (),
              "sum of purchases of PP&E and intangibles, as a positive amount", "≥ 0", "per document version", None, statement_field="capex"),
    FieldSpec("annual_periods", "Annual periods (≥ 3)", "financials", "count", "periods", RHP, (), "12-month periods on one basis",
              "distinct month-end dates in a plausible order", "per document version", None),
    # ---------------------------------------------------------------- ratios
    *[FieldSpec(k, lbl, "ratios", "ratio", u, "Quant engine (formula in FINANCIAL_FORMULAS.md)", (), "", "denominator > 0", "on every input change",
                None, fallback="shown as unavailable or not meaningful with the reason", metric=k)
      for k, lbl, u in (("roe", "ROE", "%"), ("roce", "ROCE", "%"), ("roa", "ROA", "%"), ("net_margin", "Net margin", "%"),
                        ("ebitda_margin", "EBITDA margin", "%"), ("revenue_cagr", "Revenue CAGR", "%"), ("pat_cagr", "PAT CAGR", "%"),
                        ("current_ratio", "Current ratio", "x"), ("debt_to_equity", "Debt/Equity", "x"), ("interest_coverage", "Interest coverage", "x"),
                        ("ocf_to_pat", "OCF/PAT", "x"), ("fcf", "Free cash flow", "₹ cr"))],
    # ---------------------------------------------------------------- valuation
    *[FieldSpec(k, lbl, "valuation", "ratio", u, "Quant engine at the issue price", (), "", "positive earnings / book value", "on price or input change",
                None, fallback="not meaningful for loss-making or negative-equity companies; reason shown", metric=k, stages=_PRICED)
      for k, lbl, u in (("market_cap", "Market capitalisation", "₹ cr"), ("pe", "P/E", "x"), ("pb", "P/B", "x"), ("ev_ebitda", "EV/EBITDA", "x"),
                        ("price_to_sales", "Price/Sales", "x"))],
    FieldSpec("peer_median_pe", "Peer median P/E", "valuation", "ratio", "x", "Offer document — Basis for Issue Price (listed peers)", (),
              "median of peers whose printed P/E = price ÷ diluted EPS (±10%)", "≥ 2 consistent peers", "per document version", None,
              fallback="valuation scored on absolute ranges; flagged as insufficient peer coverage"),
    # ---------------------------------------------------------------- risk
    FieldSpec("customer_concentration", "Customer concentration", "risk", "number", "% of revenue", RHP + " (risk factors)", (),
              "percentage of revenue from top customers", "0–100%", "per document version", None),
    FieldSpec("contingent_liabilities", "Contingent liabilities", "risk", "number", "₹ crore", RHP + " (restated notes)", (), "→ crore", "≥ 0",
              "per document version", None),
    FieldSpec("auditor_qualifications", "Auditor qualifications", "risk", "status", None, RHP + " (auditor's examination report)", (),
              "none | disclosed", "explicit statement required", "per document version", None),
    FieldSpec("promoter_holding", "Promoter holding (pre/post)", "risk", "number", "%", RHP + " (capital structure)",
              ("Exchange shareholding pattern after listing",), "% of shares", "0–100%", "per document version", None,
              fallback="not extracted automatically yet; shown as unavailable"),
    FieldSpec("litigation", "Outstanding litigation", "risk", "count", "cases", RHP + " (outstanding litigation section)", (),
              "counts and amounts by category", "", "per document version", None,
              fallback="not extracted automatically (tables vary too much to read reliably); never treated as 'no litigation'"),
    # ---------------------------------------------------------------- verification
    FieldSpec("statements_verified", "Statements reconciled", "verification", "status", None, "Accounting checks on extracted statements", (),
              "share of annual periods with status verified", "assets = equity + liabilities, PAT = PBT − tax, …", "per document version", None),
    FieldSpec("issue_data_official", "Issue data from an official source", "verification", "status", None, NSE, (),
              "field observations from official sources", "conflicts between sources flagged", _ISSUE_REFRESH, None),
    FieldSpec("document_hash", "Offer document stored with hash", "verification", "status", None, "Document pipeline", (),
              "SHA-256 of the PDF", "identical files deduplicated", "per download", None),
]

BY_KEY = {f.key: f for f in FIELDS}


def registry() -> list[dict[str, Any]]:
    return [f.as_dict() for f in FIELDS]


def fields_for(group: str) -> list[FieldSpec]:
    return [f for f in FIELDS if f.group == group]


@dataclass
class FieldState:
    """One field's state for one IPO, as shown on the completeness panel."""

    key: str
    label: str
    group: str
    status: str  # available | estimated | unavailable | requires_review | not_applicable | pending
    value: Any = None
    unit: str | None = None
    source: str | None = None
    period: str | None = None
    as_of: str | None = None
    data_status: str | None = None
    stale: bool = False
    reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
