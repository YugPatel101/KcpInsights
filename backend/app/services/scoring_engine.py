"""Quantitative IPO research scoring engine.

Pure, deterministic and independent of the database, the AI agent and the UI.
Given the same ``ScoringInputs`` and configuration, it returns the same result.

Scores (0–100)
--------------
* Quality      Q = Σ w_c · P_c over profitability, growth, cash flow, balance sheet, stability.
* Valuation    V = 100 · clip((V_high − V_ipo) / (V_high − V_low), 0, 1), V_low/V_high = peer percentiles.
* Risk         R = Σ w_k · R_k over financial, valuation, governance, market, data quality (higher = riskier).
* Composite    S = 0.45 Q + 0.30 V + 0.25 (100 − R).
* Coverage     C = 100 · Σ w_i I_i / Σ w_i (evidence completeness, NOT a probability).

No formula-level score is renormalised when a component is missing: the result is
marked ``incomplete`` and lists what is missing. Within one component, available
sub-metrics are re-weighted among themselves only if they carry at least
``min_submetric_weight_coverage`` of the component's weight (documented, configurable).

The research score is NOT a probability of listing gains and NOT investment advice.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from app.services.financial_metrics import (
    MetricValue,
    Period,
    annual_periods,
    compute_quality_metrics,
)
from app.services.normalization import normalize, normalize_risk, percentile

DISCLAIMER = (
    "Educational research output. Scores are transparent rule-based summaries of the stored "
    "inputs under configuration {version}; they are not investment advice, not a forecast and "
    "not a probability of listing gains."
)


@dataclass
class IssueInput:
    ipo_id: int
    company_name: str
    sector: str
    issue_type: str  # mainboard | sme
    price_band_low: float | None = None
    price_band_high: float | None = None
    final_issue_price: float | None = None
    post_issue_shares: float | None = None
    issue_size_cr: float | None = None
    fresh_issue_cr: float | None = None
    ofs_cr: float | None = None
    promoter_holding_post_pct: float | None = None
    risk_disclosures_reviewed: bool = False
    open_date: date | None = None
    data_status: str = "imported"
    source_record_id: int | None = None
    customer_concentration_pct: float | None = None
    customer_concentration_status: str | None = None


@dataclass
class PeerInput:
    name: str
    as_of: date
    pe: float | None = None
    ev_ebitda: float | None = None
    pb: float | None = None
    ps: float | None = None
    data_status: str = "imported"
    source_record_id: int | None = None
    ticker: str | None = None


@dataclass
class DisclosureInput:
    id: int | None
    category: str
    severity: str
    status: str  # confirmed_disclosure | unresolved_concern
    title: str
    data_status: str = "imported"
    source_record_id: int | None = None


@dataclass
class ScoringInputs:
    issue: IssueInput
    periods: list[Period]
    peers: list[PeerInput] = field(default_factory=list)
    disclosures: list[DisclosureInput] = field(default_factory=list)
    as_of: date | None = None  # reference date for staleness checks

    def fingerprint(self, config: dict[str, Any]) -> str:
        payload = {"inputs": asdict(self), "config": config}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# Statuses whose values may be used in calculations (synthetic allowed so that demo
# mode can exercise the pipeline; it is excluded from *evidence* coverage instead).
CALC_STATUSES = {"verified", "imported", "estimated", "synthetic"}


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(x, nd)


# ---------------------------------------------------------------------------
# Component aggregation helper
# ---------------------------------------------------------------------------
def _aggregate(name: str, items: list[dict[str, Any]], min_cov: float) -> dict[str, Any]:
    """Weighted mean of available item scores, re-weighted within the component.

    ``items`` entries: {key, weight, score|None, ...}. Returns status 'ok' or 'unavailable'.
    """
    total_w = sum(i["weight"] for i in items)
    avail = [i for i in items if i.get("score") is not None]
    avail_w = sum(i["weight"] for i in avail)
    weight_cov = avail_w / total_w if total_w else 0.0
    if not avail or weight_cov + 1e-9 < min_cov:
        return {
            "name": name,
            "score": None,
            "status": "unavailable",
            "weight_coverage": round(weight_cov, 4),
            "reason": (
                f"available sub-metrics carry {weight_cov:.0%} of the component weight; "
                f"at least {min_cov:.0%} is required"
            ),
            "items": items,
        }
    score = sum(i["weight"] * i["score"] for i in avail) / avail_w
    return {
        "name": name,
        "score": round(score, 2),
        "status": "ok",
        "weight_coverage": round(weight_cov, 4),
        "reason": None if weight_cov >= 0.999 else "re-weighted over available sub-metrics",
        "items": items,
    }


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
def score_quality(inputs: ScoringInputs, cfg: dict[str, Any]) -> dict[str, Any]:
    qcfg = cfg["quality"]
    usable = [p for p in inputs.periods if p.data_status in CALC_STATUSES]
    metrics = compute_quality_metrics(
        usable,
        min_periods_growth=qcfg["min_periods_for_growth"],
        min_periods_stability=qcfg["min_periods_for_stability"],
        customer_concentration_pct=inputs.issue.customer_concentration_pct,
        customer_concentration_status=inputs.issue.customer_concentration_status,
        admissible_statuses=CALC_STATUSES,
    )
    components: dict[str, Any] = {}
    for comp_name, comp_cfg in qcfg["components"].items():
        items = []
        for mkey, spec in comp_cfg.items():
            m: MetricValue = metrics[mkey]
            score: float | None
            if m.score_override is not None:
                score = m.score_override
            elif m.status == "ok" and m.value is not None:
                score = normalize(m.value, spec)
            else:
                score = None
            items.append(
                {
                    "key": mkey,
                    "weight": spec["weight"],
                    "score": _r(score),
                    "normalization": {k: v for k, v in spec.items() if k != "weight"},
                    "metric": m.to_dict(),
                }
            )
        components[comp_name] = _aggregate(comp_name, items, qcfg["min_submetric_weight_coverage"])
        components[comp_name]["weight"] = qcfg["weights"][comp_name]

    missing = [n for n, c in components.items() if c["status"] != "ok"]
    if missing:
        q, status = None, "insufficient_data"
    else:
        q = sum(qcfg["weights"][n] * components[n]["score"] for n in components)
        status = "ok"
    return {
        "score": _r(q),
        "status": status,
        "formula": "Q = 0.25·P + 0.20·G + 0.20·C + 0.20·B + 0.15·R (weights from config)",
        "weights": qcfg["weights"],
        "missing_components": missing,
        "components": components,
        "annual_periods_used": [p.label for p in annual_periods(usable)],
        "excluded_periods": [
            {"label": p.label, "reason": "interim period (not 12 months)" if p.months != 12 else f"status {p.data_status}"}
            for p in inputs.periods
            if p.months != 12 or p.data_status not in CALC_STATUSES
        ],
    }


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------
def _issue_price(issue: IssueInput) -> tuple[float | None, str]:
    if issue.final_issue_price:
        return issue.final_issue_price, "final issue price"
    if issue.price_band_high:
        return issue.price_band_high, "upper end of price band"
    return None, "unavailable"


def _ipo_multiple(kind: str, mcap: float, latest: Period, issue: IssueInput, allow_ps: bool) -> tuple[float | None, str | None, dict]:
    """Return (multiple, reason_if_unusable, calculation inputs)."""
    fresh = issue.fresh_issue_cr or 0.0
    if kind == "pe":
        if latest.pat is None:
            return None, "PAT missing", {}
        if latest.pat <= 0:
            return None, "earnings are zero or negative: P/E is not meaningful", {"pat": latest.pat}
        return mcap / latest.pat, None, {"market_cap_cr": mcap, "pat": latest.pat}
    if kind == "pb":
        if latest.total_equity is None:
            return None, "equity missing", {}
        book = latest.total_equity + fresh
        if book <= 0:
            return None, "post-issue book value is zero or negative: P/B not meaningful", {"book": book}
        return mcap / book, None, {"market_cap_cr": mcap, "post_issue_book_cr": book, "fresh_issue_cr": fresh}
    if kind == "ev_ebitda":
        if latest.ebitda is None or latest.total_debt is None or latest.cash_and_equivalents is None:
            return None, "EBITDA, debt or cash missing", {}
        if latest.ebitda <= 0:
            return None, "EBITDA is zero or negative: EV/EBITDA not meaningful", {"ebitda": latest.ebitda}
        ev = mcap + latest.total_debt - latest.cash_and_equivalents - fresh
        if ev <= 0:
            return None, "enterprise value is zero or negative", {"ev": ev}
        return ev / latest.ebitda, None, {
            "market_cap_cr": mcap,
            "debt": latest.total_debt,
            "cash": latest.cash_and_equivalents,
            "fresh_issue_cr_treated_as_cash": fresh,
            "enterprise_value_cr": ev,
            "ebitda": latest.ebitda,
        }
    if kind == "ps":
        if not allow_ps:
            return None, "price-to-sales disabled in configuration", {}
        if latest.revenue is None or latest.revenue <= 0:
            return None, "revenue missing or non-positive", {}
        return mcap / latest.revenue, None, {"market_cap_cr": mcap, "revenue": latest.revenue}
    return None, f"unknown multiple {kind}", {}


MULTIPLE_LABELS = {"pe": "P/E", "pb": "P/B", "ev_ebitda": "EV/EBITDA", "ps": "Price/Sales"}


def score_valuation(inputs: ScoringInputs, cfg: dict[str, Any]) -> dict[str, Any]:
    vcfg = cfg["valuation"]
    issue = inputs.issue
    base: dict[str, Any] = {
        "score": None,
        "status": "unavailable",
        "formula": "V = 100 · clip((V_high − V_IPO) / (V_high − V_low), 0, 1)",
        "kind": "relative valuation versus listed peers (not intrinsic value)",
        "flags": [],
        "attempts": [],
    }
    price, basis = _issue_price(issue)
    if price is None:
        return {**base, "reason": "issue price / price band missing"}
    if not issue.post_issue_shares:
        return {**base, "reason": "post-issue share count missing; market capitalisation cannot be derived"}
    ann = annual_periods([p for p in inputs.periods if p.data_status in CALC_STATUSES])
    if not ann:
        return {**base, "reason": "no annual financial period available"}
    latest = ann[-1]
    mcap = price * issue.post_issue_shares / 1e7
    sector = (issue.sector or "").lower()
    group = "financials" if any(s in sector for s in vcfg["financial_sectors"]) else "default"
    prefs = vcfg["multiple_preference"][group]
    ref = inputs.as_of or issue.open_date or date.today()

    attempts: list[dict[str, Any]] = []
    for kind in prefs:
        val, why, calc = _ipo_multiple(kind, mcap, latest, issue, vcfg["allow_price_to_sales"])
        if val is None:
            attempts.append({"multiple": kind, "used": False, "reason": why})
            if kind == "pe" and latest.pat is not None and latest.pat <= 0:
                base["flags"].append("Negative or zero earnings: P/E not computed.")
            continue
        peer_rows = []
        for p in inputs.peers:
            pv = getattr(p, kind)
            age = (ref - p.as_of).days
            usable = (
                pv is not None
                and pv > 0
                and p.data_status in CALC_STATUSES
                and abs(age) <= vcfg["peer_max_age_days"]
            )
            reason = None
            if pv is None:
                reason = "multiple not available"
            elif pv <= 0:
                reason = "non-positive multiple excluded"
            elif p.data_status not in CALC_STATUSES:
                reason = f"status {p.data_status}"
            elif abs(age) > vcfg["peer_max_age_days"]:
                reason = f"snapshot {age} days from reference date"
            peer_rows.append(
                {
                    "name": p.name,
                    "ticker": p.ticker,
                    "value": _r(pv),
                    "as_of": p.as_of.isoformat(),
                    "data_status": p.data_status,
                    "source_record_id": p.source_record_id,
                    "used": usable,
                    "excluded_reason": reason,
                }
            )
        vals: list[float] = [float(getattr(p, kind)) for p, r in zip(inputs.peers, peer_rows, strict=True) if r["used"]]
        if len(vals) < vcfg["min_peers"]:
            attempts.append(
                {"multiple": kind, "used": False, "ipo_multiple": _r(val), "reason": f"only {len(vals)} usable peers; need {vcfg['min_peers']}"}
            )
            continue
        low = percentile(vals, vcfg["low_percentile"])
        high = percentile(vals, vcfg["high_percentile"])
        med = percentile(vals, 50)
        if med <= 0 or (high - low) / med < vcfg["min_relative_spread"]:
            attempts.append({"multiple": kind, "used": False, "reason": "peer distribution too narrow to define a range"})
            continue
        v = 100.0 * max(0.0, min(1.0, (high - val) / (high - low)))
        attempts.append({"multiple": kind, "used": True})
        if kind == "ps":
            base["flags"].append("Valued on price-to-sales because earnings-based multiples are not meaningful.")
        return {
            **base,
            "score": _r(v),
            "status": "ok",
            "multiple": kind,
            "multiple_label": MULTIPLE_LABELS[kind],
            "ipo_multiple": _r(val),
            "price_used": price,
            "price_basis": basis,
            "market_cap_cr": _r(mcap),
            "latest_period": latest.label,
            "calculation_inputs": {k: _r(x) if isinstance(x, float) else x for k, x in calc.items()},
            "peer_low": _r(low),
            "peer_high": _r(high),
            "peer_median": _r(med),
            "low_percentile": vcfg["low_percentile"],
            "high_percentile": vcfg["high_percentile"],
            "premium_to_median_pct": _r((val / med - 1) * 100),
            "peers": peer_rows,
            "peer_selection": (
                f"Peers stored for this IPO with a positive {MULTIPLE_LABELS[kind]}, status in "
                f"{sorted(CALC_STATUSES)}, snapshot within {vcfg['peer_max_age_days']} days of {ref.isoformat()}."
            ),
            "attempts": attempts,
        }
    return {
        **base,
        "reason": "no applicable multiple with enough suitable peers",
        "market_cap_cr": _r(mcap),
        "price_used": price,
        "price_basis": basis,
        "attempts": attempts,
    }


# ---------------------------------------------------------------------------
# Evidence coverage
# ---------------------------------------------------------------------------
def _months_between(a: date, b: date) -> float:
    return (b - a).days / 30.4375


def evidence_coverage(inputs: ScoringInputs, cfg: dict[str, Any]) -> dict[str, Any]:
    ecfg = cfg["evidence"]
    sw: dict[str, float] = ecfg["status_weights"]
    issue = inputs.issue
    ref = inputs.as_of or issue.open_date or date.today()
    ann = annual_periods(inputs.periods)
    latest = ann[-1] if ann else None
    stale = latest is not None and _months_between(latest.period_end, ref) > ecfg["financials_max_age_months"]

    def item(key: str, present: bool, status: str | None, note: str | None = None) -> dict[str, Any]:
        w = ecfg["inputs"][key]
        credit = sw.get(status or "unavailable", 0.0) if present else 0.0
        return {"key": key, "weight": w, "present": present, "status": status if present else "unavailable", "credit": credit, "note": note}

    ist = issue.data_status
    items = [
        item("price_band", issue.price_band_high is not None, ist),
        item("post_issue_shares", issue.post_issue_shares is not None, ist),
        item("issue_size", issue.issue_size_cr is not None, ist),
        item("fresh_ofs_split", issue.fresh_issue_cr is not None and issue.ofs_cr is not None, ist),
        item("promoter_holding", issue.promoter_holding_post_pct is not None, ist),
    ]
    fin_map = {
        "fin_revenue": "revenue",
        "fin_ebitda": "ebitda",
        "fin_pat": "pat",
        "fin_operating_cash_flow": "operating_cash_flow",
        "fin_total_equity": "total_equity",
        "fin_total_debt": "total_debt",
        "fin_cash": "cash_and_equivalents",
        "fin_interest_expense": "interest_expense",
        "fin_capex": "capex",
    }
    for key, fld in fin_map.items():
        present = latest is not None and getattr(latest, fld) is not None and not stale
        note = "latest period older than threshold" if stale else None
        items.append(item(key, present, latest.data_status if latest else None, note))
    def weakest(statuses: list[str]) -> str | None:
        # the least admissible status among the records an item depends on
        return min(statuses, key=lambda s: sw.get(s, 0.0)) if statuses else None

    last3 = ann[-3:]
    items.append(item("fin_history_3y", len(ann) >= 3, weakest([p.data_status for p in last3])))
    vcfg = cfg["valuation"]
    fresh_peers = [p for p in inputs.peers if abs((ref - p.as_of).days) <= vcfg["peer_max_age_days"]]
    # credit the strongest min_peers snapshots: the set is only as good as its weakest member
    best = sorted(fresh_peers, key=lambda p: -sw.get(p.data_status, 0.0))[: vcfg["min_peers"]]
    items.append(item("peer_set", len(fresh_peers) >= vcfg["min_peers"], weakest([p.data_status for p in best])))
    items.append(item("risk_disclosures_reviewed", issue.risk_disclosures_reviewed, ist))
    items.append(item("customer_concentration", issue.customer_concentration_pct is not None, issue.customer_concentration_status))

    total = sum(i["weight"] for i in items)
    cov = 100.0 * sum(i["weight"] * i["credit"] for i in items) / total
    completeness = 100.0 * sum(i["weight"] for i in items if i["present"]) / total
    return {
        "coverage": round(cov, 2),
        "input_completeness": round(completeness, 2),
        "formula": "C = 100 · Σ w_i I_i / Σ w_i (I_i credited only for present, current, verified/imported inputs)",
        "note": (
            "Evidence coverage measures how much admissible evidence backs the score. It is not the "
            "probability that the score is correct. Synthetic and estimated inputs earn no credit."
        ),
        "financials_stale": stale,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------
def score_risk(inputs: ScoringInputs, cfg: dict[str, Any], valuation: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    rcfg = cfg["risk"]
    comps_cfg = rcfg["components"]
    issue = inputs.issue
    ann = annual_periods([p for p in inputs.periods if p.data_status in CALC_STATUSES])
    latest = ann[-1] if ann else None
    min_cov = rcfg["min_submetric_weight_coverage"]
    src = [latest.source_record_id] if latest and latest.source_record_id else []
    components: dict[str, Any] = {}

    # --- financial: rule-based distress flags -------------------------------------
    fc = comps_cfg["financial"]

    def flag(key: str, value: bool | None, evidence_txt: str) -> dict[str, Any]:
        return {
            "key": key,
            "weight": fc[key]["weight"],
            "score": None if value is None else (100.0 if value else 0.0),
            "triggered": value,
            "evidence": evidence_txt,
            "source_record_ids": src,
        }

    fin_items = []
    if latest is None:
        fin_items = [flag(k, None, "no annual period") for k in fc]
    else:
        pat, ocf, eq, debt = latest.pat, latest.operating_cash_flow, latest.total_equity, latest.total_debt
        fin_items.append(flag("latest_loss", None if pat is None else pat <= 0, f"PAT {latest.label}: {pat}"))
        fin_items.append(flag("negative_ocf_latest", None if ocf is None else ocf < 0, f"OCF {latest.label}: {ocf}"))
        fin_items.append(flag("negative_equity", None if eq is None else eq <= 0, f"Equity {latest.label}: {eq}"))
        thr = fc["interest_cover_below"]["threshold"]
        if latest.ebit is None or latest.interest_expense is None:
            ic_flag, ic_txt = None, "EBIT or interest expense missing"
        elif latest.interest_expense == 0:
            ic_flag, ic_txt = (False, "no interest expense, no debt") if debt == 0 else (None, "zero interest with debt: unclear")
        else:
            ic = latest.ebit / latest.interest_expense
            ic_flag, ic_txt = ic < thr, f"interest cover {ic:.2f}x vs threshold {thr}x"
        fin_items.append(flag("interest_cover_below", ic_flag, ic_txt))
        lthr = fc["leverage_above"]["threshold"]
        if eq is None or debt is None:
            lv_flag, lv_txt = None, "debt or equity missing"
        elif eq <= 0:
            lv_flag, lv_txt = False, "not assessed: negative equity is captured by its own flag (no double count)"
        else:
            lv_flag, lv_txt = debt / eq > lthr, f"D/E {debt / eq:.2f}x vs threshold {lthr}x"
        fin_items.append(flag("leverage_above", lv_flag, lv_txt))
    components["financial"] = _aggregate("financial", fin_items, min_cov)

    # --- valuation risk ----------------------------------------------------------------
    vc = comps_cfg["valuation"]
    if valuation.get("status") == "ok":
        prem = valuation["premium_to_median_pct"]
        prem_score = normalize_risk(prem, vc["premium_to_peer_median"]["a"], vc["premium_to_peer_median"]["b"])
        basis_score = vc["multiple_basis"]["scores"].get(valuation["multiple"], 50.0)
        val_items = [
            {"key": "premium_to_peer_median", "weight": vc["premium_to_peer_median"]["weight"], "score": _r(prem_score),
             "value": prem, "evidence": f"IPO {valuation['multiple_label']} {valuation['ipo_multiple']} vs peer median {valuation['peer_median']}"},
            {"key": "multiple_basis", "weight": vc["multiple_basis"]["weight"], "score": basis_score,
             "value": valuation["multiple"], "evidence": f"valued on {valuation['multiple_label']}"},
        ]
    else:
        val_items = [
            {"key": "premium_to_peer_median", "weight": vc["premium_to_peer_median"]["weight"], "score": None, "evidence": valuation.get("reason")},
            {"key": "multiple_basis", "weight": vc["multiple_basis"]["weight"], "score": None, "evidence": valuation.get("reason")},
        ]
    components["valuation"] = _aggregate("valuation", val_items, min_cov)

    # --- governance & disclosure ---------------------------------------------------------
    gc = comps_cfg["governance"]
    cd = gc["confirmed_disclosures"]
    usable_disc = [d for d in inputs.disclosures if d.data_status in CALC_STATUSES]
    gov_items = []
    if issue.risk_disclosures_reviewed or usable_disc:
        confirmed = [d for d in usable_disc if d.status == "confirmed_disclosure"]
        unresolved = [d for d in usable_disc if d.status != "confirmed_disclosure"]
        pts = sum(cd["severity_points"].get(d.severity, 0.0) for d in confirmed)
        pts += cd["unresolved_multiplier"] * sum(cd["severity_points"].get(d.severity, 0.0) for d in unresolved)
        gov_items.append({
            "key": "confirmed_disclosures", "weight": cd["weight"], "score": _r(min(cd["cap"], pts)),
            "evidence": f"{len(confirmed)} confirmed disclosure(s), {len(unresolved)} unresolved concern(s) (weighted ×{cd['unresolved_multiplier']})",
            "disclosure_ids": [d.id for d in usable_disc],
            "source_record_ids": sorted({d.source_record_id for d in usable_disc if d.source_record_id}),
        })
    else:
        gov_items.append({
            "key": "confirmed_disclosures", "weight": cd["weight"], "score": None,
            "evidence": "Risk disclosures have not been reviewed. Missing information is not evidence of misconduct; this item is left out.",
        })
    if issue.ofs_cr is not None and issue.issue_size_cr:
        ofs_share = issue.ofs_cr / issue.issue_size_cr * 100
        gov_items.append({"key": "ofs_share_of_issue", "weight": gc["ofs_share_of_issue"]["weight"],
                          "score": _r(normalize_risk(ofs_share, gc["ofs_share_of_issue"]["a"], gc["ofs_share_of_issue"]["b"])),
                          "value": _r(ofs_share), "evidence": f"OFS is {ofs_share:.1f}% of the issue"})
    else:
        gov_items.append({"key": "ofs_share_of_issue", "weight": gc["ofs_share_of_issue"]["weight"], "score": None, "evidence": "OFS split unavailable"})
    if issue.promoter_holding_post_pct is not None:
        ph = issue.promoter_holding_post_pct
        gov_items.append({"key": "promoter_holding_post", "weight": gc["promoter_holding_post"]["weight"],
                          "score": _r(normalize_risk(ph, gc["promoter_holding_post"]["a"], gc["promoter_holding_post"]["b"])),
                          "value": ph, "evidence": f"post-issue promoter holding {ph:.1f}%"})
    else:
        gov_items.append({"key": "promoter_holding_post", "weight": gc["promoter_holding_post"]["weight"], "score": None, "evidence": "promoter holding unavailable"})
    components["governance"] = _aggregate("governance", gov_items, min_cov)

    # --- market & industry -----------------------------------------------------------------
    mc = comps_cfg["market"]
    sc = mc["sector_cyclicality"]
    sector_key = (issue.sector or "").strip().lower()
    sector_score = sc["table"].get(sector_key)
    sector_note = "configured sector assumption (not company-specific evidence)"
    if sector_score is None:
        sector_score = sc["default"]
        sector_note = f"sector '{issue.sector}' not in table: default assumption used"
    mkt_items = [
        {"key": "sector_cyclicality", "weight": sc["weight"], "score": sector_score, "evidence": sector_note},
        {"key": "issue_type_liquidity", "weight": mc["issue_type_liquidity"]["weight"],
         "score": mc["issue_type_liquidity"]["scores"].get(issue.issue_type, 50.0), "evidence": f"{issue.issue_type} issue"},
    ]
    if issue.issue_size_cr is not None:
        mkt_items.append({"key": "issue_size", "weight": mc["issue_size"]["weight"],
                          "score": _r(normalize_risk(issue.issue_size_cr, mc["issue_size"]["a"], mc["issue_size"]["b"])),
                          "value": issue.issue_size_cr, "evidence": f"issue size ₹{issue.issue_size_cr:,.1f} cr"})
    else:
        mkt_items.append({"key": "issue_size", "weight": mc["issue_size"]["weight"], "score": None, "evidence": "issue size unavailable"})
    components["market"] = _aggregate("market", mkt_items, min_cov)

    # --- data quality ------------------------------------------------------------------------
    dq = 100.0 - evidence["coverage"]
    components["data_quality"] = {
        "name": "data_quality", "score": round(dq, 2), "status": "ok", "weight_coverage": 1.0, "reason": None,
        "items": [{"key": "inverse_evidence_coverage", "weight": 1.0, "score": round(dq, 2),
                   "evidence": "R_d = 100 − C. Reflects missing, stale or non-admissible inputs — not a claim about the company."}],
    }

    weights = rcfg["weights"]
    for n in components:
        components[n]["weight"] = weights[n]
    missing = [n for n, c in components.items() if c["status"] != "ok"]
    if missing:
        total, level, status = None, None, "insufficient_data"
    else:
        total = sum(weights[n] * components[n]["score"] for n in components)
        lv = rcfg["levels"]
        level = "low" if total < lv["low_below"] else ("high" if total >= lv["high_at_or_above"] else "moderate")
        status = "ok"
    return {
        "score": _r(total),
        "status": status,
        "level": level,
        "formula": "R = 0.25·R_f + 0.20·R_v + 0.20·R_g + 0.20·R_m + 0.15·R_d (higher = riskier)",
        "weights": weights,
        "missing_components": missing,
        "components": components,
    }


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------
def compute_scores(inputs: ScoringInputs, cfg: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    quality = score_quality(inputs, cfg)
    valuation = score_valuation(inputs, cfg)
    evidence = evidence_coverage(inputs, cfg)
    risk = score_risk(inputs, cfg, valuation, evidence)
    w = cfg["composite"]["weights"]
    missing: list[dict[str, Any]] = []
    if quality["score"] is None:
        missing.append({"component": "quality", "reason": f"insufficient data in: {', '.join(quality['missing_components'])}"})
    if valuation["score"] is None:
        missing.append({"component": "valuation", "reason": valuation.get("reason")})
    if risk["score"] is None:
        missing.append({"component": "risk", "reason": f"insufficient data in: {', '.join(risk['missing_components'])}"})
    if missing:
        composite, status = None, "incomplete"
    else:
        composite = w["quality"] * quality["score"] + w["valuation"] * valuation["score"] + w["risk_inverse"] * (100 - risk["score"])
        status = "complete"

    unavailable_metrics = []
    for cname, comp in quality["components"].items():
        for it in comp["items"]:
            if it["score"] is None:
                unavailable_metrics.append({"component": f"quality.{cname}", "metric": it["key"], "reason": it["metric"]["reason"]})
    warnings = []
    if evidence["financials_stale"]:
        warnings.append("Latest financial period is older than the staleness threshold.")
    if any(p.data_status == "synthetic" for p in inputs.periods) or inputs.issue.data_status == "synthetic":
        warnings.append("SYNTHETIC DEMONSTRATION DATA: these numbers are fictional and earn no evidence credit.")
    if quality["excluded_periods"]:
        warnings.append(f"{len(quality['excluded_periods'])} period(s) excluded from scoring (interim or inadmissible).")
    warnings.extend(valuation.get("flags", []))

    provenance = sorted(
        {p.source_record_id for p in inputs.periods if p.source_record_id}
        | {p.source_record_id for p in inputs.peers if p.source_record_id}
        | {d.source_record_id for d in inputs.disclosures if d.source_record_id}
        | ({inputs.issue.source_record_id} if inputs.issue.source_record_id else set())
    )
    ts = (now or datetime.now(UTC)).replace(microsecond=0)
    return {
        "ipo_id": inputs.issue.ipo_id,
        "company_name": inputs.issue.company_name,
        "status": status,
        "composite": _r(composite),
        "composite_formula": "S = 0.45·Q + 0.30·V + 0.25·(100 − R)",
        "composite_weights": w,
        "missing_components": missing,
        "quality": quality,
        "valuation": valuation,
        "risk": risk,
        "evidence": evidence,
        "coverage": evidence["coverage"],
        "warnings": warnings,
        "unavailable_metrics": unavailable_metrics,
        "provenance_source_record_ids": provenance,
        "config_version": cfg["version"],
        "input_fingerprint": inputs.fingerprint(cfg),
        "calculated_at": ts.isoformat(),
        "is_probability": False,
        "disclaimer": DISCLAIMER.format(version=cfg["version"]),
    }
