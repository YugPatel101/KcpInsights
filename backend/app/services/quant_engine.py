"""Quantitative IPO analysis engine (single source of every formula).

Inputs are stored financial statements (INR crore), issue terms, listed-peer multiples and
disclosures. Outputs are standard ratios, five component scores, the overall fundamental score Q,
a separate risk score and a full audit trail of how each number was produced.

Rules that keep the numbers honest:

* Only annual (12-month) periods are used for ratios; interim stubs are shown but not annualised.
* One reporting basis per calculation (consolidated preferred over standalone); never mixed.
* Figures marked ``requires_review`` (a failed accounting check) are never used.
* A ratio whose denominator is zero/negative, or a CAGR whose start or end is not positive, is
  reported as "not meaningful" — never forced to a number.
* Missing inputs lower coverage; Q is not issued below the configured coverage. Missing
  information never counts as a negative disclosure in the risk score.

Scores are methodology-dependent educational measures, not investment advice or probabilities.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

# Bumped whenever a formula or scoring rule changes, so stored results are recomputed (it is part of the fingerprint).
ENGINE_VERSION = "2.1.1"

DISCLAIMER = (
    "KcpInsights provides educational financial research and quantitative analysis. Scores are methodology-dependent, "
    "data may be incomplete or delayed, and the platform does not provide personalized investment advice or guarantee IPO performance."
)

FORMULAS = {
    "roe": "ROE = PAT ÷ average shareholders' equity × 100",
    "roce": "ROCE = EBIT ÷ average capital employed × 100; capital employed = total assets − current liabilities",
    "net_margin": "Net profit margin = PAT ÷ revenue from operations × 100",
    "ebitda_margin": "EBITDA margin = EBITDA ÷ revenue × 100; EBITDA = PBT + finance costs + depreciation & amortisation",
    "operating_margin": "Operating margin = EBIT ÷ revenue × 100; EBIT = PBT + finance costs",
    "roa": "ROA = PAT ÷ average total assets × 100",
    "gross_margin": "Gross margin (materials basis) = (revenue − cost of materials consumed) ÷ revenue × 100; purchases of traded goods and inventory changes are not deducted",
    "ebitda_cagr": "EBITDA CAGR = (ending ÷ beginning)^(1/years) − 1, only when both are positive",
    "eps_cagr": "EPS CAGR = (ending ÷ beginning basic EPS)^(1/years) − 1, only when both are positive",
    "debt_to_assets": "Debt/Assets = total borrowings ÷ total assets",
    "capex_intensity": "Capex intensity = capital expenditure ÷ revenue × 100",
    "receivable_days": "Receivable days = closing trade receivables ÷ revenue × 365",
    "inventory_days": "Inventory days = closing inventories ÷ revenue × 365 (sales basis: cost of goods sold is not reported consistently)",
    "price_to_sales": "Price/Sales = market capitalisation ÷ latest revenue",
    "revenue_cagr": "Revenue CAGR = (ending ÷ beginning)^(1/years) − 1",
    "pat_cagr": "PAT CAGR = (ending ÷ beginning)^(1/years) − 1, only when both are positive",
    "revenue_yoy": "Revenue growth (YoY) = revenue_t ÷ revenue_t−1 − 1",
    "pat_yoy": "PAT growth (YoY) = PAT_t ÷ PAT_t−1 − 1 (only when PAT_t−1 > 0)",
    "ebitda_growth": "EBITDA growth (YoY) = EBITDA_t ÷ EBITDA_t−1 − 1 (only when EBITDA_t−1 > 0)",
    "eps_growth": "EPS growth (YoY) = basic EPS_t ÷ basic EPS_t−1 − 1 (only when EPS_t−1 > 0)",
    "revenue_volatility": "Revenue growth volatility = standard deviation of YoY revenue growth (percentage points)",
    "growth_consistency": "Consistency = 60% × share of positive YoY revenue and PAT changes + 40% × volatility score",
    "current_ratio": "Current ratio = current assets ÷ current liabilities",
    "quick_ratio": "Quick ratio = (current assets − inventories) ÷ current liabilities (prepaid expenses are not separately reported in summary statements)",
    "cash_ratio": "Cash ratio = cash and cash equivalents ÷ current liabilities",
    "debt_to_equity": "Debt/Equity = total borrowings (current + non-current, excluding lease liabilities) ÷ total equity",
    "interest_coverage": "Interest coverage = EBIT ÷ finance costs",
    "debt_to_ebitda": "Debt/EBITDA = total borrowings ÷ EBITDA",
    "ocf_to_pat": "OCF/PAT = net cash from operating activities ÷ PAT",
    "fcf": "Free cash flow = operating cash flow − capital expenditure (purchase of property, plant, equipment and intangibles)",
    "fcf_margin": "FCF margin = free cash flow ÷ revenue × 100",
    "cash_conversion": "Cash conversion = operating cash flow ÷ EBITDA × 100",
    "cash_flow_consistency": "Cash-flow consistency = share of years with positive operating cash flow and positive free cash flow",
    "eps_post_issue": "Post-issue EPS = latest PAT ÷ post-issue shares",
    "pe": "P/E = issue price ÷ post-issue EPS",
    "bvps_post_issue": "Post-issue book value per share = (latest equity + fresh-issue proceeds) ÷ post-issue shares",
    "pb": "P/B = issue price ÷ post-issue book value per share",
    "market_cap": "Market capitalisation = issue price × post-issue shares",
    "enterprise_value": "EV = market capitalisation + borrowings − cash − fresh-issue proceeds (proceeds are cash on completion)",
    "ev_ebitda": "EV/EBITDA = enterprise value ÷ latest EBITDA",
    "Q": "Q = 0.25·P + 0.25·G + 0.20·F + 0.15·C + 0.15·V (weights from the active configuration)",
}

COMPONENT_LABELS = {"profitability": "Profitability", "growth": "Growth", "financial_health": "Financial health",
                    "cash_flow": "Cash flow", "valuation": "Valuation"}


# ---------------------------------------------------------------------------- inputs
@dataclass
class FinPeriod:
    label: str
    period_end: date
    months: int
    basis: str = "unknown"
    data_status: str = "imported"
    validation_status: str = "not_checked"
    source_record_id: int | None = None
    revenue: float | None = None
    other_income: float | None = None
    cost_of_materials: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    pbt: float | None = None
    pat: float | None = None
    depreciation: float | None = None
    interest_expense: float | None = None
    eps_basic: float | None = None
    total_assets: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    inventory: float | None = None
    trade_receivables: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    document_id: int | None = None


@dataclass
class IssueTerms:
    company_name: str
    sector: str
    issue_type: str
    price_band_low: float | None = None
    price_band_high: float | None = None
    final_issue_price: float | None = None
    pre_issue_shares: float | None = None
    post_issue_shares: float | None = None  # used only when pre-issue shares or fresh-issue size are unknown
    post_issue_shares_status: str | None = None
    fresh_issue_cr: float | None = None


@dataclass
class PeerMultiple:
    name: str
    pe: float | None
    pb: float | None
    ronw_pct: float | None
    basis: str | None
    period_label: str | None
    data_status: str


@dataclass
class RiskFacts:
    customer_concentration_pct: float | None = None
    customer_concentration_basis: str | None = None
    contingent_liabilities_cr: float | None = None
    contingent_basis: str | None = None
    auditor_qualifications: str | None = None  # "none" | "disclosed"
    disclosures: list[dict[str, Any]] = field(default_factory=list)  # confirmed RiskDisclosure rows
    requires_review_periods: int = 0
    lender_kpis: dict[str, Any] = field(default_factory=dict)  # as printed in the KPI table (unverified; never scored)


@dataclass
class EngineInputs:
    issue: IssueTerms
    periods: list[FinPeriod]
    peers: list[PeerMultiple]
    facts: RiskFacts
    as_of: date
    profile: str = "general"  # industry analysis profile (see services.industry_profiles)


# ---------------------------------------------------------------------------- helpers
def r2(x: float | None, nd: int = 2) -> float | None:
    return None if x is None or not math.isfinite(x) else round(x, nd)


def normalize(x: float, spec: dict[str, Any]) -> float:
    """Map x to 0–100 with a ``linear`` or ``band`` spec (see ``scoring_config``)."""
    if not math.isfinite(x):
        raise ValueError("cannot normalise a non-finite value")
    if spec["kind"] == "linear":
        z, f = float(spec["zero"]), float(spec["full"])
        return 100.0 * min(1.0, max(0.0, (x - z) / (f - z)))
    lo, hi, zl, zh = (float(spec[k]) for k in ("lo", "hi", "zero_low", "zero_high"))
    if lo <= x <= hi:
        return 100.0
    if x < lo:
        return 100.0 * max(0.0, (x - zl) / (lo - zl))
    return 100.0 * max(0.0, (zh - x) / (zh - hi))


def cagr(start: float | None, end: float | None, years: float) -> tuple[float | None, str | None]:
    """Compound annual growth in percent, or (None, reason) when it would mislead."""
    if start is None or end is None:
        return None, "input missing"
    if years <= 0:
        return None, "needs at least two periods"
    if start <= 0 or end <= 0:
        return None, "not meaningful: the starting or ending value is zero or negative"
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0, None


def years_between(a: date, b: date) -> float:
    return round((b - a).days / 365.25, 2)


def _avg(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else (a + b) / 2.0


@dataclass
class Metric:
    key: str
    label: str
    value: float | None
    unit: str
    formula: str
    period: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | unavailable | not_meaningful | not_applicable
    reason: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["value"] = r2(self.value, 4 if self.unit == "x" else 2)
        return d


def _m(key: str, label: str, value: float | None, unit: str, period: str | None = None, inputs: dict[str, Any] | None = None,
       reason: str | None = None, status: str | None = None, note: str | None = None) -> Metric:
    st = status or ("ok" if value is not None else ("not_meaningful" if reason and reason.startswith("not meaningful") else "unavailable"))
    return Metric(key, label, value if st == "ok" else None, unit, FORMULAS.get(key, ""), period, inputs or {}, st, reason, note)


# ---------------------------------------------------------------------------- period selection
def choose_basis(periods: list[FinPeriod], usable: set[str]) -> tuple[str | None, list[FinPeriod]]:
    """The reporting basis with the most usable annual periods (consolidated wins ties)."""
    ok = [p for p in periods if p.data_status in usable and p.validation_status != "failed" and p.months == 12]
    if not ok:
        return None, []
    order = {"consolidated": 0, "standalone": 1, "unknown": 2}
    counts: dict[str, int] = {}
    for p in ok:
        counts[p.basis] = counts.get(p.basis, 0) + 1
    basis = min(counts, key=lambda b: (-counts[b], order.get(b, 3)))
    return basis, sorted([p for p in ok if p.basis == basis], key=lambda p: p.period_end)


# ---------------------------------------------------------------------------- ratios
def compute_metrics(annual: list[FinPeriod], issue: IssueTerms, peers: list[PeerMultiple], cfg: dict[str, Any]) -> tuple[dict[str, Metric], dict[str, Any]]:
    """All standard ratios from annual periods (oldest → latest). Returns metrics and valuation context."""
    m: dict[str, Metric] = {}
    if not annual:
        return m, {}
    L = annual[-1]
    P = annual[-2] if len(annual) >= 2 else None
    lab = L.label

    # --- profitability
    te_avg = _avg(L.total_equity, P.total_equity) if P else None
    eq_note = None
    if te_avg is None and L.total_equity is not None:
        te_avg, eq_note = L.total_equity, "closing equity used: no opening balance available for an average"
    if L.pat is None or te_avg is None:
        m["roe"] = _m("roe", "Return on equity", None, "%", lab, reason="PAT or equity missing")
    elif te_avg <= 0:
        m["roe"] = _m("roe", "Return on equity", None, "%", lab, reason="not meaningful: average equity is zero or negative")
    else:
        m["roe"] = _m("roe", "Return on equity", L.pat / te_avg * 100, "%", lab, {"pat": L.pat, "average_equity": r2(te_avg)}, note=eq_note)

    def cap_emp(p: FinPeriod | None) -> float | None:
        return None if p is None or p.total_assets is None or p.current_liabilities is None else p.total_assets - p.current_liabilities

    ce = _avg(cap_emp(L), cap_emp(P)) if P else None
    ce_note = None
    if ce is None and cap_emp(L) is not None:
        ce, ce_note = cap_emp(L), "closing capital employed used: no opening balance available for an average"
    if L.ebit is None or ce is None:
        m["roce"] = _m("roce", "Return on capital employed", None, "%", lab, reason="EBIT or capital employed missing")
    elif ce <= 0:
        m["roce"] = _m("roce", "Return on capital employed", None, "%", lab, reason="not meaningful: capital employed is zero or negative")
    else:
        m["roce"] = _m("roce", "Return on capital employed", L.ebit / ce * 100, "%", lab, {"ebit": L.ebit, "average_capital_employed": r2(ce)}, note=ce_note)

    for key, label, num in (("net_margin", "Net profit margin", L.pat), ("ebitda_margin", "EBITDA margin", L.ebitda),
                            ("operating_margin", "Operating (EBIT) margin", L.ebit)):
        if num is None or L.revenue is None:
            m[key] = _m(key, label, None, "%", lab, reason="input missing")
        elif L.revenue <= 0:
            m[key] = _m(key, label, None, "%", lab, reason="not meaningful: revenue is zero or negative")
        else:
            m[key] = _m(key, label, num / L.revenue * 100, "%", lab, {"numerator": num, "revenue": L.revenue})

    ta_avg = _avg(L.total_assets, P.total_assets) if P else None
    ta_note = None
    if ta_avg is None and L.total_assets is not None:
        ta_avg, ta_note = L.total_assets, "closing total assets used: no opening balance available for an average"
    if L.pat is None or ta_avg is None:
        m["roa"] = _m("roa", "Return on assets", None, "%", lab, reason="PAT or total assets missing")
    elif ta_avg <= 0:
        m["roa"] = _m("roa", "Return on assets", None, "%", lab, reason="not meaningful: average total assets are zero or negative")
    else:
        m["roa"] = _m("roa", "Return on assets", L.pat / ta_avg * 100, "%", lab, {"pat": L.pat, "average_total_assets": r2(ta_avg)}, note=ta_note)
    if L.cost_of_materials is None or L.revenue is None:
        m["gross_margin"] = _m("gross_margin", "Gross margin (materials basis)", None, "%", lab, reason="cost of materials consumed not reported")
    elif L.revenue <= 0:
        m["gross_margin"] = _m("gross_margin", "Gross margin (materials basis)", None, "%", lab, reason="not meaningful: revenue is zero or negative")
    else:
        m["gross_margin"] = _m("gross_margin", "Gross margin (materials basis)", (L.revenue - L.cost_of_materials) / L.revenue * 100, "%", lab,
                               {"revenue": L.revenue, "cost_of_materials": L.cost_of_materials},
                               note="excludes purchases of stock-in-trade and inventory changes; compare only within one company")

    # --- growth
    first = annual[0]
    yrs = years_between(first.period_end, L.period_end)
    span = f"{first.label}–{L.label}"
    v, why = cagr(first.revenue, L.revenue, yrs) if len(annual) >= 2 else (None, "needs at least two annual periods")
    m["revenue_cagr"] = _m("revenue_cagr", "Revenue CAGR", v, "%", span, {"start": first.revenue, "end": L.revenue, "years": yrs}, reason=why)
    v, why = cagr(first.pat, L.pat, yrs) if len(annual) >= 2 else (None, "needs at least two annual periods")
    m["pat_cagr"] = _m("pat_cagr", "PAT CAGR", v, "%", span, {"start": first.pat, "end": L.pat, "years": yrs}, reason=why)
    v, why = cagr(first.ebitda, L.ebitda, yrs) if len(annual) >= 2 else (None, "needs at least two annual periods")
    m["ebitda_cagr"] = _m("ebitda_cagr", "EBITDA CAGR", v, "%", span, {"start": first.ebitda, "end": L.ebitda, "years": yrs}, reason=why)
    v, why = cagr(first.eps_basic, L.eps_basic, yrs) if len(annual) >= 2 else (None, "needs at least two annual periods")
    m["eps_cagr"] = _m("eps_cagr", "EPS CAGR", v, "%", span, {"start": first.eps_basic, "end": L.eps_basic, "years": yrs}, reason=why,
                       note="basic EPS as reported; share splits or bonus issues between periods are restated in the offer document")

    def yoy(fld: str) -> list[float]:
        out = []
        for a, b in zip(annual, annual[1:], strict=False):
            x, y = getattr(a, fld), getattr(b, fld)
            if x is not None and y is not None and x > 0:
                out.append((y / x - 1) * 100)
        return out

    rev_yoy, pat_yoy = yoy("revenue"), yoy("pat")
    for key, label, fld in (("revenue_yoy", "Revenue growth (YoY)", "revenue"), ("pat_yoy", "PAT growth (YoY)", "pat"),
                            ("ebitda_growth", "EBITDA growth (YoY)", "ebitda"), ("eps_growth", "EPS growth (YoY)", "eps_basic")):
        if P is None:
            m[key] = _m(key, label, None, "%", lab, reason="needs two annual periods")
            continue
        x, y = getattr(P, fld), getattr(L, fld)
        if x is None or y is None:
            m[key] = _m(key, label, None, "%", lab, reason="input missing")
        elif x <= 0:
            m[key] = _m(key, label, None, "%", lab, reason="not meaningful: previous-year value is zero or negative")
        else:
            m[key] = _m(key, label, (y / x - 1) * 100, "%", f"{P.label}→{L.label}", {"previous": x, "latest": y})
    if len(rev_yoy) >= 2:
        m["revenue_volatility"] = _m("revenue_volatility", "Revenue growth volatility", statistics.pstdev(rev_yoy), "pp", span, {"yoy_growth_pct": [r2(g) for g in rev_yoy]})
        changes = rev_yoy + pat_yoy
        pos = sum(1 for g in changes if g > 0) / len(changes)
        vol_score = normalize(statistics.pstdev(rev_yoy), cfg["ranges"]["growth_volatility_pp"])
        m["growth_consistency"] = _m("growth_consistency", "Growth consistency", 0.6 * pos * 100 + 0.4 * vol_score, "score", span,
                                     {"positive_changes": sum(1 for g in changes if g > 0), "changes": len(changes), "volatility_score": r2(vol_score)})
    else:
        reason = "needs at least three annual periods (two year-on-year changes)"
        m["revenue_volatility"] = _m("revenue_volatility", "Revenue growth volatility", None, "pp", span, reason=reason)
        m["growth_consistency"] = _m("growth_consistency", "Growth consistency", None, "score", span, reason=reason)

    # --- liquidity and leverage
    def ratio(key: str, label: str, num: float | None, den: float | None, unit: str = "x", den_name: str = "denominator") -> Metric:
        if num is None or den is None:
            return _m(key, label, None, unit, lab, reason="input missing")
        if den <= 0:
            return _m(key, label, None, unit, lab, reason=f"not meaningful: {den_name} is zero or negative")
        return _m(key, label, num / den, unit, lab, {"numerator": num, "denominator": den})

    m["current_ratio"] = ratio("current_ratio", "Current ratio", L.current_assets, L.current_liabilities, den_name="current liabilities")
    qa = None if L.current_assets is None or L.inventory is None else L.current_assets - L.inventory
    m["quick_ratio"] = ratio("quick_ratio", "Quick ratio", qa, L.current_liabilities, den_name="current liabilities")
    m["cash_ratio"] = ratio("cash_ratio", "Cash ratio", L.cash_and_equivalents, L.current_liabilities, den_name="current liabilities")
    m["debt_to_equity"] = ratio("debt_to_equity", "Debt/Equity", L.total_debt, L.total_equity, den_name="equity")
    if L.ebit is not None and L.interest_expense == 0:
        m["interest_coverage"] = _m("interest_coverage", "Interest coverage", None, "x", lab, {"ebit": L.ebit, "finance_costs": 0.0},
                                    status="ok", note="no finance costs: coverage is unlimited")
    else:
        m["interest_coverage"] = ratio("interest_coverage", "Interest coverage", L.ebit, L.interest_expense, den_name="finance costs")
    m["debt_to_ebitda"] = ratio("debt_to_ebitda", "Debt/EBITDA", L.total_debt, L.ebitda, den_name="EBITDA")
    m["debt_to_assets"] = ratio("debt_to_assets", "Debt/Assets", L.total_debt, L.total_assets, den_name="total assets")
    for key, label, num in (("receivable_days", "Receivable days", L.trade_receivables), ("inventory_days", "Inventory days", L.inventory)):
        if num is None or L.revenue is None:
            m[key] = _m(key, label, None, "days", lab, reason="input missing")
        elif L.revenue <= 0:
            m[key] = _m(key, label, None, "days", lab, reason="not meaningful: revenue is zero or negative")
        else:
            m[key] = _m(key, label, num / L.revenue * 365, "days", lab, {"closing_balance": num, "revenue": L.revenue})

    # --- cash flow
    m["ocf_to_pat"] = ratio("ocf_to_pat", "OCF/PAT", L.operating_cash_flow, L.pat, den_name="PAT")
    fcf = None if L.operating_cash_flow is None or L.capex is None else L.operating_cash_flow - L.capex
    m["fcf"] = _m("fcf", "Free cash flow", fcf, "₹ cr", lab, {"operating_cash_flow": L.operating_cash_flow, "capex": L.capex},
                  reason=None if fcf is not None else "operating cash flow or capex missing")
    m["fcf_margin"] = ratio("fcf_margin", "FCF margin", None if fcf is None else fcf * 100, L.revenue, "%", "revenue")
    m["capex_intensity"] = ratio("capex_intensity", "Capex intensity", None if L.capex is None else L.capex * 100, L.revenue, "%", "revenue")
    m["cash_conversion"] = ratio("cash_conversion", "Cash conversion (OCF/EBITDA)", None if L.operating_cash_flow is None else L.operating_cash_flow * 100,
                                 L.ebitda, "%", "EBITDA")
    obs = []
    for p in annual:
        if p.operating_cash_flow is not None:
            obs.append(p.operating_cash_flow > 0)
            if p.capex is not None:
                obs.append(p.operating_cash_flow - p.capex > 0)
    m["cash_flow_consistency"] = _m("cash_flow_consistency", "Cash-flow consistency", (sum(obs) / len(obs) * 100) if len(obs) >= 2 else None, "%", span,
                                    {"positive_observations": sum(obs), "observations": len(obs)},
                                    reason=None if len(obs) >= 2 else "needs operating cash flow for at least two years")

    # --- valuation (at the issue price, on post-issue shares)
    price = issue.final_issue_price or issue.price_band_high
    price_basis = "final issue price" if issue.final_issue_price else ("upper end of the price band (final price not yet announced)" if price else None)
    shares, shares_status = issue.post_issue_shares, issue.post_issue_shares_status
    if price and issue.pre_issue_shares and issue.fresh_issue_cr is not None:
        shares = issue.pre_issue_shares + issue.fresh_issue_cr * 1e7 / price  # fresh-issue shares depend on the price
        shares_status = "verified" if issue.final_issue_price else "estimated"
    ctx: dict[str, Any] = {"price": price, "price_basis": price_basis, "price_status": "verified" if issue.final_issue_price else ("estimated" if price else None),
                           "post_issue_shares": r2(shares, 0), "post_issue_shares_status": shares_status,
                           "post_issue_shares_formula": "shares before the issue + fresh-issue amount ÷ price" if issue.pre_issue_shares else None}
    if not price or not shares:
        why = "issue price not yet published" if not price else "post-issue share count not available"
        for key, label in (("pe", "P/E"), ("pb", "P/B"), ("ev_ebitda", "EV/EBITDA"), ("price_to_sales", "Price/Sales")):
            m[key] = _m(key, label, None, "x", lab, reason=why)
    else:
        mcap = price * shares / 1e7
        ctx["market_cap_cr"] = r2(mcap)
        m["market_cap"] = _m("market_cap", "Market capitalisation", mcap, "₹ cr", None, {"price": price, "post_issue_shares": shares})
        if L.revenue is None:
            m["price_to_sales"] = _m("price_to_sales", "Price/Sales", None, "x", lab, reason="revenue missing")
        elif L.revenue <= 0:
            m["price_to_sales"] = _m("price_to_sales", "Price/Sales", None, "x", lab, reason="not meaningful: revenue is zero or negative")
        else:
            m["price_to_sales"] = _m("price_to_sales", "Price/Sales", mcap / L.revenue, "x", lab, {"market_cap_cr": r2(mcap), "revenue": L.revenue})
        if L.pat is None:
            m["pe"] = _m("pe", "P/E", None, "x", lab, reason="PAT missing")
        elif L.pat <= 0:
            m["pe"] = _m("pe", "P/E", None, "x", lab, reason="not meaningful: latest PAT is zero or negative")
        else:
            eps = L.pat * 1e7 / shares
            m["eps_post_issue"] = _m("eps_post_issue", "Post-issue EPS", eps, "₹", lab, {"pat_cr": L.pat, "post_issue_shares": shares})
            m["pe"] = _m("pe", "P/E", price / eps, "x", lab, {"price": price, "post_issue_eps": r2(eps, 4)})
        if L.total_equity is None:
            m["pb"] = _m("pb", "P/B", None, "x", lab, reason="equity missing")
        else:
            book = L.total_equity + (issue.fresh_issue_cr or 0.0)
            if book <= 0:
                m["pb"] = _m("pb", "P/B", None, "x", lab, reason="not meaningful: post-issue book value is zero or negative")
            else:
                bvps = book * 1e7 / shares
                m["bvps_post_issue"] = _m("bvps_post_issue", "Post-issue book value per share", bvps, "₹", lab,
                                          {"equity_cr": L.total_equity, "fresh_issue_cr": issue.fresh_issue_cr or 0.0, "post_issue_shares": shares})
                m["pb"] = _m("pb", "P/B", price / bvps, "x", lab, {"price": price, "post_issue_bvps": r2(bvps, 4)})
        if L.total_debt is None or L.cash_and_equivalents is None:
            m["ev_ebitda"] = _m("ev_ebitda", "EV/EBITDA", None, "x", lab, reason="borrowings or cash missing")
        else:
            ev = mcap + L.total_debt - L.cash_and_equivalents - (issue.fresh_issue_cr or 0.0)
            m["enterprise_value"] = _m("enterprise_value", "Enterprise value", ev, "₹ cr", lab,
                                       {"market_cap": r2(mcap), "debt": L.total_debt, "cash": L.cash_and_equivalents, "fresh_issue_cr": issue.fresh_issue_cr or 0.0})
            if L.ebitda is None:
                m["ev_ebitda"] = _m("ev_ebitda", "EV/EBITDA", None, "x", lab, reason="EBITDA missing")
            elif L.ebitda <= 0:
                m["ev_ebitda"] = _m("ev_ebitda", "EV/EBITDA", None, "x", lab, reason="not meaningful: EBITDA is zero or negative")
            else:
                m["ev_ebitda"] = _m("ev_ebitda", "EV/EBITDA", ev / L.ebitda, "x", lab, {"enterprise_value": r2(ev), "ebitda": L.ebitda})

    # --- peers (medians reduce the influence of outliers)
    min_peers = cfg["peers"]["min_peers"]
    good = [p for p in peers if p.data_status == "verified"]
    pes = [p.pe for p in good if p.pe and p.pe > 0]
    pbs = [p.pb for p in good if p.pb and p.pb > 0]
    ronws = [p.ronw_pct for p in good if p.ronw_pct is not None]
    ctx["peers"] = {
        "count": len(good), "with_pe": len(pes), "with_pb": len(pbs), "min_peers": min_peers,
        "median_pe": r2(statistics.median(pes)) if len(pes) >= min_peers else None,
        "median_pb": r2(statistics.median(pbs)) if len(pbs) >= min_peers else None,
        "median_ronw_pct": r2(statistics.median(ronws)) if len(ronws) >= min_peers else None,
        "pe_quartiles": quartiles(pes) if len(pes) >= min_peers else None,
        "pb_quartiles": quartiles(pbs) if len(pbs) >= min_peers else None,
        "ronw_quartiles": quartiles(ronws) if len(ronws) >= min_peers else None,
        "basis": sorted({p.basis for p in good if p.basis}), "periods": sorted({p.period_label for p in good if p.period_label}),
        "excluded_loss_making": sum(1 for p in good if p.pe is None or p.pe <= 0),
        "note": None if len(pes) >= min_peers else f"fewer than {min_peers} listed peers with a positive P/E: peer valuation unavailable",
    }
    return m, ctx


def quartiles(xs: list[float]) -> dict[str, float | None]:
    """Q1, median and Q3 (inclusive method, as in spreadsheet QUARTILE.INC) with min and max."""
    v = sorted(xs)
    if len(v) == 1:
        return {"min": r2(v[0]), "q1": r2(v[0]), "median": r2(v[0]), "q3": r2(v[0]), "max": r2(v[0])}
    q = statistics.quantiles(v, n=4, method="inclusive")
    return {"min": r2(v[0]), "q1": r2(q[0]), "median": r2(q[1]), "q3": r2(q[2]), "max": r2(v[-1])}


# ---------------------------------------------------------------------------- scoring
def profile_of(cfg: dict[str, Any], profile: str) -> dict[str, Any]:
    """The industry profile's configuration (falls back to ``general``)."""
    profiles = cfg.get("profiles") or {}
    return profiles.get(profile) or profiles.get("general") or {"label": "General", "not_applicable": []}


