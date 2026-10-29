"""Deterministic financial metrics computed from stored statements.

All inputs are plain dataclasses so the maths can be unit-tested without a database.
Amounts are INR crore. Ratios are returned in percent where the key says so.

Each metric is returned as a ``MetricValue`` carrying:
  * ``status``: ``ok`` | ``unavailable`` (inputs missing) | ``not_meaningful`` (inputs
    exist but the ratio is analytically undefined, e.g. CAGR from a loss);
  * ``score_override``: set only for explicitly documented edge rules (e.g. a
    debt-free company gets the best balance-sheet score for interest cover);
  * the formula, the exact inputs, the periods used and their source record ids.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

# Conversion factors into INR crore (1 crore = 10,000,000).
UNIT_TO_CRORE: dict[str, float] = {
    "crore": 1.0,
    "cr": 1.0,
    "lakh": 0.01,
    "lakhs": 0.01,
    "million": 0.1,
    "mn": 0.1,
    "billion": 100.0,
    "bn": 100.0,
    "thousand": 0.0001,
    "rupees": 1e-7,
    "inr": 1e-7,
}


class UnitError(ValueError):
    pass


def to_crore(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    key = unit.strip().lower()
    if key not in UNIT_TO_CRORE:
        raise UnitError(f"unsupported unit {unit!r}; expected one of {sorted(UNIT_TO_CRORE)}")
    return value * UNIT_TO_CRORE[key]


FIN_FIELDS = (
    "revenue",
    "ebitda",
    "ebit",
    "pat",
    "operating_cash_flow",
    "capex",
    "interest_expense",
    "total_assets",
    "total_liabilities",
    "total_debt",
    "cash_and_equivalents",
    "total_equity",
    "current_assets",
    "current_liabilities",
)


@dataclass
class Period:
    label: str
    period_end: date
    months: int = 12
    revenue: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    pat: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None  # positive number = cash outflow
    interest_expense: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    total_equity: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    data_status: str = "imported"
    source_record_id: int | None = None


@dataclass
class MetricValue:
    key: str
    label: str
    value: float | None
    unit: str
    status: str  # ok | unavailable | not_meaningful
    formula: str
    reason: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    periods: list[str] = field(default_factory=list)
    source_record_ids: list[int] = field(default_factory=list)
    score_override: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d["value"] is not None:
            d["value"] = round(d["value"], 4)
        return d


def _ok(key, label, value, unit, formula, inputs, periods) -> MetricValue:
    return MetricValue(
        key=key,
        label=label,
        value=value,
        unit=unit,
        status="ok",
        formula=formula,
        inputs=inputs,
        periods=[p.label for p in periods],
        source_record_ids=sorted({p.source_record_id for p in periods if p.source_record_id}),
    )


def _na(key, label, unit, formula, reason, status="unavailable", periods=()) -> MetricValue:
    return MetricValue(
        key=key,
        label=label,
        value=None,
        unit=unit,
        status=status,
        formula=formula,
        reason=reason,
        periods=[p.label for p in periods],
        source_record_ids=sorted({p.source_record_id for p in periods if p.source_record_id}),
    )


def _v(p: Period, fld: str) -> float:
    """Value of a field already filtered to be present."""
    v = getattr(p, fld)
    if v is None:
        raise ValueError(f"{fld} missing for {p.label}")
    return float(v)


def annual_periods(periods: list[Period]) -> list[Period]:
    """12-month periods sorted by period end (interim periods are not comparable)."""
    return sorted([p for p in periods if p.months == 12], key=lambda p: p.period_end)


def years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


def cagr(start: float | None, end: float | None, years: float) -> tuple[float | None, str | None]:
    """Compound annual growth rate in percent.

    CAGR = ((end / start) ** (1 / years) - 1) * 100. Undefined (returns a reason) when
    either value is missing, start/end is zero or negative, or years <= 0.
    """
    if start is None or end is None:
        return None, "start or end value missing"
    if years <= 0:
        return None, "period length must be positive"
    if start <= 0:
        return None, "start value is zero or negative; CAGR is undefined"
    if end <= 0:
        return None, "end value is zero or negative; CAGR is undefined"
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0, None


def yoy_growth(periods: list[Period], fld: str = "revenue") -> list[tuple[str, float]]:
    """Year-on-year growth (percent) between consecutive annual periods with prior value > 0."""
    out: list[tuple[str, float]] = []
    ann = annual_periods(periods)
    for prev, cur in zip(ann, ann[1:], strict=False):
        pv, cv = getattr(prev, fld), getattr(cur, fld)
        if pv is not None and cv is not None and pv > 0:
            out.append((cur.label, (cv / pv - 1.0) * 100.0))
    return out


# ---------------------------------------------------------------------------
# Individual metrics
# ---------------------------------------------------------------------------
def ebitda_margin(ann: list[Period]) -> MetricValue:
    k, lbl, f = "ebitda_margin", "EBITDA margin", "EBITDA / Revenue × 100 (latest FY)"
    if not ann:
        return _na(k, lbl, "%", f, "no annual period")
    p = ann[-1]
    if p.ebitda is None or p.revenue is None:
        return _na(k, lbl, "%", f, "EBITDA or revenue missing", periods=[p])
    if p.revenue <= 0:
        return _na(k, lbl, "%", f, "revenue is zero or negative", "not_meaningful", [p])
    return _ok(k, lbl, p.ebitda / p.revenue * 100, "%", f, {"ebitda": p.ebitda, "revenue": p.revenue}, [p])


def pat_margin(ann: list[Period]) -> MetricValue:
    k, lbl, f = "pat_margin", "PAT margin", "PAT / Revenue × 100 (latest FY)"
    if not ann:
        return _na(k, lbl, "%", f, "no annual period")
    p = ann[-1]
    if p.pat is None or p.revenue is None:
        return _na(k, lbl, "%", f, "PAT or revenue missing", periods=[p])
    if p.revenue <= 0:
        return _na(k, lbl, "%", f, "revenue is zero or negative", "not_meaningful", [p])
    return _ok(k, lbl, p.pat / p.revenue * 100, "%", f, {"pat": p.pat, "revenue": p.revenue}, [p])


def roe(ann: list[Period]) -> MetricValue:
    k, lbl, f = "roe", "Return on equity", "PAT / average(opening, closing equity) × 100"
    if not ann:
        return _na(k, lbl, "%", f, "no annual period")
    p = ann[-1]
    if p.pat is None or p.total_equity is None:
        return _na(k, lbl, "%", f, "PAT or equity missing", periods=[p])
    if p.total_equity <= 0:
        return _na(k, lbl, "%", f, "closing equity is zero or negative; ROE not meaningful", "not_meaningful", [p])
    used = [p]
    eq = p.total_equity
    if len(ann) >= 2 and ann[-2].total_equity is not None:
        eq = (ann[-2].total_equity + p.total_equity) / 2.0
        used = [ann[-2], p]
    if eq <= 0:
        return _na(k, lbl, "%", f, "average equity is zero or negative; ROE not meaningful", "not_meaningful", used)
    return _ok(k, lbl, p.pat / eq * 100, "%", f, {"pat": p.pat, "average_equity": eq}, used)


def roce(ann: list[Period]) -> MetricValue:
    k, lbl, f = "roce", "Return on capital employed", "EBIT / (equity + debt) × 100 (latest FY)"
    if not ann:
        return _na(k, lbl, "%", f, "no annual period")
    p = ann[-1]
    if p.ebit is None or p.total_equity is None or p.total_debt is None:
        return _na(k, lbl, "%", f, "EBIT, equity or debt missing", periods=[p])
    ce = p.total_equity + p.total_debt
    if ce <= 0:
        return _na(k, lbl, "%", f, "capital employed is zero or negative", "not_meaningful", [p])
    return _ok(k, lbl, p.ebit / ce * 100, "%", f, {"ebit": p.ebit, "capital_employed": ce}, [p])


def _cagr_metric(ann: list[Period], fld: str, key: str, label: str, min_periods: int) -> MetricValue:
    f = f"((last {fld} / first {fld}) ^ (1 / years) − 1) × 100"
    pts = [p for p in ann if getattr(p, fld) is not None]
    if len(pts) < min_periods:
        return _na(key, label, "%", f, f"need at least {min_periods} annual periods with {fld}", periods=pts)
    first, last = pts[0], pts[-1]
    yrs = years_between(first.period_end, last.period_end)
    val, reason = cagr(getattr(first, fld), getattr(last, fld), yrs)
    if val is None:
        return _na(key, label, "%", f, reason, "not_meaningful", [first, last])
    return _ok(
        key,
        label,
        val,
        "%",
        f,
        {"start": getattr(first, fld), "end": getattr(last, fld), "years": round(yrs, 3)},
        [first, last],
    )


def revenue_cagr(ann: list[Period], min_periods: int = 2) -> MetricValue:
    return _cagr_metric(ann, "revenue", "revenue_cagr", "Revenue CAGR", min_periods)


def pat_cagr(ann: list[Period], min_periods: int = 2) -> MetricValue:
    return _cagr_metric(ann, "pat", "pat_cagr", "PAT CAGR", min_periods)


def latest_revenue_growth(ann: list[Period]) -> MetricValue:
    k, lbl, f = "latest_revenue_growth", "Latest revenue growth (YoY)", "(Revenue_t / Revenue_t−1 − 1) × 100"
    if len(ann) < 2:
        return _na(k, lbl, "%", f, "need two annual periods", periods=ann)
    prev, cur = ann[-2], ann[-1]
    if prev.revenue is None or cur.revenue is None:
        return _na(k, lbl, "%", f, "revenue missing", periods=[prev, cur])
    if prev.revenue <= 0:
        return _na(k, lbl, "%", f, "prior revenue is zero or negative", "not_meaningful", [prev, cur])
    return _ok(k, lbl, (cur.revenue / prev.revenue - 1) * 100, "%", f, {"prior": prev.revenue, "latest": cur.revenue}, [prev, cur])


def ocf_to_pat(ann: list[Period]) -> MetricValue:
    k, lbl, f = "ocf_to_pat", "Operating cash flow / PAT", "Σ OCF / Σ PAT over periods with both values"
    pts = [p for p in ann if p.operating_cash_flow is not None and p.pat is not None]
    if not pts:
        return _na(k, lbl, "x", f, "no period with both OCF and PAT")
    s_ocf = sum(_v(p, "operating_cash_flow") for p in pts)
    s_pat = sum(_v(p, "pat") for p in pts)
    if s_pat <= 0:
        return _na(k, lbl, "x", f, "cumulative PAT is zero or negative; cash conversion ratio not meaningful", "not_meaningful", pts)
    return _ok(k, lbl, s_ocf / s_pat, "x", f, {"sum_ocf": s_ocf, "sum_pat": s_pat}, pts)


def fcf_margin(ann: list[Period]) -> MetricValue:
    k, lbl = "fcf_margin", "Free-cash-flow margin"
    f = "Σ (OCF − capex) / Σ revenue × 100; negative FCF is kept negative (scores toward 0)"
    pts = [p for p in ann if p.operating_cash_flow is not None and p.capex is not None and p.revenue is not None]
    if not pts:
        return _na(k, lbl, "%", f, "no period with OCF, capex and revenue")
    s_fcf = sum(_v(p, "operating_cash_flow") - _v(p, "capex") for p in pts)
    s_rev = sum(_v(p, "revenue") for p in pts)
    if s_rev <= 0:
        return _na(k, lbl, "%", f, "cumulative revenue is zero or negative", "not_meaningful", pts)
    return _ok(k, lbl, s_fcf / s_rev * 100, "%", f, {"sum_fcf": s_fcf, "sum_revenue": s_rev}, pts)


def positive_ocf_share(ann: list[Period]) -> MetricValue:
    k, lbl, f = "positive_ocf_share", "Share of periods with positive OCF", "count(OCF > 0) / count(OCF reported)"
    pts = [p for p in ann if p.operating_cash_flow is not None]
    if len(pts) < 2:
        return _na(k, lbl, "share", f, "need at least two periods with OCF", periods=pts)
    pos = sum(1 for p in pts if _v(p, "operating_cash_flow") > 0)
    return _ok(k, lbl, pos / len(pts), "share", f, {"positive": pos, "periods": len(pts)}, pts)


def debt_to_equity(ann: list[Period]) -> MetricValue:
    k, lbl, f = "debt_to_equity", "Debt / equity", "Total debt / total equity (latest FY)"
    if not ann:
        return _na(k, lbl, "x", f, "no annual period")
    p = ann[-1]
    if p.total_debt is None or p.total_equity is None:
        return _na(k, lbl, "x", f, "debt or equity missing", periods=[p])
    if p.total_equity <= 0:
        m = _na(k, lbl, "x", f, "equity is zero or negative: treated as the weakest balance-sheet outcome (score 0)", "not_meaningful", [p])
        m.score_override = 0.0
        m.inputs = {"total_debt": p.total_debt, "total_equity": p.total_equity}
        return m
    return _ok(k, lbl, p.total_debt / p.total_equity, "x", f, {"total_debt": p.total_debt, "total_equity": p.total_equity}, [p])


def interest_coverage(ann: list[Period]) -> MetricValue:
    k, lbl, f = "interest_coverage", "Interest coverage", "EBIT / interest expense (latest FY)"
    if not ann:
        return _na(k, lbl, "x", f, "no annual period")
    p = ann[-1]
    if p.ebit is None or p.interest_expense is None:
        return _na(k, lbl, "x", f, "EBIT or interest expense missing", periods=[p])
    if p.interest_expense == 0:
        if p.total_debt == 0:
            m = _na(k, lbl, "x", f, "no debt and no interest expense: best score by rule", "not_meaningful", [p])
            m.score_override = 100.0
            return m
        return _na(k, lbl, "x", f, "zero interest expense with debt outstanding or unknown debt", "not_meaningful", [p])
    return _ok(k, lbl, p.ebit / p.interest_expense, "x", f, {"ebit": p.ebit, "interest_expense": p.interest_expense}, [p])


def net_debt_to_ebitda(ann: list[Period]) -> MetricValue:
    k, lbl, f = "net_debt_to_ebitda", "Net debt / EBITDA", "(Debt − cash) / EBITDA (latest FY)"
    if not ann:
        return _na(k, lbl, "x", f, "no annual period")
    p = ann[-1]
    if p.total_debt is None or p.cash_and_equivalents is None or p.ebitda is None:
        return _na(k, lbl, "x", f, "debt, cash or EBITDA missing", periods=[p])
    nd = p.total_debt - p.cash_and_equivalents
    if nd <= 0:
        m = _na(k, lbl, "x", f, "net cash position: best score by rule", "not_meaningful", [p])
        m.score_override = 100.0
        m.inputs = {"net_debt": nd}
        return m
    if p.ebitda <= 0:
        return _na(k, lbl, "x", f, "EBITDA is zero or negative with net debt; ratio not meaningful", "not_meaningful", [p])
    return _ok(k, lbl, nd / p.ebitda, "x", f, {"net_debt": nd, "ebitda": p.ebitda}, [p])


def revenue_growth_volatility(ann: list[Period], min_periods: int = 3) -> MetricValue:
    k, lbl, f = "revenue_growth_volatility", "Revenue growth volatility", "sample std. dev. of YoY revenue growth (pp)"
    g = yoy_growth(ann)
    if len(ann) < min_periods or len(g) < 2:
        return _na(k, lbl, "pp", f, f"need at least {min_periods} annual periods (two growth rates)", periods=ann)
    return _ok(k, lbl, statistics.stdev([x for _, x in g]), "pp", f, {"growth_rates": {lbl_: round(v, 3) for lbl_, v in g}}, ann)


def positive_growth_share(ann: list[Period], min_periods: int = 3) -> MetricValue:
    k, lbl, f = "positive_growth_share", "Share of years with revenue growth", "count(YoY growth > 0) / count(YoY growth)"
    g = yoy_growth(ann)
    if len(ann) < min_periods or len(g) < 2:
        return _na(k, lbl, "share", f, f"need at least {min_periods} annual periods", periods=ann)
    pos = sum(1 for _, x in g if x > 0)
    return _ok(k, lbl, pos / len(g), "share", f, {"positive": pos, "growth_periods": len(g)}, ann)


def customer_concentration(pct: float | None, status: str | None, admissible: set[str]) -> MetricValue:
    k, lbl, f = "customer_concentration", "Customer concentration", "Disclosed revenue share of top customers (%)"
    if pct is None:
        return _na(k, lbl, "%", f, "no disclosed customer-concentration figure")
    if status not in admissible:
        return _na(k, lbl, "%", f, f"figure has status '{status}', not admissible for scoring")
    if not 0 <= pct <= 100:
        return _na(k, lbl, "%", f, "value outside 0–100 %", "not_meaningful")
    m = MetricValue(key=k, label=lbl, value=pct, unit="%", status="ok", formula=f, inputs={"top_customer_share_pct": pct})
    return m


def compute_quality_metrics(
    periods: list[Period],
    *,
    min_periods_growth: int = 2,
    min_periods_stability: int = 3,
    customer_concentration_pct: float | None = None,
    customer_concentration_status: str | None = None,
    admissible_statuses: set[str] | None = None,
) -> dict[str, MetricValue]:
    ann = annual_periods(periods)
    adm = admissible_statuses or {"verified", "imported", "synthetic", "estimated"}
    metrics = [
        ebitda_margin(ann),
        pat_margin(ann),
        roe(ann),
        roce(ann),
        revenue_cagr(ann, min_periods_growth),
        pat_cagr(ann, min_periods_growth),
        latest_revenue_growth(ann),
        ocf_to_pat(ann),
        fcf_margin(ann),
        positive_ocf_share(ann),
        debt_to_equity(ann),
        interest_coverage(ann),
        net_debt_to_ebitda(ann),
        revenue_growth_volatility(ann, min_periods_stability),
        positive_growth_share(ann, min_periods_stability),
        customer_concentration(customer_concentration_pct, customer_concentration_status, adm),
    ]
    return {m.key: m for m in metrics}


def period_ratios(p: Period) -> dict[str, float | None]:
    """Per-period derived ratios for display tables/charts."""

    def safe(n: float | None, d: float | None, scale: float = 1.0) -> float | None:
        if n is None or d is None or d == 0 or not math.isfinite(n) or not math.isfinite(d):
            return None
        return round(n / d * scale, 4)

    wc = None
    if p.current_assets is not None and p.current_liabilities is not None:
        wc = round(p.current_assets - p.current_liabilities, 4)
    fcf = None
    if p.operating_cash_flow is not None and p.capex is not None:
        fcf = round(p.operating_cash_flow - p.capex, 4)
    return {
        "ebitda_margin_pct": safe(p.ebitda, p.revenue, 100) if (p.revenue or 0) > 0 else None,
        "pat_margin_pct": safe(p.pat, p.revenue, 100) if (p.revenue or 0) > 0 else None,
        "debt_to_equity": safe(p.total_debt, p.total_equity) if (p.total_equity or 0) > 0 else None,
        "current_ratio": safe(p.current_assets, p.current_liabilities) if (p.current_liabilities or 0) > 0 else None,
        "working_capital_cr": wc,
        "free_cash_flow_cr": fcf,
        "ocf_to_pat": safe(p.operating_cash_flow, p.pat) if (p.pat or 0) > 0 else None,
    }
