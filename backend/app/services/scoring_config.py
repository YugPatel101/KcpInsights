"""Versioned scoring configuration.

Every weight, threshold and rule constant used by ``scoring_engine`` lives here.
The defaults are *educational starting points*: they were chosen to be easy to
explain, NOT estimated from data, and they are not validated predictive coefficients.

Normalisation conventions (see ``normalization.py``):
  * ``higher``:  N = 100 * clip((x - a) / (b - a), 0, 1)
  * ``lower``:   N = 100 * clip((b - x) / (b - a), 0, 1)
  * ``target``:  100 inside [lo, hi]; linear decay to 0 over ``tol_lo`` below / ``tol_hi`` above.

Percentages are expressed in percent units (e.g. 12.5 means 12.5 %).
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

DEFAULT_CONFIG_VERSION = "1.0.0"

DEFAULT_CONFIG: dict[str, Any] = {
    "version": DEFAULT_CONFIG_VERSION,
    "description": (
        "Initial educational defaults. Bounded linear normalisation with documented "
        "thresholds; weights are judgemental, not statistically fitted."
    ),
    # ---------------------------------------------------------------- composite
    "composite": {
        "weights": {"quality": 0.45, "valuation": 0.30, "risk_inverse": 0.25},
        # Formula: S = 0.45 Q + 0.30 V + 0.25 (100 - R_total). No renormalisation.
    },
    # ---------------------------------------------------------------- quality Q
    "quality": {
        "weights": {
            "profitability": 0.25,
            "growth": 0.20,
            "cash_flow": 0.20,
            "balance_sheet": 0.20,
            "revenue_stability": 0.15,
        },
        # Within a component, available sub-metrics are re-weighted among themselves,
        # but only if their share of the component's weight is at least this value.
        "min_submetric_weight_coverage": 0.5,
        "min_periods_for_growth": 2,
        "min_periods_for_stability": 3,
        "components": {
            "profitability": {
                "ebitda_margin": {"weight": 0.35, "direction": "higher", "a": 0.0, "b": 25.0, "unit": "%"},
                "pat_margin": {"weight": 0.25, "direction": "higher", "a": 0.0, "b": 15.0, "unit": "%"},
                "roe": {"weight": 0.20, "direction": "higher", "a": 0.0, "b": 25.0, "unit": "%"},
                "roce": {"weight": 0.20, "direction": "higher", "a": 0.0, "b": 25.0, "unit": "%"},
            },
            "growth": {
                "revenue_cagr": {"weight": 0.50, "direction": "higher", "a": 0.0, "b": 25.0, "unit": "%"},
                "pat_cagr": {"weight": 0.30, "direction": "higher", "a": 0.0, "b": 30.0, "unit": "%"},
                "latest_revenue_growth": {"weight": 0.20, "direction": "higher", "a": 0.0, "b": 25.0, "unit": "%"},
            },
            "cash_flow": {
                # cumulative OCF / cumulative PAT over the window
                "ocf_to_pat": {"weight": 0.40, "direction": "target", "lo": 0.9, "hi": 1.6, "tol_lo": 0.9, "tol_hi": 2.0, "unit": "x"},
                # cumulative (OCF - capex) / cumulative revenue; negative FCF scores 0 below a
                "fcf_margin": {"weight": 0.35, "direction": "higher", "a": -5.0, "b": 10.0, "unit": "%"},
                "positive_ocf_share": {"weight": 0.25, "direction": "higher", "a": 0.5, "b": 1.0, "unit": "share"},
            },
            "balance_sheet": {
                "debt_to_equity": {"weight": 0.40, "direction": "lower", "a": 0.1, "b": 2.0, "unit": "x"},
                "interest_coverage": {"weight": 0.30, "direction": "higher", "a": 1.5, "b": 8.0, "unit": "x"},
                "net_debt_to_ebitda": {"weight": 0.30, "direction": "lower", "a": 0.0, "b": 4.0, "unit": "x"},
            },
            "revenue_stability": {
                # sample standard deviation of YoY revenue growth (pp)
                "revenue_growth_volatility": {"weight": 0.40, "direction": "lower", "a": 3.0, "b": 25.0, "unit": "pp"},
                "positive_growth_share": {"weight": 0.35, "direction": "higher", "a": 0.34, "b": 1.0, "unit": "share"},
                # only used when a verified/imported disclosure exists
                "customer_concentration": {"weight": 0.25, "direction": "lower", "a": 20.0, "b": 80.0, "unit": "%"},
            },
        },
    },
    # ---------------------------------------------------------------- valuation V
    "valuation": {
        # V = 100 * clip((V_high - V_ipo) / (V_high - V_low), 0, 1)
        "low_percentile": 25,
        "high_percentile": 75,
        "min_peers": 3,
        "min_relative_spread": 0.10,  # (high-low)/median below this -> degenerate
        "peer_max_age_days": 180,
        "price_basis": "upper_band",  # or final issue price when known
        # Multiple preference by sector group. The first applicable multiple is used.
        "multiple_preference": {
            "financials": ["pb", "pe"],
            "default": ["pe", "ev_ebitda", "ps"],
        },
        "financial_sectors": ["banking", "nbfc", "financial services", "insurance", "housing finance"],
        # P/S is only used for loss-making companies when explicitly allowed.
        "allow_price_to_sales": True,
    },
    # ---------------------------------------------------------------- risk R_total
    "risk": {
        "weights": {"financial": 0.25, "valuation": 0.20, "governance": 0.20, "market": 0.20, "data_quality": 0.15},
        "min_submetric_weight_coverage": 0.5,
        "levels": {"low_below": 35.0, "high_at_or_above": 60.0},
        "components": {
            # Rule-based distress flags on the latest period. Each flag is 0 or 100.
            "financial": {
                "latest_loss": {"weight": 0.25},
                "negative_ocf_latest": {"weight": 0.25},
                "negative_equity": {"weight": 0.20},
                "interest_cover_below": {"weight": 0.15, "threshold": 1.5},
                "leverage_above": {"weight": 0.15, "threshold": 2.0},
            },
            "valuation": {
                # premium of IPO multiple over peer median; 0 % -> 0 risk, 100 % -> 100 risk
                "premium_to_peer_median": {"weight": 0.70, "a": 0.0, "b": 100.0},
                # basis risk: what multiple had to be used
                "multiple_basis": {"weight": 0.30, "scores": {"pe": 0.0, "pb": 20.0, "ev_ebitda": 35.0, "ps": 75.0}},
            },
            "governance": {
                "confirmed_disclosures": {
                    "weight": 0.50,
                    "severity_points": {"low": 10.0, "medium": 25.0, "high": 45.0},
                    "unresolved_multiplier": 0.5,
                    "cap": 100.0,
                },
                "ofs_share_of_issue": {"weight": 0.25, "a": 30.0, "b": 100.0},
                # lower promoter holding post issue -> higher risk
                "promoter_holding_post": {"weight": 0.25, "a": 75.0, "b": 30.0},
            },
            "market": {
                # configured sector assumption – NOT company-specific evidence
                "sector_cyclicality": {
                    "weight": 0.50,
                    "default": 50.0,
                    "table": {
                        "information technology": 40.0,
                        "fmcg": 30.0,
                        "consumer": 40.0,
                        "healthcare": 35.0,
                        "pharmaceuticals": 40.0,
                        "specialty chemicals": 55.0,
                        "chemicals": 55.0,
                        "capital goods": 55.0,
                        "renewable energy": 55.0,
                        "nbfc": 55.0,
                        "financial services": 50.0,
                        "real estate": 70.0,
                        "metals": 70.0,
                        "auto components": 55.0,
                        "logistics": 50.0,
                        "retail": 50.0,
                    },
                },
                "issue_type_liquidity": {"weight": 0.30, "scores": {"mainboard": 30.0, "sme": 75.0}},
                # smaller issues -> thinner float; 1000 cr -> 0 risk, 50 cr -> 100 risk
                "issue_size": {"weight": 0.20, "a": 1000.0, "b": 50.0},
            },
            "data_quality": {
                # R_d = 100 - evidence coverage C (C counts only verified/imported current inputs)
                "method": "inverse_evidence_coverage",
            },
        },
    },
    # ---------------------------------------------------------------- evidence coverage C
    "evidence": {
        # C = 100 * sum(w_i I_i) / sum(w_i); I_i = 1 when present, valid, current and of an
        # admissible status. Synthetic data never counts.
        "status_weights": {"verified": 1.0, "imported": 1.0, "estimated": 0.0, "synthetic": 0.0, "unavailable": 0.0},
        "financials_max_age_months": 18,
        "inputs": {
            "price_band": 2.0,
            "post_issue_shares": 2.0,
            "issue_size": 1.0,
            "fresh_ofs_split": 1.0,
            "promoter_holding": 0.5,
            "fin_revenue": 2.0,
            "fin_ebitda": 1.5,
            "fin_pat": 2.0,
            "fin_operating_cash_flow": 1.5,
            "fin_total_equity": 1.5,
            "fin_total_debt": 1.0,
            "fin_cash": 0.5,
            "fin_interest_expense": 0.5,
            "fin_capex": 0.5,
            "fin_history_3y": 1.5,
            "peer_set": 2.0,
            "risk_disclosures_reviewed": 1.5,
            "customer_concentration": 0.5,
        },
    },
    # ---------------------------------------------------------------- scenarios
    "scenario": {
        "defaults": {
            "bear": {"growth_delta_pp": -10.0, "margin_delta_pp": -3.0, "multiple_percentile": 25, "market_adjustment_pct": -10.0},
            "base": {"growth_delta_pp": 0.0, "margin_delta_pp": 0.0, "multiple_percentile": 50, "market_adjustment_pct": 0.0},
            "bull": {"growth_delta_pp": 5.0, "margin_delta_pp": 2.0, "multiple_percentile": 75, "market_adjustment_pct": 5.0},
        },
        "base_growth_cap_pct": 40.0,
        "base_growth_floor_pct": -20.0,
    },
    # ---------------------------------------------------------------- listing outcome model
    "listing_model": {
        "classes": {"negative_below_pct": -2.0, "positive_above_pct": 5.0},
        "min_samples": 40,
        "min_class_count": 8,
        "test_fraction": 0.25,
        "validation_fraction": 0.15,
        "walk_forward_folds": 4,
        "bootstrap_iterations": 500,
        "features": [
            "log_issue_size",
            "is_sme",
            "revenue_cagr",
            "pat_margin",
            "debt_to_equity",
            "valuation_premium_pct",
            "ofs_share_pct",
            "subscription_total_at_close",
            "subscription_qib_at_close",
            "days_open_to_listing",
        ],
    },
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

    def _sum_is_one(weights: dict[str, float], where: str) -> None:
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ConfigError(f"{where} weights must sum to 1.0 (got {total:.4f})")
        if any(w < 0 for w in weights.values()):
            raise ConfigError(f"{where} weights must be non-negative")

    for key in ("version", "composite", "quality", "valuation", "risk", "evidence"):
        if key not in config:
            raise ConfigError(f"missing section: {key}")
    _sum_is_one(config["composite"]["weights"], "composite")
    _sum_is_one(config["quality"]["weights"], "quality")
    _sum_is_one(config["risk"]["weights"], "risk")
    for name, comp in config["quality"]["components"].items():
        _sum_is_one({k: v["weight"] for k, v in comp.items()}, f"quality.{name}")
        for metric, spec in comp.items():
            if spec["direction"] in ("higher", "lower") and not spec["a"] < spec["b"]:
                raise ConfigError(f"quality.{name}.{metric}: require a < b")
            if spec["direction"] == "target" and not spec["lo"] <= spec["hi"]:
                raise ConfigError(f"quality.{name}.{metric}: require lo <= hi")
    for name, comp in config["risk"]["components"].items():
        if name == "data_quality":
            continue
        _sum_is_one({k: v["weight"] for k, v in comp.items()}, f"risk.{name}")
    v = config["valuation"]
    if not 0 <= v["low_percentile"] < v["high_percentile"] <= 100:
        raise ConfigError("valuation percentiles must satisfy 0 <= low < high <= 100")
    if v["min_peers"] < 2:
        raise ConfigError("valuation.min_peers must be >= 2")