def apply_applicability(m: dict[str, Metric], prof: dict[str, Any]) -> list[dict[str, Any]]:
    """Mark ratios that do not fit the business model. Their values stay visible but are never scored or counted as missing."""
    out = []
    for key in prof.get("not_applicable", []):
        mt = m.get(key)
        why = (prof.get("reasons") or {}).get(key) or f"not used for {prof.get('label', 'this industry')}"
        if mt is not None:
            mt.status, mt.reason = "not_applicable", f"not applicable: {why}"
        out.append({"key": key, "label": mt.label if mt else key, "reason": why})
    return out


def _component(name: str, items: list[tuple[str, float | None, str | None]], cfg: dict[str, Any], prof: dict[str, Any]) -> dict[str, Any]:
    label = COMPONENT_LABELS[name]
    if name in prof.get("not_applicable_components", []):
        why = (prof.get("reasons") or {}).get(name) or f"not applicable to {prof.get('label', 'this industry')}"
        return {"name": name, "label": label, "score": None, "coverage": None, "applicable": False, "items": [], "reason": f"not applicable: {why}"}
    weights = (prof.get("weights") or {}).get(name) or cfg["weights"][name]
    na = set(prof.get("not_applicable", []))
    rows = []
    num = den = total = 0.0
    for key, score, note in items:
        w = weights[key]
        if key in na:
            rows.append({"key": key, "weight": w, "score": None, "note": note, "available": False, "applicable": False})
            continue
        total += w
        rows.append({"key": key, "weight": w, "score": r2(score), "note": note, "available": score is not None, "applicable": True})
        if score is not None:
            num += w * score
            den += w
    cov = den / total if total else 0.0
    ok = cov >= cfg["coverage"]["component_min"] - 1e-9 and den > 0
    return {"name": name, "label": label, "score": r2(num / den) if ok else None, "coverage": r2(cov * 100), "applicable": True,
            "items": rows, "weights": weights, "reason": None if ok else f"only {cov * 100:.0f}% of this component's inputs are available"}


