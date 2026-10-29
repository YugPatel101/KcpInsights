"""Deterministic scenario analysis (hypothetical, not a listing-price forecast).

Per-share value is derived from an explicit equity value and the post-issue diluted
share count, never from ambiguous per-share shortcuts:

  P/E method       PAT_s   = Revenue_0 · (1 + g) · m · k            (k = PAT / EBITDA conversion)
                   Equity_s = PAT_s · PE_s · (1 + market_adj)
  EV/EBITDA method EBITDA_s = Revenue_0 · (1 + g) · m
                   Equity_s = EBITDA_s · EV/EBITDA_s · (1 + market_adj) − net_debt_post_issue
  Price            P_s = Equity_s (₹ crore) · 10^7 / post-issue diluted shares
  Return           r_s = (P_s − P_issue) / P_issue

Net debt post issue = debt − cash − fresh-issue proceeds (proceeds treated as cash).
"""
from __future__ import annotations

from typing import Any

from app.services.financial_metrics import annual_periods, cagr, years_between
from app.services.normalization import percentile
from app.services.scoring_engine import CALC_STATUSES, ScoringInputs, _issue_price

SCENARIO_NOTE = (
    "Hypothetical scenario arithmetic under the stated assumptions. It is not a forecast of the "
    "listing price, and actual outcomes can fall outside every scenario shown."
)

OVERRIDABLE = {"revenue_growth_pct", "ebitda_margin_pct", "pat_to_ebitda", "multiple", "market_adjustment_pct", "method"}


def _peer_values(inputs: ScoringInputs, kind: str) -> list[float]:
    return [getattr(p, kind) for p in inputs.peers if getattr(p, kind) and getattr(p, kind) > 0 and p.data_status in CALC_STATUSES]


def derive_defaults(inputs: ScoringInputs, cfg: dict[str, Any]) -> dict[str, Any]:
    """Data-derived starting assumptions with an explanation of each."""
    scfg = cfg["scenario"]
    ann = annual_periods([p for p in inputs.periods if p.data_status in CALC_STATUSES])
    out: dict[str, Any] = {"available": True, "reasons": [], "notes": {}}
    if not ann or ann[-1].revenue is None or ann[-1].revenue <= 0:
        return {"available": False, "reasons": ["latest annual revenue missing or non-positive"]}
    latest = ann[-1]
    out["base_revenue_cr"] = latest.revenue
    out["base_period"] = latest.label

    growth = None
    rev_pts = [p for p in ann if p.revenue is not None]
    if len(rev_pts) >= 2:
        growth, _ = cagr(rev_pts[0].revenue, rev_pts[-1].revenue, years_between(rev_pts[0].period_end, rev_pts[-1].period_end))
        out["notes"]["revenue_growth_pct"] = (f"historical revenue CAGR {rev_pts[0].label}–{rev_pts[-1].label}, "
                                              f"capped to [{scfg['base_growth_floor_pct']}, {scfg['base_growth_cap_pct']}] %")
    if growth is None:
        out["reasons"].append("historical revenue growth unavailable; supply revenue_growth_pct")
    else:
        growth = max(scfg["base_growth_floor_pct"], min(scfg["base_growth_cap_pct"], growth))
    out["revenue_growth_pct"] = growth

    if latest.ebitda is None:
        out["ebitda_margin_pct"] = None
        out["reasons"].append("latest EBITDA missing; supply ebitda_margin_pct")
    else:
        out["ebitda_margin_pct"] = latest.ebitda / out["base_revenue_cr"] * 100
        out["notes"]["ebitda_margin_pct"] = f"{latest.label} EBITDA margin"

    if latest.pat is not None and latest.ebitda and latest.pat > 0 and latest.ebitda > 0:
        out["pat_to_ebitda"] = latest.pat / latest.ebitda
        out["notes"]["pat_to_ebitda"] = f"{latest.label} PAT / EBITDA"
    else:
        out["pat_to_ebitda"] = None

    min_peers = cfg["valuation"]["min_peers"]
    pe_vals, ev_vals = _peer_values(inputs, "pe"), _peer_values(inputs, "ev_ebitda")
    if out["pat_to_ebitda"] is not None and len(pe_vals) >= min_peers:
        out["method"], out["peer_values"] = "pe", pe_vals
    elif len(ev_vals) >= min_peers:
        out["method"], out["peer_values"] = "ev_ebitda", ev_vals
    else:
        out["method"], out["peer_values"] = None, []
        out["reasons"].append(f"fewer than {min_peers} peers with a usable P/E or EV/EBITDA")
    if latest.total_debt is not None and latest.cash_and_equivalents is not None:
        out["net_debt_post_issue_cr"] = latest.total_debt - latest.cash_and_equivalents - (inputs.issue.fresh_issue_cr or 0.0)
    else:
        out["net_debt_post_issue_cr"] = None
    return out


