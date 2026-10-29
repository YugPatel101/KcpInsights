"""Checks applied to model-generated text before it is shown to users."""
from __future__ import annotations

import json
import re
from typing import Any

_NUM = re.compile(r"(?<![A-Za-z])[-−]?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![A-Za-z])[-−]?\d+(?:\.\d+)?")


def numbers_in_text(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text):
        s = m.group(0).replace(",", "").replace("−", "-")
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def numbers_in_data(data: Any, acc: set[float] | None = None) -> set[float]:
    acc = acc if acc is not None else set()
    if isinstance(data, bool) or data is None:
        return acc
    if isinstance(data, (int, float)):
        acc.add(float(data))
    elif isinstance(data, str):
        acc.update(numbers_in_text(data))
    elif isinstance(data, dict):
        for v in data.values():
            numbers_in_data(v, acc)
    elif isinstance(data, (list, tuple)):
        for v in data:
            numbers_in_data(v, acc)
    return acc


def _matches(n: float, allowed: set[float]) -> bool:
    if abs(n) <= 12 and float(n).is_integer():
        return True  # small counts, list ordinals, section numbers
    if 1990 <= n <= 2100 and float(n).is_integer():
        return True  # years
    for a in allowed:
        for cand in (a, a * 100, a / 100):  # share <-> percent presentations
            if abs(n - cand) <= max(0.051, abs(cand) * 0.006):
                return True
    return False


def unsupported_numbers(text: str, allowed: set[float]) -> list[float]:
    return [n for n in numbers_in_text(text) if not _matches(n, allowed)]


def compact_json(data: Any, limit: int) -> str:
    s = json.dumps(data, default=str, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit] + "…(truncated)"