def score_components(m: dict[str, Metric], ctx: dict[str, Any], cfg: dict[str, Any], profile: str = "general",
                     lender_kpis: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    prof = profile_of(cfg, profile)
    R = {**cfg["ranges"], **(prof.get("ranges") or {})}

    def s(key: str, rng: str | None = None) -> float | None:
        mt = m.get(key)
        if mt is None or mt.value is None or mt.status != "ok":
            return None
        return normalize(mt.value, R[rng or key])

    cand: dict[str, tuple[float | None, str | None]] = {k: (s(k), None) for k in ("roe", "roce", "roa", "net_margin", "ebitda_margin",
                                                                                 "current_ratio", "debt_to_equity", "ocf_to_pat")}
    rev_g = m.get("revenue_cagr")
    rev_key = "revenue_cagr" if rev_g and rev_g.value is not None else "revenue_yoy"
    pat_g = m.get("pat_cagr")
    pat_key = "pat_cagr" if pat_g and pat_g.value is not None else "pat_yoy"
    cand["revenue_growth"] = (s(rev_key, "revenue_growth"), m[rev_key].label if rev_key in m else None)
    cand["pat_growth"] = (s(pat_key, "pat_growth"), m[pat_key].label if pat_key in m else None)
    gc = m.get("growth_consistency")
    cand["growth_consistency"] = (gc.value if gc is not None and gc.status == "ok" else None, None)
    icr = m.get("interest_coverage")
    unlimited = icr is not None and icr.status == "ok" and icr.value is None and icr.note
    cand["interest_coverage"] = (100.0 if unlimited else s("interest_coverage"), icr.note if icr else None)
    cand["fcf"] = (s("fcf_margin", "fcf_margin"), "scored on FCF margin")
    cfc = m.get("cash_flow_consistency")
    cand["cash_flow_consistency"] = (cfc.value if cfc is not None and cfc.status == "ok" else None, None)
    # lender and insurer health ratios are printed in KPI tables only: shown as reported, never scored unverified
    for key in ("gnpa_pct", "nnpa_pct", "crar_pct", "solvency_ratio"):
        printed = (lender_kpis or {}).get(key)
        cand[key] = (None, f"printed on p{printed['page']} of the offer document but not verifiable against the statements; not scored"
                     if printed else "not disclosed in a readable KPI table")
    peers = ctx.get("peers") or {}
    for key, med_key, abs_rng in (("pe", "median_pe", "pe_absolute"), ("pb", "median_pb", "pb_absolute"), ("ev_ebitda", None, "ev_ebitda_absolute")):
        mt = m.get(key)
        if mt is None or mt.value is None or mt.status != "ok":
            cand[key] = (None, mt.reason if mt else "unavailable")
            continue
        med = peers.get(med_key) if med_key else None
        if med:
            prem = (mt.value / med - 1) * 100
            cand[key] = (normalize(prem, R["relative_premium"]), f"{prem:+.1f}% vs peer median {med:g}x")
        else:
            cand[key] = (normalize(mt.value, R[abs_rng]), "absolute range (no peer median)")
    comps: dict[str, dict[str, Any]] = {}
    for name in COMPONENT_LABELS:
        weights = (prof.get("weights") or {}).get(name) or cfg["weights"][name]
        comps[name] = _component(name, [(k, *cand.get(k, (None, "unavailable"))) for k in weights], cfg, prof)
    return comps


def overall_score(comps: dict[str, dict[str, Any]], cfg: dict[str, Any], profile: str = "general") -> dict[str, Any]:
    prof = profile_of(cfg, profile)
    W = cfg["weights"]["overall"]
    applicable = [k for k, c in comps.items() if c.get("applicable", True)]
    avail = {k: comps[k]["score"] for k in applicable if comps[k]["score"] is not None}
    wsum = sum(W[k] for k in applicable)
    cov = sum(W[k] for k in avail) / wsum if wsum else 0.0
    not_applicable = [COMPONENT_LABELS[k] for k in W if k not in applicable]
    required = [k for k in prof.get("required_components", cfg["coverage"]["required_components"]) if k in applicable]
    missing_required = [k for k in required if k not in avail]
    base = {"formula": FORMULAS["Q"], "weights": W, "not_applicable": not_applicable, "weight_coverage": r2(cov * 100)}
    if missing_required or cov < cfg["coverage"]["overall_min"] - 1e-9:
        why = (f"required component(s) unavailable: {', '.join(COMPONENT_LABELS[k] for k in missing_required)}" if missing_required
               else f"only {cov * 100:.0f}% of the model weight is computable (minimum {cfg['coverage']['overall_min'] * 100:.0f}%)")
        return {**base, "score": None, "classification": None, "renormalized": False, "reason": why}
    q = sum(W[k] * v for k, v in avail.items()) / sum(W[k] for k in avail)
    label = next(lbl for bound, lbl in cfg["classification"] if q >= bound)
    excluded = [COMPONENT_LABELS[k] for k in applicable if k not in avail]
    notes = []
    if excluded:
        notes.append(f"computed without {', '.join(excluded)} (unavailable)")
    if not_applicable:
        notes.append(f"{', '.join(not_applicable)} not applicable to {prof.get('label', 'this industry')}")
    return {**base, "score": r2(q), "classification": label, "renormalized": bool(excluded), "excluded": excluded, "reason": None,
            "note": ("; ".join(notes) + "; remaining weights rescaled to sum to 1") if notes else None}


GOVERNANCE_KEYS = ("customer_concentration", "contingent_liabilities", "auditor_qualifications", "governance")


def risk_score(m: dict[str, Metric], ctx: dict[str, Any], facts: RiskFacts, annual: list[FinPeriod], coverage_pct: float, cfg: dict[str, Any],
               profile: str = "general") -> dict[str, Any]:
    RR = cfg["risk_ranges"]
    W = cfg["weights"]["risk"]
    prof = profile_of(cfg, profile)
    na_risk = set(prof.get("not_applicable_risk", []))
    comps: list[dict[str, Any]] = []

    def add(key: str, label: str, points: float | None, kind: str, detail: str | None) -> None:
        if key in na_risk:
            why = (prof.get("reasons") or {}).get(key) or f"not applicable to {prof.get('label', 'this industry')}"
            comps.append({"key": key, "label": label, "points": None, "weight": W[key], "kind": kind, "detail": f"not applicable: {why}",
                          "available": False, "applicable": False})
            return
        comps.append({"key": key, "label": label, "points": r2(points), "weight": W[key], "kind": kind, "detail": detail,
                      "available": points is not None, "applicable": True})

    def nz(x: float | None, rng: str) -> float | None:
        return None if x is None else normalize(x, RR[rng])

    de, debitda = m.get("debt_to_equity"), m.get("debt_to_ebitda")
    parts = [p for p in (nz(de.value if de else None, "debt_to_equity"), nz(debitda.value if debitda else None, "debt_to_ebitda")) if p is not None]
    add("leverage", "Financial leverage", sum(parts) / len(parts) if parts else None, "derived from financials",
        f"D/E {de.value:.2f}x" if de and de.value is not None else None)
    if len(annual) >= 2 and all(p.pat is not None and p.revenue for p in annual[-2:]):
        a, b = annual[-2], annual[-1]
        drop = (a.pat / a.revenue - b.pat / b.revenue) * 100  # type: ignore[operator]
        dec = (1 - b.pat / a.pat) * 100 if a.pat and a.pat > 0 else None  # type: ignore[operator]
        det = [x for x in (nz(drop, "net_margin_drop_pp"), nz(dec, "pat_decline_pct")) if x is not None]
        add("profitability_deterioration", "Profitability deterioration", sum(det) / len(det), "derived from financials",
            f"net margin change {-drop:+.2f} pp" + (f", PAT change {-dec:+.1f}%" if dec is not None else ""))
    else:
        add("profitability_deterioration", "Profitability deterioration", None, "derived from financials", "needs two annual periods")
    ocf = m.get("ocf_to_pat")
    ocf_years = [p.operating_cash_flow for p in annual if p.operating_cash_flow is not None]
    pts: list[float] = []
    if ocf is not None and ocf.value is not None:
        pts.append(normalize(ocf.value, RR["ocf_to_pat"]))
    if ocf_years:
        pts.append(100.0 * sum(1 for v in ocf_years if v < 0) / len(ocf_years))
    add("cash_flow_weakness", "Cash-flow weakness", sum(pts) / len(pts) if pts else None, "derived from financials",
        f"OCF/PAT {ocf.value:.2f}x" if ocf and ocf.value is not None else None)
    pe = m.get("pe")
    med = (ctx.get("peers") or {}).get("median_pe")
    if pe and pe.value is not None:
        if med:
            prem = (pe.value / med - 1) * 100
            add("valuation", "Valuation risk", nz(prem, "pe_premium_pct"), "derived from issue terms", f"P/E {pe.value:.1f}x vs peer median {med:g}x ({prem:+.0f}%)")
        else:
            add("valuation", "Valuation risk", nz(pe.value, "pe_absolute"), "derived from issue terms", f"P/E {pe.value:.1f}x (no peer median)")
    else:
        add("valuation", "Valuation risk", None, "derived from issue terms", pe.reason if pe else None)
    add("customer_concentration", "Customer concentration", nz(facts.customer_concentration_pct, "customer_concentration_pct"), "disclosed fact",
        f"{facts.customer_concentration_pct:g}% of revenue from {facts.customer_concentration_basis or 'top customers'}" if facts.customer_concentration_pct is not None else None)
    nw = annual[-1].total_equity if annual else None
    if facts.contingent_liabilities_cr is not None and nw and nw > 0:
        ratio_pct = facts.contingent_liabilities_cr / nw * 100
        add("contingent_liabilities", "Contingent liabilities", nz(ratio_pct, "contingent_to_net_worth_pct"), "disclosed fact",
            f"₹{facts.contingent_liabilities_cr:g} cr = {ratio_pct:.1f}% of net worth ({facts.contingent_basis or 'latest year'})")
    else:
        add("contingent_liabilities", "Contingent liabilities", None, "disclosed fact", None)
    aq = facts.auditor_qualifications
    add("auditor_qualifications", "Auditor qualifications", 0.0 if aq == "none" else (100.0 if aq == "disclosed" else None), "disclosed fact",
        {"none": "no qualifications not given effect to", "disclosed": "qualifications disclosed in the offer document"}.get(aq or "", None))
    sev = {"high": 100.0, "medium": 60.0, "low": 20.0}
    confirmed = [d for d in facts.disclosures if d.get("status") == "confirmed_disclosure" and d.get("category") in ("litigation", "regulatory", "related_party", "governance")]
    add("governance", "Governance & litigation disclosures", max((sev.get(d.get("severity", ""), 0.0) for d in confirmed), default=None) if confirmed else None,
        "disclosed fact", f"{len(confirmed)} confirmed disclosure(s)" if confirmed else None)
    dq = 100.0 - coverage_pct + (15.0 if facts.requires_review_periods else 0.0) + (10.0 if ctx.get("price_status") == "estimated" else 0.0)
    add("data_quality", "Data quality & uncertainty", min(100.0, max(0.0, dq)), "data quality",
        f"coverage {coverage_pct:.0f}%" + ("; periods needing review excluded" if facts.requires_review_periods else "")
        + ("; price is the upper band" if ctx.get("price_status") == "estimated" else ""))
    avail = [c for c in comps if c["available"]]
    den = sum(c["weight"] for c in avail)
    applicable_w = sum(c["weight"] for c in comps if c.get("applicable", True))
    # data quality alone says how much is unknown, not how risky the company is: no substantive input, no risk score
    substantive = [c for c in avail if c["key"] != "data_quality"]
    score = sum(c["weight"] * c["points"] for c in avail) / den if den and substantive else None
    level = next(lv for bound, lv in cfg["risk_levels"] if score is not None and score >= bound) if score is not None else None
    gov = [c for c in avail if c["key"] in GOVERNANCE_KEYS]
    gden = sum(c["weight"] for c in gov)
    governance = {"score": r2(sum(c["weight"] * c["points"] for c in gov) / gden) if gden else None,
                  "components": [c["key"] for c in gov], "available": len(gov), "of": len(GOVERNANCE_KEYS),
                  "formula": "Governance & disclosure risk = weighted average of the available disclosure-based risk components "
                             "(customer concentration, contingent liabilities, auditor qualifications, governance & litigation)",
                  "reason": None if gden else "no governance or disclosure facts could be read from the offer document"}
    return {"score": r2(score), "level": level, "components": comps, "weight_coverage": r2(den / applicable_w * 100) if applicable_w else None,
            "governance_disclosure": governance,
            "reason": None if score is not None else "no financial, valuation or disclosure risk input is available yet; data quality alone is not scored",
            "formula": "Risk = weighted average of available risk components (0 = low, 100 = high); unavailable components are excluded, not penalised"}


def fingerprint(inputs: EngineInputs, cfg: dict[str, Any]) -> str:
    payload = json.dumps([ENGINE_VERSION, asdict(inputs), cfg.get("version"), cfg], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def compute(inputs: EngineInputs, cfg: dict[str, Any]) -> dict[str, Any]:
    """Full analysis for one IPO. Deterministic: the same inputs and configuration give the same result."""
    usable = set(cfg["usable_statuses"])
    basis, annual = choose_basis(inputs.periods, usable)
    interim = [p for p in inputs.periods if p.months != 12 and p.basis == basis and p.data_status in usable]
    review = [p for p in inputs.periods if p.validation_status == "failed" or p.data_status == "requires_review"]
    inputs.facts.requires_review_periods = len(review)
    m, ctx = compute_metrics(annual, inputs.issue, inputs.peers, cfg)
    prof = profile_of(cfg, inputs.profile)
    applicability = apply_applicability(m, prof) if annual else []
    comps = score_components(m, ctx, cfg, inputs.profile, inputs.facts.lender_kpis) if annual else {
        k: {"name": k, "label": v, "score": None, "coverage": 0.0, "items": [], "applicable": True, "reason": "no usable annual financial statements"}
        for k, v in COMPONENT_LABELS.items()}
    W = cfg["weights"]["overall"]
    appl = [k for k, c in comps.items() if c.get("applicable", True)]
    coverage = sum(W[k] * (comps[k]["coverage"] or 0.0) / 100 for k in appl) / sum(W[k] for k in appl) * 100 if appl else 0.0
    overall = overall_score(comps, cfg, inputs.profile)
    if len(annual) < cfg["coverage"]["min_annual_periods"] and overall["score"] is not None:
        overall.update(score=None, classification=None, reason=f"needs at least {cfg['coverage']['min_annual_periods']} annual periods")
    risk = risk_score(m, ctx, inputs.facts, annual, coverage, cfg, inputs.profile)
    missing = [f"{c['label']}: {c['reason']}" for c in comps.values() if c["score"] is None and c.get("reason") and c.get("applicable", True)]
    missing += [f"{mt.label}: {mt.reason}" for mt in m.values() if mt.status not in ("ok", "not_applicable") and mt.reason]
    warnings = []
    if any(p.data_status == "synthetic" for p in annual):
        warnings.append("Includes SYNTHETIC demonstration data about a fictional company — not real financial facts.")
    if review:
        warnings.append(f"{len(review)} period(s) failed accounting checks and were excluded: " + ", ".join(sorted({p.label for p in review})))
    if ctx.get("price_status") == "estimated":
        warnings.append("Valuation uses the upper end of the price band; it will be recalculated when the final issue price is published.")
    if interim:
        warnings.append("Interim periods (" + ", ".join(p.label for p in interim) + ") are shown but not annualised or used in ratios.")
    status = "complete" if overall["score"] is not None and not overall.get("renormalized") else ("partial" if overall["score"] is not None else "insufficient")
    return {
        "config_version": cfg["version"], "engine_version": ENGINE_VERSION, "status": status, "as_of": inputs.as_of.isoformat(),
        "profile": {"key": inputs.profile if (cfg.get("profiles") or {}).get(inputs.profile) else "general", "label": prof.get("label", "General")},
        "applicability": applicability,
        "basis": basis, "periods_used": [p.label for p in annual], "latest_period": annual[-1].label if annual else None,
        "period_sources": [{"label": p.label, "period_end": p.period_end.isoformat(), "basis": p.basis, "data_status": p.data_status,
                            "validation_status": p.validation_status, "document_id": p.document_id, "source_record_id": p.source_record_id}
                           for p in annual],
        "price": {k: ctx.get(k) for k in ("price", "price_basis", "price_status", "post_issue_shares", "post_issue_shares_status",
                                          "post_issue_shares_formula", "market_cap_cr")},
        "metrics": {k: v.to_dict() for k, v in m.items()},
        "components": comps,
        "fundamental": overall,
        "composite": overall["score"],
        "classification": overall["classification"],
        "risk": risk,
        "peers": ctx.get("peers"),
        "coverage": r2(coverage),
        "missing": missing,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
        "input_fingerprint": fingerprint(inputs, cfg),
    }


HISTORY_KEYS = ("roe", "roce", "roa", "net_margin", "ebitda_margin", "operating_margin", "gross_margin", "current_ratio", "quick_ratio",
                "debt_to_equity", "debt_to_assets", "interest_coverage", "ocf_to_pat", "fcf", "capex_intensity", "receivable_days", "inventory_days",
                "revenue_yoy", "pat_yoy", "ebitda_growth", "eps_growth")


def ratio_history(inputs: EngineInputs, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Selected ratios for every annual period, computed by the same functions as the score."""
    _, annual = choose_basis(inputs.periods, set(cfg["usable_statuses"]))
    out = []
    for k in range(len(annual)):
        m, _ = compute_metrics(annual[: k + 1], inputs.issue, [], cfg)
        out.append({"period": annual[k].label, "period_end": annual[k].period_end.isoformat(),
                    **{key: (m[key].value if key in m else None) for key in HISTORY_KEYS}})
    return out


def price_sensitivity(inputs: EngineInputs, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Valuation multiples and score at each relevant issue price (band ends, final price)."""
    i = inputs.issue
    prices = {"lower end of band": i.price_band_low, "upper end of band": i.price_band_high, "final issue price": i.final_issue_price}
    out = []
    for label, p in prices.items():
        if not p:
            continue
        issue = IssueTerms(**{**asdict(i), "final_issue_price": p})
        r = compute(EngineInputs(issue, inputs.periods, inputs.peers, inputs.facts, inputs.as_of, inputs.profile), cfg)
        out.append({"label": label, "price": p, "pe": r["metrics"].get("pe", {}).get("value"), "pb": r["metrics"].get("pb", {}).get("value"),
                    "ev_ebitda": r["metrics"].get("ev_ebitda", {}).get("value"), "price_to_sales": r["metrics"].get("price_to_sales", {}).get("value"),
                    "market_cap_cr": r["price"].get("market_cap_cr"),
                    "valuation_score": r["components"]["valuation"]["score"], "fundamental_score": r["composite"]})
    return out
