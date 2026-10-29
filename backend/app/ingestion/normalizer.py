"""Parsing and normalisation of raw exchange values.

Every parser returns ``None`` when a value is absent or cannot be parsed unambiguously —
callers then mark the field unavailable instead of guessing.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_date(value: object) -> date | None:
    """'29-Oct-2026', '23-OCT-2026', '2026-10-28', '28-10-2026' -> date."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v or v in ("-", "NA", "N.A."):
        return None
    m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", v)
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        return date(int(m.group(3)), mon, int(m.group(1))) if mon else None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", v)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def parse_update_time(value: object) -> datetime | None:
    """'Updated as on 29-Oct-2026 17:00:00' -> naive IST datetime."""
    if not isinstance(value, str):
        return None
    m = re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?", value)
    if not m:
        return None
    d = parse_date(m.group(1))
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3)), int(m.group(4) or 0))


def parse_number(value: object) -> float | None:
    """'1.6533012E7', '1,65,32,880', '  1119', '6.55' -> float; '' / None -> None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    v = value.strip().replace(",", "")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_price_band(value: object) -> tuple[float | None, float | None]:
    """'Rs.78 to Rs.82' / 'Rs. 1065 to Rs. 1119 per Equity Share' / 'Rs.150' -> (low, high)."""
    if not isinstance(value, str):
        return None, None
    nums = [float(x.replace(",", "")) for x in re.findall(r"(\d[\d,]*(?:\.\d+)?)", value)]
    if len(nums) >= 2:
        lo, hi = nums[0], nums[1]
        return (lo, hi) if lo <= hi else (None, None)
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def parse_first_int(value: object) -> int | None:
    """'182 Equity Shares and in multiples thereof' -> 182."""
    if not isinstance(value, str):
        return None
    m = re.search(r"(\d[\d,]*)", value)
    return int(m.group(1).replace(",", "")) if m else None


def parse_rupees_per_share(value: object) -> float | None:
    """'Rs. 10 per Equity Share' -> 10.0."""
    if not isinstance(value, str):
        return None
    m = re.search(r"Rs\.?\s*(\d+(?:\.\d+)?)", value, re.IGNORECASE)
    return float(m.group(1)) if m else None


_UNIT_TO_CRORE = {"million": 0.1, "mn": 0.1, "crore": 1.0, "crores": 1.0, "cr": 1.0, "lakh": 0.01, "lakhs": 0.01, "billion": 100.0}


_AMOUNT = r"Rs\.? ?([\d,]+(?:\.\d+)?) ?(million|mn|crores?|cr|lakhs?|billion)"
_SHARES = r"([\d,]+) ?equity shares"


def parse_issue_components(text: object) -> dict[str, float] | None:
    """Fresh-issue and offer-for-sale components from the NSE issue-size sentence.

    Text in parentheses (anchor, market-maker, employee or shareholder portions) describes
    portions *included* in the totals, so it is removed before parsing. Returns a dict with
    any of ``fresh_cr``, ``fresh_shares``, ``ofs_cr``, ``ofs_shares``, or None when the
    sentence does not have a recognised structure.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    t = re.sub(r"\s+", " ", text)
    for _ in range(3):  # strip (possibly nested) parentheticals
        t = re.sub(r"\([^()]*\)", " ", t)
    low = t.lower()
    i_fresh, i_ofs = low.find("fresh issue"), low.find("offer for sale")
    if i_fresh < 0 and i_ofs < 0:
        return None
    parts: dict[str, str] = {}
    if i_fresh >= 0:
        parts["fresh"] = low[i_fresh: i_ofs if i_ofs > i_fresh else len(low)]
    if i_ofs >= 0:
        parts["ofs"] = low[i_ofs: i_fresh if i_fresh > i_ofs else len(low)]
    out: dict[str, float] = {}
    for name, seg in parts.items():
        amounts = re.findall(_AMOUNT, seg, re.IGNORECASE)
        shares = re.findall(_SHARES, seg, re.IGNORECASE)
        if len(amounts) == 1 and not shares:
            num, unit = amounts[0]
            out[f"{name}_cr"] = float(num.replace(",", "")) * _UNIT_TO_CRORE[unit.lower()]
        elif len(shares) == 1 and not amounts:
            out[f"{name}_shares"] = float(shares[0].replace(",", ""))
        else:
            return None  # ambiguous: several amounts or both units in one component
    return out


def strip_html(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    v = re.sub(r"<[^>]+>", " ", value).replace('"', "").strip()
    return re.sub(r"\s+", " ", v) or None


def first_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    m = re.search(r"https://[^\s\"'<>]+", value)
    return m.group(0) if m else None


SME_SERIES = {"SME", "SM", "ST", "SZ"}
EQUITY_SERIES = {"EQ", "BE", "BZ"} | SME_SERIES


def issue_type_for_series(series: object) -> str | None:
    s = str(series or "").strip().upper()
    if s in SME_SERIES:
        return "sme"
    if s in {"EQ", "BE", "BZ"}:
        return "mainboard"
    return None


_CORP_SUFFIX = re.compile(r"\b(limited|ltd|private|pvt|the)\b", re.IGNORECASE)


def normalize_company_name(name: str) -> str:
    n = _CORP_SUFFIX.sub(" ", name.lower())
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def subscription_category(label: str, sr_no: object) -> str | None:
    """Map NSE category rows to KcpInsights categories; sub-rows return None."""
    s = str(sr_no or "").strip()
    lab = label.lower()
    if lab.startswith("total") or (sr_no is None and "total" in lab):
        return "total"
    if s == "1" and "qualified institutional" in lab:
        return "qib"
    if s == "2" and "non institutional" in lab:
        return "nii"
    if s == "3" and "retail" in lab:
        return "retail"
    if "employee" in lab and "." not in s and "(" not in s:
        return "employee"
    if "shareholder" in lab and "." not in s and "(" not in s:
        return "shareholder"
    return None


def add_working_days(d: date, n: int) -> date:
    """Add n working days, skipping weekends only (exchange holidays are not known here)."""
    out = d
    while n > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:
            n -= 1
    return out
