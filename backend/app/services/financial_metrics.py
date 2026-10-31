"""Units and field names shared by financial-statement importers.

All ratio and score formulas live in ``quant_engine`` (single implementation).
"""
from __future__ import annotations

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


# Statement fields accepted by CSV/JSON imports (amounts; converted to INR crore).
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
    "other_income",
    "depreciation",
    "pbt",
    "inventory",
)