def run_scenarios(
    inputs: ScoringInputs,
    cfg: dict[str, Any],
    overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    overrides = overrides or {}
    price, basis = _issue_price(inputs.issue)
    shares = inputs.issue.post_issue_shares
    d = derive_defaults(inputs, cfg)
    result: dict[str, Any] = {
        "note": SCENARIO_NOTE,
        "is_forecast": False,
        "issue_price": price,
        "issue_price_basis": basis,
        "post_issue_shares": shares,
        "config_version": cfg["version"],
        "formulas": {
            "pe": "P = Revenue₀·(1+g)·m·k · PE · (1+adj) · 10⁷ / shares",
            "ev_ebitda": "P = [Revenue₀·(1+g)·m · EV/EBITDA · (1+adj) − net debt post-issue] · 10⁷ / shares",
            "return": "r = (P − P_issue) / P_issue",
        },
        "scenarios": [],
    }
    if not d.get("available"):
        result["status"] = "unavailable"
        result["reasons"] = d["reasons"]
        return result
    if price is None or not shares:
        result["status"] = "unavailable"
        result["reasons"] = ["issue price and post-issue share count are required"]
        return result
    result["base_revenue_cr"] = d["base_revenue_cr"]
    result["base_period"] = d["base_period"]
    result["derivation_notes"] = d["notes"]

    for name, sd in cfg["scenario"]["defaults"].items():
        ov = {k: v for k, v in (overrides.get(name) or {}).items() if k in OVERRIDABLE and v is not None}
        method = ov.get("method", d["method"])
        a: dict[str, Any] = {"method": method, "market_adjustment_pct": ov.get("market_adjustment_pct", sd["market_adjustment_pct"])}
        problems: list[str] = []
        g = ov.get("revenue_growth_pct", None if d["revenue_growth_pct"] is None else d["revenue_growth_pct"] + sd["growth_delta_pp"])
        m = ov.get("ebitda_margin_pct", None if d["ebitda_margin_pct"] is None else d["ebitda_margin_pct"] + sd["margin_delta_pp"])
        a["revenue_growth_pct"], a["ebitda_margin_pct"] = g, m
        if g is None:
            problems.append("revenue growth assumption missing")
        if m is None:
            problems.append("EBITDA margin assumption missing")
        if method not in ("pe", "ev_ebitda"):
            problems.append("no supported valuation method (need peers with P/E or EV/EBITDA)")
        mult = ov.get("multiple")
        if mult is None and method in ("pe", "ev_ebitda"):
            vals = d["peer_values"] if method == d["method"] else _peer_values(inputs, method)
            if len(vals) >= cfg["valuation"]["min_peers"]:
                mult = percentile(vals, sd["multiple_percentile"])
                a["multiple_source"] = f"peer {method} p{sd['multiple_percentile']} (n={len(vals)})"
            else:
                problems.append(f"not enough peers for {method}")
        else:
            a["multiple_source"] = "user override"
        a["multiple"] = mult
        k = ov.get("pat_to_ebitda", d["pat_to_ebitda"])
        if method == "pe":
            a["pat_to_ebitda"] = k
            if k is None:
                problems.append("PAT/EBITDA conversion unavailable (historical PAT or EBITDA not positive); use EV/EBITDA or supply pat_to_ebitda")
        if method == "ev_ebitda":
            a["net_debt_post_issue_cr"] = d["net_debt_post_issue_cr"]
            if d["net_debt_post_issue_cr"] is None:
                problems.append("debt/cash missing for EV bridge")
        if problems:
            result["scenarios"].append({"name": name, "status": "unavailable", "assumptions": a, "reasons": problems})
            continue
        assert g is not None and m is not None  # guaranteed by the checks above
        rev = d["base_revenue_cr"] * (1 + g / 100)
        ebitda = rev * m / 100
        adj = 1 + a["market_adjustment_pct"] / 100
        steps: dict[str, float | None] = {"revenue_cr": rev, "ebitda_cr": ebitda}
        if method == "pe":
            pat = ebitda * k
            steps["pat_cr"] = pat
            if pat <= 0:
                result["scenarios"].append({"name": name, "status": "unavailable", "assumptions": a,
                                            "reasons": ["scenario earnings are not positive; P/E method not applicable"], "steps": steps})
                continue
            equity = pat * mult * adj
        else:
            if ebitda <= 0:
                result["scenarios"].append({"name": name, "status": "unavailable", "assumptions": a,
                                            "reasons": ["scenario EBITDA is not positive; EV/EBITDA method not applicable"], "steps": steps})
                continue
            ev = ebitda * mult * adj
            steps["enterprise_value_cr"] = ev
            equity = ev - d["net_debt_post_issue_cr"]
        steps["equity_value_cr"] = equity
        if equity <= 0:
            result["scenarios"].append({"name": name, "status": "unavailable", "assumptions": a,
                                        "reasons": ["implied equity value is not positive"], "steps": steps})
            continue
        p = equity * 1e7 / shares
        pat_cr = steps.get("pat_cr")
        steps["eps_inr"] = pat_cr * 1e7 / shares if pat_cr is not None else None
        r = (p - price) / price * 100
        result["scenarios"].append({
            "name": name,
            "status": "ok",
            "assumptions": {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in a.items()},
            "steps": {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in steps.items()},
            "implied_price": round(p, 2),
            "implied_return_pct": round(r, 2),
        })
    result["status"] = "ok" if any(s["status"] == "ok" for s in result["scenarios"]) else "unavailable"
    return result
