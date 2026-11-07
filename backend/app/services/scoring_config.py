"""Versioned configuration of the quantitative IPO scoring model (v2.1).

Every weight, reference range and threshold used by ``quant_engine`` lives here, so the model can
be changed without touching code (new versions are stored in ``scoring_config_versions``).

The defaults are *educational starting points* chosen to be explainable, not fitted to data.
They are not validated predictors of listing gains or returns.

Normalisation of one metric x to a 0–100 score (higher score = better characteristic):

* ``linear``: S = 100 · clip((x − zero) / (full − zero), 0, 1). ``zero`` is the value scoring 0,
  ``full`` the value scoring 100; when zero > full, lower values score higher (e.g. debt/equity).
* ``band``: S = 100 inside [lo, hi]; linear decline to 0 at ``zero_low`` below and ``zero_high``
  above (e.g. a current ratio that is too low *or* idle-cash high).

Percentages are in percent units (12.5 means 12.5 %).
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

DEFAULT_CONFIG_VERSION = "2.1.0"
# Earlier built-in defaults: an active row with one of these versions is upgraded automatically.
# Configurations created by an administrator (any other version) are never replaced.
SUPERSEDED_DEFAULT_VERSIONS = {"1.0.0", "2.0.0", "2.0.1"}

_LENDER_NA = ["roce", "ebitda_margin", "operating_margin", "gross_margin", "current_ratio", "quick_ratio", "cash_ratio", "debt_to_equity",
              "interest_coverage", "debt_to_ebitda", "debt_to_assets", "ev_ebitda", "enterprise_value", "ocf_to_pat", "fcf", "fcf_margin",
              "cash_conversion", "cash_flow_consistency", "capex_intensity", "inventory_days", "receivable_days", "price_to_sales"]
_LENDER_REASONS = {
    "debt_to_equity": "borrowing is a lender's raw material; leverage is judged through capital adequacy instead",
    "interest_coverage": "interest is a lender's cost of goods, not a financing charge",
    "current_ratio": "lenders do not classify assets and liabilities as current and non-current",
    "ebitda_margin": "EBITDA is not meaningful when interest is an operating cost",
    "roce": "capital employed is not meaningful for a balance sheet made of loans",
    "ev_ebitda": "enterprise value and EBITDA are not meaningful for lenders",
    "ocf_to_pat": "operating cash flow of a lender includes loan disbursements and repayments",
    "cash_flow": "operating cash flow of a lender includes loan disbursements and repayments",
    "leverage": "borrowing is a lender's raw material; leverage is judged through capital adequacy instead",
    "cash_flow_weakness": "operating cash flow of a lender includes loan disbursements and repayments",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": DEFAULT_CONFIG_VERSION,
    "description": (
        "Fundamental score Q = 0.25·Profitability + 0.25·Growth + 0.20·Financial health + 0.15·Cash flow "
        "+ 0.15·Valuation, with a separate risk score. Educational defaults; weights are judgemental."
    ),
    "weights": {
        # Rationale: earnings quality and growth carry most of the information in restated
        # financials (0.25 each); balance-sheet strength next (0.20); cash flow and valuation
        # are noisier for young companies and pre-pricing issues (0.15 each).
        "overall": {"profitability": 0.25, "growth": 0.25, "financial_health": 0.20, "cash_flow": 0.15, "valuation": 0.15},
        "profitability": {"roe": 0.30, "roce": 0.30, "net_margin": 0.20, "ebitda_margin": 0.20},
        "growth": {"revenue_growth": 0.40, "pat_growth": 0.35, "growth_consistency": 0.25},
        "financial_health": {"current_ratio": 0.30, "debt_to_equity": 0.35, "interest_coverage": 0.35},
        "cash_flow": {"ocf_to_pat": 0.40, "fcf": 0.35, "cash_flow_consistency": 0.25},
        "valuation": {"pe": 0.40, "pb": 0.30, "ev_ebitda": 0.30},
        "risk": {
            "leverage": 0.20, "profitability_deterioration": 0.15, "cash_flow_weakness": 0.15, "valuation": 0.10,
            "customer_concentration": 0.10, "contingent_liabilities": 0.10, "auditor_qualifications": 0.05,
            "governance": 0.05, "data_quality": 0.10,
        },
    },
    "ranges": {
        # profitability (%)
        "roe": {"kind": "linear", "zero": 0.0, "full": 25.0},
        "roce": {"kind": "linear", "zero": 0.0, "full": 30.0},
        "roa": {"kind": "linear", "zero": 0.0, "full": 12.0},
        "net_margin": {"kind": "linear", "zero": 0.0, "full": 15.0},
        "ebitda_margin": {"kind": "linear", "zero": 0.0, "full": 25.0},
        # growth (% a year) and consistency
        "revenue_growth": {"kind": "linear", "zero": -5.0, "full": 25.0},
        "pat_growth": {"kind": "linear", "zero": -10.0, "full": 30.0},
        "growth_volatility_pp": {"kind": "linear", "zero": 30.0, "full": 5.0},
        # financial health
        "current_ratio": {"kind": "band", "lo": 1.2, "hi": 3.0, "zero_low": 0.5, "zero_high": 6.0},
        "debt_to_equity": {"kind": "linear", "zero": 2.0, "full": 0.0},
        "interest_coverage": {"kind": "linear", "zero": 1.0, "full": 8.0},
        # cash flow
        "ocf_to_pat": {"kind": "linear", "zero": 0.0, "full": 1.0},
        "fcf_margin": {"kind": "linear", "zero": -10.0, "full": 10.0},
        # valuation: premium of the IPO multiple over the peer median (%), else absolute multiples
        "relative_premium": {"kind": "linear", "zero": 60.0, "full": -40.0},
        "pe_absolute": {"kind": "linear", "zero": 60.0, "full": 10.0},
        "pb_absolute": {"kind": "linear", "zero": 8.0, "full": 1.0},
        "ev_ebitda_absolute": {"kind": "linear", "zero": 30.0, "full": 6.0},
    },
    # Risk points (0 = low risk, 100 = high risk) per component input
    "risk_ranges": {
        "debt_to_equity": {"kind": "linear", "zero": 0.0, "full": 2.5},
        "debt_to_ebitda": {"kind": "linear", "zero": 0.0, "full": 5.0},
        "net_margin_drop_pp": {"kind": "linear", "zero": 0.0, "full": 5.0},
        "pat_decline_pct": {"kind": "linear", "zero": 0.0, "full": 30.0},
        "ocf_to_pat": {"kind": "linear", "zero": 1.0, "full": 0.0},
        "pe_premium_pct": {"kind": "linear", "zero": 0.0, "full": 100.0},
        "pe_absolute": {"kind": "linear", "zero": 20.0, "full": 80.0},
        "customer_concentration_pct": {"kind": "linear", "zero": 20.0, "full": 80.0},
        "contingent_to_net_worth_pct": {"kind": "linear", "zero": 0.0, "full": 50.0},
    },
    "coverage": {
        "component_min": 0.5,  # share of a component's weight that must be computable
        "overall_min": 0.85,  # share of the overall weight that must be computable to issue Q
        "required_components": ["profitability", "growth", "financial_health"],
        "min_annual_periods": 2,
    },
    "peers": {"min_peers": 2},
    # Industry analysis profiles (the metric-applicability registry). The issuer's profile comes from the industry
    # classifier (financials.industry). A ratio listed under "not_applicable" is shown for reference but never scored and
    # never counted as missing; a profile may replace a component's weights and reference ranges.
    "profiles": {
        "general": {"label": "General", "not_applicable": []},
        "manufacturing": {"label": "Manufacturing", "not_applicable": []},
        "technology": {
            "label": "Technology & internet", "not_applicable": ["gross_margin", "inventory_days"],
            "reasons": {"gross_margin": "software and internet businesses consume few raw materials",
                        "inventory_days": "software and internet businesses hold little or no inventory"},
            "ranges": {"ebitda_margin": {"kind": "linear", "zero": 0.0, "full": 30.0}},
        },
        "infrastructure": {"label": "Infrastructure & utilities", "not_applicable": ["gross_margin"],
                           "reasons": {"gross_margin": "project costs are not reported as materials consumed"}},
        "real_estate": {
            "label": "Real estate", "not_applicable": ["inventory_days", "receivable_days", "current_ratio", "gross_margin"],
            "reasons": {"inventory_days": "inventory is land and projects under development, not stock in trade",
                        "receivable_days": "revenue is recognised on project completion; receivables do not track sales",
                        "current_ratio": "projects under development make current assets structurally large",
                        "gross_margin": "construction costs are not reported as materials consumed"},
        },
        "lender": {
            "label": "Lenders (banks, NBFCs)", "not_applicable": _LENDER_NA, "reasons": _LENDER_REASONS,
            "not_applicable_components": ["cash_flow"], "not_applicable_risk": ["leverage", "cash_flow_weakness"],
            "weights": {"profitability": {"roe": 0.40, "roa": 0.40, "net_margin": 0.20},
                        "financial_health": {"gnpa_pct": 0.35, "nnpa_pct": 0.25, "crar_pct": 0.40},
                        "valuation": {"pe": 0.50, "pb": 0.50}},
            "ranges": {"roe": {"kind": "linear", "zero": 0.0, "full": 18.0}, "roa": {"kind": "linear", "zero": 0.0, "full": 2.5},
                       "net_margin": {"kind": "linear", "zero": 0.0, "full": 25.0}},
        },
        "insurer": {
            "label": "Insurers", "not_applicable": _LENDER_NA, "reasons": _LENDER_REASONS,
            "not_applicable_components": ["cash_flow"], "not_applicable_risk": ["leverage", "cash_flow_weakness"],
            "weights": {"profitability": {"roe": 0.50, "roa": 0.25, "net_margin": 0.25},
                        "financial_health": {"solvency_ratio": 1.0},
                        "valuation": {"pe": 0.50, "pb": 0.50}},
            "ranges": {"roe": {"kind": "linear", "zero": 0.0, "full": 18.0}, "roa": {"kind": "linear", "zero": 0.0, "full": 2.0}},
        },
    },
    # Statuses whose statement periods feed scores. "extracted" (read from a document but not confirmed by an
    # accounting check) and "requires_review" (a check failed) are shown but never scored.
    "usable_statuses": ["verified", "imported", "estimated", "synthetic"],
    "classification": [
        [80, "Strong financial characteristics"],
        [65, "Relatively positive financial characteristics"],
        [50, "Mixed financial characteristics"],
        [35, "Weak financial characteristics"],
        [0, "Significant financial concerns"],
    ],
    "risk_levels": [[70, "high"], [50, "elevated"], [30, "moderate"], [0, "low"]],
}


def config_fingerprint(config: dict[str, Any]) -> str:
    """Stable hash of a configuration (used to detect edits under one version label)."""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def get_default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


class ConfigError(ValueError):
    pass


def validate_config(config: dict[str, Any]) -> None:
    """Sanity-check a configuration before it is activated."""
    for key in ("version", "weights", "ranges", "risk_ranges", "coverage", "classification", "risk_levels"):
        if key not in config:
            raise ConfigError(f"missing section: {key}")
    for group, weights in config["weights"].items():
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ConfigError(f"weights.{group} must sum to 1.0 (got {total:.4f})")
        if any(w < 0 for w in weights.values()):
            raise ConfigError(f"weights.{group} must be non-negative")
    for name in ("profitability", "growth", "financial_health", "cash_flow", "valuation"):
        if name not in config["weights"]["overall"]:
            raise ConfigError(f"weights.overall is missing {name}")
    for section in ("ranges", "risk_ranges"):
        for name, spec in config[section].items():
            if spec.get("kind") == "linear":
                if spec["zero"] == spec["full"]:
                    raise ConfigError(f"{section}.{name}: zero and full must differ")
            elif spec.get("kind") == "band":
                if not spec["zero_low"] < spec["lo"] <= spec["hi"] < spec["zero_high"]:
                    raise ConfigError(f"{section}.{name}: require zero_low < lo <= hi < zero_high")
            else:
                raise ConfigError(f"{section}.{name}: unknown kind {spec.get('kind')!r}")
    cov = config["coverage"]
    if not 0 < cov["component_min"] <= 1 or not 0 < cov["overall_min"] <= 1:
        raise ConfigError("coverage thresholds must be in (0, 1]")
    if config["peers"]["min_peers"] < 2:
        raise ConfigError("peers.min_peers must be >= 2")
    for pname, prof in (config.get("profiles") or {}).items():
        for group, weights in (prof.get("weights") or {}).items():
            if group not in config["weights"]:
                raise ConfigError(f"profiles.{pname}.weights.{group}: unknown component")
            if abs(sum(weights.values()) - 1.0) > 1e-6:
                raise ConfigError(f"profiles.{pname}.weights.{group} must sum to 1.0")
        for comp in prof.get("not_applicable_components", []):
            if comp not in config["weights"]["overall"]:
                raise ConfigError(f"profiles.{pname}: unknown component {comp!r}")
    bounds = [b for b, _ in config["classification"]]
    if bounds != sorted(bounds, reverse=True) or bounds[-1] != 0:
        raise ConfigError("classification bounds must be descending and end at 0")
