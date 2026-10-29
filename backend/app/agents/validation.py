"""Checks applied to model-generated text before it is shown to users."""
from __future__ import annotations

import json
import re
from datetime import date
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


_MONTH = (r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
          r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?")
_DATE = re.compile(
    r"\b(?P<iso>\d{4}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"
    rf"|\b(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}(?:,?\s+(?P<y1>\d{{4}}))?"
    rf"|\b{_MONTH.replace('mon', 'mon2')}\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<y2>\d{{4}}))?",
    re.I)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def dates_in_text(text: str, default_year: int) -> list[tuple[date, int, int]]:
    """Calendar dates written as ISO, "9 November 2026" or "Nov 9, 2026", with their character spans."""
    out = []
    for m in _DATE.finditer(text):
        try:
            if m.group("iso"):
                d = date.fromisoformat(m.group("iso"))
            else:
                mon = (m.group("mon") or m.group("mon2")).lower()[:3]
                d = date(int(m.group("y1") or m.group("y2") or default_year), _MONTHS.index(mon) + 1, int(m.group("d1") or m.group("d2")))
        except ValueError:
            continue
        out.append((d, m.start(), m.end()))
    return out


def _without_dates(text: str) -> str:
    for _d, a, b in reversed(dates_in_text(text, 2000)):
        text = text[:a] + " " * (b - a) + text[b:]
    return text


def unsupported_numbers(text: str, allowed: set[float]) -> list[float]:
    """Numbers in text not found in the tool data (dates are checked separately by ``date_problems``)."""
    return [n for n in numbers_in_text(_without_dates(text)) if not _matches(n, allowed)]


# Event words near a date must match what that date is in the data (e.g. an allotment date called "opens").
_ROLE_WORDS = {
    "open": re.compile(r"\b(?:open|start|begin|commenc)", re.I),
    "close": re.compile(r"\b(?:clos|ends?\b|ending\b)", re.I),
    "allotment": re.compile(r"\ballot", re.I),
    "refund": re.compile(r"\brefund", re.I),
    "demat_credit": re.compile(r"\b(?:demat|credit)", re.I),
    "listing": re.compile(r"\blist", re.I),
}
_CLAUSE = re.compile(r"[.;,!?](?:\s|$)|\band\b|\bwhile\b|\bwith\b|\bthen\b", re.I)
_ROLE_FIELDS = {"open_date": "open", "close_date": "close", "allotment_date": "allotment", "refund_date": "refund",
                "demat_credit_date": "demat_credit", "listing_date": "listing"}
_EVENT_ROLES = {"opens": "open", "closes": "close", "allotment": "allotment", "lists": "listing", "open": "open", "close": "close",
                "refund": "refund", "demat_credit": "demat_credit", "listing": "listing"}


def date_roles(data: Any, roles: dict[date, set[str]] | None = None) -> dict[date, set[str]]:
    """Every ISO date in tool data, with the event roles it plays (empty set = a date with no event meaning, e.g. "as of")."""
    roles = roles if roles is not None else {}

    def parse(v: Any) -> date | None:
        if isinstance(v, str) and len(v) >= 10:
            try:
                return date.fromisoformat(v[:10])
            except ValueError:
                return None
        return None

    if isinstance(data, dict):
        role = _EVENT_ROLES.get(str(data.get("key") or data.get("event") or "")) if "date" in data else None
        for k, v in data.items():
            d = parse(v)
            if d is not None:
                r = roles.setdefault(d, set())
                if k in _ROLE_FIELDS:
                    r.add(_ROLE_FIELDS[k])
                elif k == "date" and role:
                    r.add(role)
            elif k == "estimated_fields" and isinstance(v, dict):
                for f, e in v.items():
                    d = parse((e or {}).get("value"))
                    if d is not None:
                        roles.setdefault(d, set()).update({_ROLE_FIELDS[f]} if f in _ROLE_FIELDS else set())
            else:
                date_roles(v, roles)
    elif isinstance(data, (list, tuple)):
        for v in data:
            date_roles(v, roles)
    return roles


def date_problems(text: str, roles: dict[date, set[str]], default_year: int) -> list[str]:
    """Dates that are not in the data, or that are described as a different event than the data says."""
    problems = []
    for d, a, b in dates_in_text(text, default_year):
        if d not in roles:
            problems.append(f"{d.isoformat()} is not in the tool results")
            continue
        if not roles[d]:
            continue
        start = max((m.end() for m in _CLAUSE.finditer(text, 0, a)), default=0)
        nxt = _CLAUSE.search(text, b)
        before, after = text[start:a], text[b: nxt.start() if nxt else len(text)]
        hits = [(m.start(), r) for r, rx in _ROLE_WORDS.items() for m in rx.finditer(before)]
        if not hits:
            hits = [(-m.start(), r) for r, rx in _ROLE_WORDS.items() for m in rx.finditer(after)]
        if hits:
            said = max(hits)[1]  # the event word closest to the date
            if said not in roles[d]:
                problems.append(f"{d.isoformat()} described as {said}, but it is the {'/'.join(sorted(roles[d]))} date")
    return problems


def unit_values(data: Any, multiples: set[float] | None = None, percents: set[float] | None = None,
                _ctx: str | None = None) -> tuple[set[float], set[float]]:
    """Numeric values that are subscription multiples ("x") and percentages ("%") in tool data."""
    multiples = multiples if multiples is not None else set()
    percents = percents if percents is not None else set()
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        (multiples if _ctx == "x" else percents if _ctx == "%" else set()).add(float(data))
    elif isinstance(data, dict):
        for k, v in data.items():
            key = str(k).lower()
            ctx = "x" if "subscri" in key else "%" if ("pct" in key or "percent" in key) else _ctx
            unit_values(v, multiples, percents, ctx)
    elif isinstance(data, (list, tuple)):
        for v in data:
            unit_values(v, multiples, percents, _ctx)
    return multiples, percents


_PCT_AFTER = re.compile(r"\s*(?:%|per\s*cent|percent)", re.I)
_X_AFTER = re.compile(r"\s*(?:x\b|times\b)", re.I)


def unit_problems(text: str, multiples: set[float], percents: set[float]) -> list[str]:
    """A subscription multiple written as a percentage, or a percentage written as a multiple."""
    def near(n: float, vals: set[float]) -> bool:
        return any(abs(n - v) <= max(0.051, abs(v) * 0.006) for v in vals)

    out = []
    clean = _without_dates(text)
    for m in _NUM.finditer(clean):
        n = float(m.group(0).replace(",", "").replace("−", "-"))
        if _PCT_AFTER.match(clean, m.end()) and near(n, multiples) and not near(n, percents):
            out.append(f"{m.group(0)} is a subscription multiple (times), not a percentage")
        elif _X_AFTER.match(clean, m.end()) and near(n, percents) and not near(n, multiples):
            out.append(f"{m.group(0)} is a percentage, not a multiple")
    return out


_ADVICE = re.compile(r"\b(?:you should|we recommend|i recommend|recommended to (?:apply|buy|subscribe)|(?:should|must) (?:apply|buy|sell|subscribe)"
                     r"|consider (?:applying|buying|subscribing)|good (?:investment|buy)|worth (?:applying|buying|subscribing)"
                     r"|guaranteed|sure-shot|chance of (?:listing )?gains?|undervalued|overvalued|bargain)\b", re.I)


def advice_problems(text: str) -> list[str]:
    """Investment advice or probability claims, which the assistant must never make."""
    return [f"advice-like wording {m.group(0)!r}" for m in _ADVICE.finditer(text)]


_QUALIFIER = re.compile(r"estimat|expected|approx|indicative|tentative|projected|likely", re.I)
_SENTENCE = re.compile(r"[.;!?](?:\s|$)")
_UNIT = re.compile(r"\s*(?:crore|cr\b\.?|lakh)", re.I)


def label_estimates(text: str, numbers: set[float], dates: set[date]) -> tuple[str, int]:
    """Mark estimated values the text states without a qualifier nearby.

    Model output is not trusted to carry the label; returns the text and the number of labels added.
    """
    spans: list[tuple[int, str]] = []

    def qualified(start: int, end: int) -> bool:  # a qualifier within the same sentence, near the value
        before = _SENTENCE.split(text[max(0, start - 50): start])[-1]
        after = _SENTENCE.split(text[end: end + 40])[0]
        return bool(_QUALIFIER.search(before + text[start:end] + after))

    for m in _NUM.finditer(_without_dates(text)):
        n = float(m.group(0).replace(",", "").replace("−", "-"))
        if (abs(n) <= 31 and n.is_integer()) or (1990 <= n <= 2100 and n.is_integer()):
            continue  # day numbers, counts and years are handled as dates or ignored
        if any(abs(n - e) <= max(0.051, abs(e) * 0.006) for e in numbers) and not qualified(m.start(), m.end()):
            unit = _UNIT.match(text, m.end())
            spans.append((unit.end() if unit else m.end(), " (estimated)"))
    year = min(dates).year if dates else 2000
    date_spans = dates_in_text(text, year)
    for d, a, b in date_spans:
        if d in dates and not qualified(a, b):
            spans.append((b, " (expected)"))
    for pos, label in sorted(set(spans), reverse=True):
        text = text[:pos] + label + text[pos:]
    return text, len(set(spans))


def compact_json(data: Any, limit: int) -> str:
    s = json.dumps(data, default=str, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit] + "…(truncated)"
