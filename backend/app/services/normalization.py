"""Bounded linear normalisation functions.

These map a raw metric onto [0, 100]. They are transparent conventions, not
financial truths; thresholds come from the versioned scoring configuration.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _check(x: float) -> None:
    if x is None or not math.isfinite(x):
        raise ValueError("value must be a finite number")


def normalize_higher(x: float, a: float, b: float) -> float:
    """Higher is better: z = (x - a) / (b - a); N = 100 * clip(z)."""
    _check(x)
    if not a < b:
        raise ValueError("require a < b")
    return 100.0 * clip((x - a) / (b - a))


def normalize_lower(x: float, a: float, b: float) -> float:
    """Lower is better: z = (b - x) / (b - a); N = 100 * clip(z)."""
    _check(x)
    if not a < b:
        raise ValueError("require a < b")
    return 100.0 * clip((b - x) / (b - a))


def normalize_target(x: float, lo: float, hi: float, tol_lo: float, tol_hi: float) -> float:
    """Target range: 100 inside [lo, hi], linear decay to 0 over tol_lo below / tol_hi above."""
    _check(x)
    if lo > hi or tol_lo <= 0 or tol_hi <= 0:
        raise ValueError("require lo <= hi and positive tolerances")
    if lo <= x <= hi:
        return 100.0
    if x < lo:
        return 100.0 * clip(1.0 - (lo - x) / tol_lo)
    return 100.0 * clip(1.0 - (x - hi) / tol_hi)


def normalize_risk(x: float, a: float, b: float) -> float:
    """Risk mapping: 0 risk at ``a`` and 100 risk at ``b`` (a may be greater than b).

    Used for "riskier when larger" (a < b) and "riskier when smaller" (a > b) inputs.
    """
    _check(x)
    if a == b:
        raise ValueError("require a != b")
    return 100.0 * clip((x - a) / (b - a))


def normalize(x: float, spec: dict) -> float:
    direction = spec["direction"]
    if direction == "higher":
        return normalize_higher(x, spec["a"], spec["b"])
    if direction == "lower":
        return normalize_lower(x, spec["a"], spec["b"])
    if direction == "target":
        return normalize_target(x, spec["lo"], spec["hi"], spec["tol_lo"], spec["tol_hi"])
    raise ValueError(f"unknown direction {direction!r}")


def winsorize(values: Sequence[float], lower_pct: float, upper_pct: float) -> list[float]:
    """Clamp values to the [lower_pct, upper_pct] percentiles of the same sample.

    Only apply to a comparable cross-section computed at a single point in time,
    never using information from after the prediction timestamp.
    """
    if not values:
        return []
    lo = percentile(values, lower_pct)
    hi = percentile(values, upper_pct)
    return [min(hi, max(lo, v)) for v in values]


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile (same convention as numpy's default 'linear')."""
    if not values:
        raise ValueError("percentile of empty sequence")
    if not 0 <= pct <= 100:
        raise ValueError("pct must be within [0, 100]")
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    rank = (pct / 100.0) * (len(s) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(s[lo])
    return float(s[lo] + (s[hi] - s[lo]) * (rank - lo))
