"""Extract restated financial statements from an Indian offer document (RHP/DRHP/prospectus).

Approach (no model, no paid service):

1. Find pages whose heading names a balance sheet ("statement of assets and liabilities"), a
   profit and loss statement or a cash flow statement.
2. Rebuild rows from word positions (``pdf_tables``), read the reporting period of every figure
   column from the column header, and the unit ("₹ in million", "₹ in lakhs", ...) from the page.
3. Map row labels to standard fields with documented patterns; keep the label, printed text and
   page of every figure.
4. Reconcile: assets = equity + liabilities, assets = current + non-current, PBT − tax = PAT,
   total income = revenue + other income. A failed check marks that period "requires review";
   such figures are stored but never used in scores.

Amounts are normalised to INR crore (per-share figures stay in INR). Consolidated and standalone
statements are kept apart and never combined.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.financials.pdf_tables import Row, align, column_centres, header_text_by_column, is_year_row, merge_split_rows, page_rows

PARSER_VERSION = "1.5"

UNIT_TO_CRORE = {"million": 0.1, "lakh": 0.01, "crore": 1.0, "thousand": 1e-4, "billion": 100.0, "rupee": 1e-7}
_UNIT_RE = re.compile(
    r"(?:(?:₹|rs\.?|inr|rupees)\s*(?:in\s*)?|in\s*(?:₹|rs\.?|inr)\s*|amount[s]?\s*(?:in\s*)?(?:₹|rs\.?|inr)?\s*(?:in\s*)?)"
    r"(million|mn|lakhs?|lacs?|crores?|cr\b|thousands?|billion)", re.I)

TITLES = {
    "bs": re.compile(r"statement of assets (and|&) liabilities|balance sheet", re.I),
    "pl": re.compile(r"statement of profit (and|&) loss|profit (and|&) loss (statement|account)", re.I),
    "cf": re.compile(r"cash ?flow statement|statement of cash ?flows?", re.I),
}
REQUIRED = {"bs": ("total_assets",), "pl": ("revenue", "pat"), "cf": ("operating_cash_flow",)}

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# (field, pattern on the normalised label, statement kind). Order matters: first match wins.
PATTERNS: list[tuple[str, str, str]] = [
    # balance sheet totals
    ("total_equity_and_liabilities", r"^total (equity|equities) (and|&) liabilities|^total liabilities (and|&) equity", "bs"),
    ("total_assets", r"^total assets", "bs"),
    ("non_current_assets", r"^total non[- ]?current assets", "bs"),
    ("current_assets", r"^total current assets", "bs"),
    ("non_current_liabilities", r"^total non[- ]?current liabilities", "bs"),
    ("current_liabilities", r"^total current liabilities", "bs"),
    ("total_liabilities", r"^total liabilities$", "bs"),
    ("total_equity", r"^total equity( attributable.*)?$|^total shareholders'? (funds|equity)|^net worth$|^total equity \(", "bs"),
    ("share_capital", r"^(equity )?share capital", "bs"),
    ("other_equity", r"^other equity|^reserves (and|&) surplus", "bs"),
    ("inventory", r"^inventor(y|ies)", "bs"),
    ("trade_receivables", r"^trade receivables", "bs"),
    ("cash_and_equivalents", r"^cash and cash equivalents|^cash and bank balances", "bs"),
    # profit and loss
    ("revenue", r"^revenue from operations?|^income from operations?", "pl"),
    ("other_income", r"^other income", "pl"),
    ("total_income", r"^total income|^total revenue", "pl"),
    ("cost_of_materials", r"^cost of (raw )?materials? consumed", "pl"),
    ("employee_expenses", r"^employee benefits? expenses?|^employee (benefit )?(cost|expenses?)", "pl"),
    ("finance_costs", r"^finance costs?|^interest (and finance charges|expenses?|costs?)", "pl"),
    ("depreciation", r"^depreciation", "pl"),
    ("other_expenses", r"^other expenses", "pl"),
    ("total_expenses", r"^total expenses", "pl"),
    ("pbt", r"^(restated )?(net )?(profit|loss|profit ?/ ?\(loss\)|\(loss\) ?/ ?profit) before tax", "pl"),
    ("pbt_pre_exceptional", r"^(restated )?(profit|loss|profit ?/ ?\(loss\)) before exceptional", "pl"),
    ("tax_expense", r"^total tax expenses?|^tax expenses? total|^total tax$|^total income tax expenses?|^income tax expenses?$", "pl"),
    ("pat", r"^(restated )?(net )?(profit|loss|profit ?/ ?\(loss\)|\(loss\) ?/ ?profit) (for|after tax)(?!.*comprehensive)", "pl"),
    ("eps_basic", r"^basic\b|^earnings per (equity )?share.*basic", "pl"),
    ("eps_diluted", r"^diluted\b|^earnings per (equity )?share.*diluted", "pl"),
    # cash flow
    ("operating_cash_flow", r"^net cash.*operating activit", "cf"),
    ("pbt_cf", r"^(restated )?(net )?(profit|loss|profit ?/ ?\(loss\)) before (income )?(tax|taxation)", "cf"),
    ("investing_cash_flow", r"^net cash.*invest(ing|ment) activit", "cf"),
    ("financing_cash_flow", r"^net cash.*financing activit", "cf"),
]
_COMPILED = [(f, re.compile(p), k) for f, p, k in PATTERNS]
# fields summed over every matching row
_CAPEX = re.compile(r"^(purchase|acquisition|payment)s? (of|for|towards) (property|capital|fixed|tangible|intangible|ppe|plant)")
_LEASE = re.compile(r"^lease liabilit")
_BORROW = re.compile(r"^(long[- ]term |short[- ]term )?borrowings")
_CUR_MATURITY = re.compile(r"^current maturities of long[- ]term (borrowings|debt)")
PER_SHARE = {"eps_basic", "eps_diluted"}


@dataclass
class Period:
    column: int
    end: date
    months: int
    label: str


@dataclass
class Figure:
    field: str
    value: float | None  # INR crore (per-share fields: INR)
    raw_text: str
    raw_label: str
    page: int
    unit: str


@dataclass
class StatementTable:
    kind: str  # bs | pl | cf
    page: int
    basis: str  # consolidated | standalone | unknown
    unit: str | None
    periods: list[Period]
    figures: dict[tuple[str, int], Figure] = field(default_factory=dict)  # (field, column) -> figure
    title: str = ""
    warnings: list[str] = field(default_factory=list)
    ncols: int = 0
    borrowed_periods: bool = False

    def fields(self) -> set[str]:
        return {f for f, _ in self.figures}


@dataclass
class PeriodStatement:
    """All figures of one reporting period on one basis, merged across statements."""

    basis: str
    end: date
    months: int
    label: str
    figures: dict[str, Figure] = field(default_factory=dict)
    derived: dict[str, tuple[float, str]] = field(default_factory=dict)  # field -> (value, formula)
    checks: list[dict[str, Any]] = field(default_factory=list)
    validation_status: str = "not_checked"

    def get(self, f: str) -> float | None:
        if f in self.figures:
            return self.figures[f].value
        if f in self.derived:
            return self.derived[f][0]
        return None


@dataclass
class ExtractionResult:
    status: str  # extracted | partial | not_found
    pages_scanned: int
    tables: list[StatementTable]
    periods: list[PeriodStatement]
    warnings: list[str]

    def summary(self) -> list[dict[str, Any]]:
        return [{"kind": t.kind, "page": t.page, "basis": t.basis, "unit": t.unit, "title": t.title,
                 "periods": [p.end.isoformat() for p in t.periods], "fields": sorted(t.fields())} for t in self.tables]


# ---------------------------------------------------------------------------- helpers
def norm_label(s: str) -> str:
    s = s.lower().replace("’", "'").replace("`", "'")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[|\[\]{}_~]+\s*", "", s)  # table rules read as characters on OCR'd pages
    s = re.sub(r"(\s)[|\[\]{}]+\s*", r"\1", s)
    for _ in range(3):  # leading enumerators: "a)", "(ii)", "1.", "A.", "I", "ii)", "13 " ...
        s = re.sub(r"^(\(?([a-z]|[ivx]{1,4}|\d{1,2})[.)]|[ivx]{1,4}(?=\s)|\d{1,2}(?=\s+[a-z]))\s*", "", s).strip()
    for _ in range(3):  # trailing formula tags: "(i)", "(a+b)", "c=(a+b)", "(ii)"
        s = re.sub(r"\s*([a-z]\s*=\s*)?\(([a-z0-9+\-\s]|[ivx])+\)\s*$", "", s).strip()
    return s


def detect_unit(text: str) -> str | None:
    m = _UNIT_RE.search(text)
    if not m:
        return None
    u = m.group(1).lower().rstrip(".")
    if u in ("mn", "million"):
        return "million"
    if u.startswith(("lakh", "lac")):
        return "lakh"
    if u.startswith("cr"):
        return "crore"
    if u.startswith("thousand"):
        return "thousand"
    return "billion" if u == "billion" else None


def parse_period_header(text: str) -> tuple[date | None, int | None]:
    """Period end and (if stated) length in months from a column header such as 'March 31, 2026'."""
    t = text.lower().replace(",", " ").replace("’", "'")
    t = re.sub(r"\s+", " ", t)
    months = None
    m = re.search(r"\b(three|six|nine|3|6|9) months?\b", t)
    if m:
        months = {"three": 3, "six": 6, "nine": 9}.get(m.group(1), None) or int(m.group(1))
    for pat, order in ((r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})", "mdy"),
                       (r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})", "dmy"),
                       (r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})(?!\d)", "num")):
        m = re.search(pat, t)
        if m:
            try:
                if order == "mdy":
                    return date(int(m.group(3)), _MONTHS[m.group(1)[:3]], int(m.group(2))), months
                if order == "dmy":
                    return date(int(m.group(3)), _MONTHS[m.group(2)[:3]], int(m.group(1))), months
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1))), months
            except (ValueError, KeyError):
                continue
    m = re.search(r"\b(?:fiscal|fy|financial year)\s*'?(\d{2,4})(?:\s*[-–]\s*(\d{2,4}))?", t) or re.search(r"\b(20\d{2})\s*[-–]\s*(\d{2})\b", t)
    if m:
        a, b = m.group(1), m.group(2)
        year = int(b) if b and len(b) == 4 else (int(a[:2] + b) if b and len(a) == 4 else int(a) if len(a) == 4 else 2000 + int(a))
        return date(year, 3, 31), 12
    return None, months


def header_dates(header: str, n: int) -> list[tuple[date, int | None]] | None:
    """Exactly ``n`` period ends read from a header in reading order, or None.

    Headers are often split over lines ("As at June | As at March" / "30, 2026 | 31, 2026"), so
    besides whole dates, month, day and year tokens are also collected as separate sequences and
    paired up when each sequence has one entry per column.
    """
    t = re.sub(r"\s+", " ", header.lower().replace("’", "'"))
    months = None
    m = re.search(r"\b(three|six|nine|3|6|9) months?\b", t)
    if m:
        months = {"three": 3, "six": 6, "nine": 9}.get(m.group(1), None) or int(m.group(1))
    # "April 1, 2026 to June 30, 2026" is one period: keep its end date, note its length
    mon = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    md = rf"{mon}\s*\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{4}}|\d{{1,2}}(?:st|nd|rd|th)?\s*{mon},?\s*\d{{4}}"
    range_months: list[int] = []

    def _range(m: re.Match[str]) -> str:
        a, b = parse_period_header(m.group(1))[0], parse_period_header(m.group(2))[0]
        if a and b and b > a:
            range_months.append(max(1, round((b - a).days / 30.44)))
        return " " + m.group(2) + " "

    t = re.sub(rf"({md})\s*(?:to|till|until|-|–)\s*({md})", _range, t)
    if range_months and months is None:
        months = range_months[0]
    whole = []
    for m in re.finditer(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})"
                         # one short stray token before the year is tolerated: OCR reads table rules as "ee", "|" etc.
                         r"|\b(\d{1,2})(?:st|nd|rd|th)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*(?:[a-z|]{1,3}\s+)?(\d{4})", t):
        try:
            if m.group(1):
                whole.append(date(int(m.group(3)), _MONTHS[m.group(1)[:3]], int(m.group(2))))
            else:
                whole.append(date(int(m.group(6)), _MONTHS[m.group(5)[:3]], int(m.group(4))))
        except ValueError:
            continue
    whole = [d for d in whole if _month_end(d)] if len([d for d in whole if _month_end(d)]) == n else whole
    if len(whole) != n:  # numeric dates such as 30-04-2026 or 31/03/2025
        numeric = []
        for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})(?!\d)", t):
            try:
                numeric.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
            except ValueError:
                continue
        if len(numeric) == n:
            whole = numeric
    if len(whole) == n and len(set(whole)) == n:
        return [(d, months if i == 0 else None) for i, d in enumerate(whole)]
    mons = [_MONTHS[x[:3]] for x in re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", t)]
    days = [int(x) for x in re.findall(r"(?<![\d.])(\d{1,2})(?:st|nd|rd|th)?,?(?![\d.])", t) if 1 <= int(x) <= 31]
    years = [int(x) for x in re.findall(r"\b(20\d{2}|19\d{2})\b(?!\s*[-–]\s*\d)", t)]
    if len(mons) == n and len(days) == n and len(years) == n:
        try:
            paired = [date(y, mo, d) for mo, d, y in zip(mons, days, years, strict=True)]
        except ValueError:
            return None
        # interleaved headers can pair a month with another column's day: only accept real period ends
        if all(_month_end(d) for d in paired) and len(set(paired)) == n:
            return [(d, months if i == 0 else None) for i, d in enumerate(paired)]
    fiscal = re.findall(r"\b(?:fiscal|fy|financial year)\s*'?(\d{4}|\d{2})(?:\s*[-–]\s*(\d{2,4}))?|\b(20\d{2})\s*[-–]\s*(\d{2})\b", t)
    if len(fiscal) == n:
        out: list[tuple[date, int | None]] = []
        for a, b, c, d2 in fiscal:
            if c:
                out.append((date(int(c[:2] + d2), 3, 31), 12))
            else:
                year = int(b) if b and len(b) == 4 else (int(a[:2] + b) if b and len(a) == 4 else (int(a) if len(a) == 4 else 2000 + int(a)))
                out.append((date(year, 3, 31), 12))
        return out
    return None


def _month_end(d: date) -> bool:
    """Reporting periods end on a month's last day; a date such as 'April 1' is a period start."""
    return (d + timedelta(days=1)).day == 1


def _periods(page: Any, rows: list[Row], centres: list[float], title_y: float) -> list[Period] | None:
    first_val = min((r.y for r in rows if r.has_values and not is_year_row(r) and len(r.cells) >= max(1, len(centres) - 1)), default=None)
    if first_val is None:
        return None
    header = " ".join(r.label + " " + " ".join(c.text for c in r.cells) for r in rows if title_y < r.y < first_val - 1)
    # two readings of the header: in reading order, and by the words sitting over each column;
    # the first that yields valid, distinct, plausibly ordered period ends is used
    readings: list[list[tuple[date | None, int | None]]] = [list(header_dates(header, len(centres)) or []),
                [parse_period_header(h) for h in header_text_by_column(page, centres, first_val - 1, title_y + 1)]]
    for parsed in readings:
        periods = _to_periods(parsed) if parsed else None
        if periods is not None:
            return periods
    return None


def _to_periods(parsed: list[tuple[date | None, int | None]]) -> list[Period] | None:
    if any(d is None or not _month_end(d) for d, _ in parsed) or len({d for d, _ in parsed}) != len(parsed):
        return None  # two columns can never end on the same date: the header was not read correctly
    ends = [d for d, _ in parsed if d is not None]
    fye = Counter((d.month, d.day) for d in ends).most_common(1)[0][0]
    out = []
    for k, (d, months) in enumerate(parsed):
        if d is None:  # excluded above; kept explicit so the guard survives `python -O`
            return None
        if months is None or (d.month, d.day) == fye:
            months = 12 if (d.month, d.day) == fye else ((d.month - fye[0]) % 12 or 12)
        out.append(Period(k, d, months, period_label(d, months, fye[0])))
    return out if plausible_order(out) else None


def plausible_order(periods: list[Period]) -> bool:
    """Columns run in one direction within the annual group and within the interim group, and each group is contiguous.

    A header read in the wrong order still yields valid-looking dates; this catches it.
    """
    def monotonic(ds: list[date]) -> bool:
        return all(a > b for a, b in zip(ds, ds[1:], strict=False)) or all(a < b for a, b in zip(ds, ds[1:], strict=False))

    kinds = [p.months == 12 for p in periods]
    runs = sum(1 for a, b in zip(kinds, kinds[1:], strict=False) if a != b)
    return runs <= 1 and monotonic([p.end for p in periods if p.months == 12]) and monotonic([p.end for p in periods if p.months != 12])


def period_label(end: date, months: int, fye_month: int = 3) -> str:
    """'FY2026' for a full fiscal year ending in ``end``'s year, else e.g. '3M Jun-2026'."""
    if months == 12:
        if end.month == 3:
            return f"FY{end.year}"
        return f"CY{end.year}" if end.month == 12 else f"FY{end.year} ({end:%b})"
    return f"{months}M {end:%b-%Y}"


def _title_lines(text: str, n: int = 8) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(lines[:n])


def _basis_of(title: str, doc_basis: str) -> str:
    t = title.lower()
    if "consolidated" in t:
        return "consolidated"
    if "standalone" in t:
        return "standalone"
    return doc_basis


def document_basis(texts: list[str]) -> str:
    """Whether the restated financials are consolidated or standalone, when headings do not say."""
    blob = " ".join(texts[: min(len(texts), 200)]).lower()
    c = len(re.findall(r"restated consolidated (financial|summary|statement)", blob))
    s = len(re.findall(r"restated standalone (financial|summary|statement)", blob))
    if c >= 3 and c >= 2 * s:
        return "consolidated"
    if s >= 3 and s >= 2 * c:
        return "standalone"
    return "unknown"


# ---------------------------------------------------------------------------- statement parsing
def _without_notes_column(page: Any, rows: list[Row], centres: list[float], title_y: float) -> list[float]:
    """Statements with a "Notes" column print note references (e.g. "3", "4(a)") that look like figures."""
    first_val = min((r.y for r in rows if r.y > title_y and r.has_values and not is_year_row(r)), default=None)
    if first_val is None or len(centres) < 3:
        return centres
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        if title_y < (y0 + y1) / 2 < first_val and re.fullmatch(r"notes?\.?|note\s*no\.?", text.strip().lower()):
            cx = (x0 + x1) / 2
            k = min(range(len(centres)), key=lambda j: abs(centres[j] - cx))
            if abs(centres[k] - cx) < 35:
                return centres[:k] + centres[k + 1:]
    # no "Notes" heading (e.g. an OCR'd page): a leftmost column holding only small note references such as
    # "3", "11" or "6.1" — never amounts with two decimals or thousands separators — is a notes column
    refs = [c.text.strip() for r in rows if r.y > title_y and len(r.cells) == len(centres) and not is_year_row(r)
            for c in r.cells if abs(c.x - centres[0]) < 25]
    if len(refs) >= 4 and all(re.fullmatch(r"\d{1,2}(\.\d)?(\([a-z]\))?", t) and float(re.sub(r"\(.*", "", t)) <= 60 for t in refs):
        return centres[1:]
    return centres


def parse_statement(doc: Any, page_index: int, kind: str, doc_basis: str) -> StatementTable | None:
    page = doc[page_index]
    text = page.get_text()
    title = _title_lines(text)
    m = TITLES[kind].search(title)
    if not m or "...." in title:
        return None
    rows = merge_split_rows(page_rows(page, page_index + 1))
    title_row_y = next((r.y for r in rows if TITLES[kind].search(r.label)), 0.0)
    centres = column_centres([r for r in rows if r.y > title_row_y and not is_year_row(r)])
    if not centres:
        return None
    centres = _without_notes_column(page, rows, centres, title_row_y)
    periods = _periods(page, rows, centres, title_row_y)
    # statements often continue on the next page (without a new heading)
    if page_index + 1 < len(doc):
        nxt_text = doc[page_index + 1].get_text()
        nxt_title = _title_lines(nxt_text, 4)
        if not any(t.search(nxt_title) for kk, t in TITLES.items() if kk != kind):
            nxt_rows = merge_split_rows(page_rows(doc[page_index + 1], page_index + 2))
            full = [r for r in nxt_rows if len(r.cells) == len(centres) and not is_year_row(r)]
            nxt_c = column_centres(full)
            if nxt_c and all(abs(a - b) <= 30 for a, b in zip(nxt_c, centres, strict=True)):
                rows = rows + nxt_rows
    align(rows, centres)
    unit = detect_unit(title) or detect_unit(text) or (detect_unit(doc[page_index - 1].get_text()) if page_index else None)
    unit_note = None
    if unit is None:  # statements of one restated set share a unit, sometimes stated only on a sibling statement
        for j in range(page_index + 1, min(page_index + 3, len(doc))):
            sib = doc[j].get_text()
            if any(t.search(_title_lines(sib)) for t in TITLES.values()) and detect_unit(sib):
                unit, unit_note = detect_unit(sib), f"p{page_index + 1}: unit taken from the statement on p{j + 1} of the same restated set"
                break
    tbl = StatementTable(kind, page_index + 1, _basis_of(title, doc_basis), unit, periods or [], title=title[:200], ncols=len(centres))
    if unit_note:
        tbl.warnings.append(unit_note)
    if periods is None:
        tbl.warnings.append(f"p{page_index + 1}: reporting periods could not be read from the column headers")
    if unit is None:
        tbl.warnings.append(f"p{page_index + 1}: unit (₹ million / lakhs / crore) not stated on the page")
    factor = UNIT_TO_CRORE.get(unit or "", None)
    section = ""
    sums: dict[tuple[str, int], list[Figure]] = {}
    for r in rows:
        if r.y <= title_row_y and r.page == tbl.page:
            continue
        lab = norm_label(r.label)
        if not lab:
            continue
        if not r.columns:
            if re.match(r"^(shareholders'? funds|equity)$", lab):
                section = "eq"
            elif re.match(r"^non[- ]?current liabilities", lab):
                section = "ncl"
            elif re.match(r"^current liabilities", lab):
                section = "cl"
            elif re.match(r"^non[- ]?current assets", lab):
                section = "nca"
            elif re.match(r"^current assets", lab):
                section = "ca"
            continue
        targets: list[str] = []
        if kind == "bs" and lab == "total" and section:
            # Indian GAAP layout: each section ends with a bare "Total"
            targets = [{"eq": "total_equity", "ncl": "non_current_liabilities", "cl": "current_liabilities",
                        "nca": "non_current_assets", "ca": "current_assets"}[section]]
        for fld, rx, k in _COMPILED if not targets else []:
            if k == kind and rx.search(lab):
                targets = [fld]
                break
        if not targets and kind == "cf" and _CAPEX.search(lab):
            targets = ["capex_rows"]
        if not targets and kind == "bs":
            if _LEASE.search(lab):
                targets = ["lease_rows"]
            elif _BORROW.search(lab) or _CUR_MATURITY.search(lab):
                if "long" in lab[:12] and not _CUR_MATURITY.search(lab):
                    targets = ["borrow_ncl"]
                elif "short" in lab[:12] or _CUR_MATURITY.search(lab):
                    targets = ["borrow_cl"]
                elif section in ("ncl", "cl"):
                    targets = [f"borrow_{section}"]
        for fld in targets:
            for col, cell in r.columns.items():
                per_share = fld in PER_SHARE
                v = cell.value if per_share or cell.value is None or factor is None else round(cell.value * factor, 6)
                fig = Figure(fld, v, cell.text, r.label[:300], r.page, "INR per share" if per_share else (unit or "unknown"))
                if fld.endswith("_rows") or fld.startswith("borrow_"):
                    sums.setdefault((fld, col), []).append(fig)
                elif (fld, col) not in tbl.figures:
                    tbl.figures[(fld, col)] = fig
    for (fld, col), figs in sums.items():
        name = {"capex_rows": "capex", "lease_rows": "lease_liabilities", "borrow_ncl": "borrowings_non_current", "borrow_cl": "borrowings_current"}[fld]
        vals = [f.value for f in figs]
        total = None if any(v is None for v in vals) else sum(v for v in vals if v is not None)
        if name == "capex" and total is not None:
            total = abs(total)  # cash outflow printed as negative
        tbl.figures[(name, col)] = Figure(name, total, " + ".join(f.raw_text for f in figs)[:64], " + ".join(f.raw_label for f in figs)[:300],
                                          figs[0].page, figs[0].unit)
    if factor is None:  # without a unit, amounts cannot be normalised: keep nothing but per-share figures
        tbl.figures = {k: v for k, v in tbl.figures.items() if k[0] in PER_SHARE}
    return tbl


def find_statements(doc: Any, texts: list[str]) -> list[list[StatementTable]]:
    """Candidate tables per (kind, basis), best first: tables whose periods could be read rank above those that cannot."""
    doc_basis = document_basis(texts)
    cands: dict[tuple[str, str], list[tuple[int, int, StatementTable]]] = {}
    for kind, rx in TITLES.items():
        pages = [i for i, t in enumerate(texts) if rx.search(_title_lines(t)) and "...." not in _title_lines(t)][:20]
        for i in pages:
            tbl = parse_statement(doc, i, kind, doc_basis)
            if tbl is None or not all(any(f == r for f, _ in tbl.figures) for r in REQUIRED[kind]):
                continue
            score = len(tbl.figures) + (10_000 if tbl.periods else 0)
            cands.setdefault((kind, tbl.basis), []).append((-score, i, tbl))  # earliest page wins ties (summary section)
    return [[t for _, _, t in sorted(v, key=lambda x: (x[0], x[1]))] for _, v in sorted(cands.items())]


# ---------------------------------------------------------------------------- merge + validate
def _close(a: float, b: float, rel: float = 0.005, abs_tol: float = 0.02) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def merge_periods(tables: list[StatementTable], borrowed: bool = False) -> list[PeriodStatement]:
    out: dict[tuple[str, date], PeriodStatement] = {}
    origin: dict[tuple[str, date], dict[str, StatementTable]] = {}
    for t in tables:
        for p in t.periods:
            ps = out.setdefault((t.basis, p.end), PeriodStatement(t.basis, p.end, p.months, p.label))
            for (fld, col), fig in t.figures.items():
                if col == p.column and fld not in ps.figures:
                    ps.figures[fld] = fig
                    origin.setdefault((t.basis, p.end), {})[fld] = t
    for key, ps in out.items():
        borrowed_tbl = next((t for t in origin.get(key, {}).values() if t.borrowed_periods), None)
        if borrowed_tbl is not None and ps.figures.get("pbt") and ps.figures.get("pbt_cf"):
            ok = _close(ps.figures["pbt"].value or 0.0, ps.figures["pbt_cf"].value or 0.0) if (
                ps.figures["pbt"].value is not None and ps.figures["pbt_cf"].value is not None) else False
            if not ok:  # the borrowed column order is wrong for this period: drop that statement's figures only
                for fld, t in origin[key].items():
                    if t is borrowed_tbl:
                        ps.figures.pop(fld, None)
                ps.checks.append({"check": "borrowed_columns_aligned", "formula": f"{borrowed_tbl.kind} statement on p{borrowed_tbl.page} "
                                  "used periods from another statement; P&L PBT ≠ cash-flow PBT, so its figures were discarded",
                                  "lhs": 0, "rhs": 0, "difference": 0, "passed": False, "hard": False})
        derive(ps)
        prior = list(ps.checks)
        crosscheck = borrowed_tbl is not None and "pbt_cf" in ps.figures and "pbt" in ps.figures
        validate(ps, crosscheck)
        ps.checks = prior + ps.checks
        if borrowed_tbl is not None and not crosscheck and any(t is borrowed_tbl for t in origin.get(key, {}).values()):
            ps.checks.append({"check": "borrowed_columns_aligned", "formula": f"{borrowed_tbl.kind} statement on p{borrowed_tbl.page} used periods from "
                              "another statement and could not be cross-checked (no profit before tax on both)", "lhs": 0, "rhs": 0,
                              "difference": 0, "passed": False, "hard": False})
            if ps.validation_status == "passed":
                ps.validation_status = "partial"  # stored as extracted (unverified), not verified
    return sorted(out.values(), key=lambda p: (p.basis, p.end))


def derive(ps: PeriodStatement) -> None:
    g = ps.get
    if g("pbt") is None and g("pbt_pre_exceptional") is not None and g("pat") is not None and g("tax_expense") is not None:
        pass  # exceptional items present without a final PBT line: leave PBT unavailable
    if g("pbt") is not None and g("finance_costs") is not None:
        ps.derived["ebit"] = (g("pbt") + g("finance_costs"), "PBT + finance costs")  # type: ignore[operator]
        if g("depreciation") is not None:
            ps.derived["ebitda"] = (g("pbt") + g("finance_costs") + g("depreciation"), "PBT + finance costs + depreciation & amortisation")  # type: ignore[operator]
    if g("total_liabilities") is None:
        if g("non_current_liabilities") is not None and g("current_liabilities") is not None:
            ps.derived["total_liabilities"] = (g("non_current_liabilities") + g("current_liabilities"), "non-current + current liabilities")  # type: ignore[operator]
        elif g("total_assets") is not None and g("total_equity") is not None:
            ps.derived["total_liabilities"] = (g("total_assets") - g("total_equity"), "total assets − total equity")  # type: ignore[operator]
    if g("total_equity") is None and g("share_capital") is not None and g("other_equity") is not None:
        ps.derived["total_equity"] = (g("share_capital") + g("other_equity"), "share capital + other equity")  # type: ignore[operator]
    b_nc, b_c = g("borrowings_non_current"), g("borrowings_current")
    if b_nc is not None or b_c is not None:
        ps.derived["total_debt"] = ((b_nc or 0.0) + (b_c or 0.0), "non-current + current borrowings (lease liabilities excluded)")
    elif g("non_current_liabilities") is not None and g("current_liabilities") is not None:
        ps.derived["total_debt"] = (0.0, "no borrowings line in the balance sheet")
    if g("total_income") is None and g("revenue") is not None and g("other_income") is not None:
        ps.derived["total_income"] = (g("revenue") + g("other_income"), "revenue + other income")  # type: ignore[operator]


def validate(ps: PeriodStatement, borrowed: bool = False) -> None:
    g = ps.get
    checks: list[dict[str, Any]] = []

    def check(name: str, lhs: float | None, rhs: float | None, formula: str, hard: bool = True) -> None:
        if lhs is None or rhs is None:
            return
        ok = _close(lhs, rhs)
        checks.append({"check": name, "formula": formula, "lhs": round(lhs, 4), "rhs": round(rhs, 4),
                       "difference": round(lhs - rhs, 4), "passed": ok, "hard": hard})

    te, ncl, cl = g("total_equity"), g("non_current_liabilities"), g("current_liabilities")
    if g("total_equity_and_liabilities") is not None:
        check("balance_sheet_balances", g("total_assets"), g("total_equity_and_liabilities"), "Total assets = Total equity and liabilities")
    if te is not None and ncl is not None and cl is not None:
        check("equity_plus_liabilities", g("total_assets"), te + ncl + cl, "Total assets = Equity + Non-current + Current liabilities")
    if g("current_assets") is not None and g("non_current_assets") is not None:
        check("assets_add_up", g("total_assets"), g("current_assets") + g("non_current_assets"), "Total assets = Current + Non-current assets")  # type: ignore[operator]
    if g("pbt") is not None and g("tax_expense") is not None:
        check("pat_reconciles", g("pat"), g("pbt") - g("tax_expense"), "PAT = PBT − Tax")  # type: ignore[operator]
    if "total_income" in ps.figures and g("revenue") is not None and g("other_income") is not None:
        check("income_adds_up", g("total_income"), g("revenue") + g("other_income"), "Total income = Revenue + Other income")  # type: ignore[operator]
    if "total_income" in ps.figures and g("total_expenses") is not None and g("pbt") is not None and "pbt_pre_exceptional" not in ps.figures:
        check("pbt_reconciles", g("pbt"), g("total_income") - g("total_expenses"), "PBT = Total income − Total expenses", hard=False)  # type: ignore[operator]
    if g("share_capital") is not None and g("other_equity") is not None and "total_equity" in ps.figures:
        check("equity_adds_up", g("total_equity"), g("share_capital") + g("other_equity"), "Total equity = Share capital + Other equity", hard=False)  # type: ignore[operator]
    if g("pbt") is not None and g("pbt_cf") is not None:
        check("cash_flow_starts_from_pbt", g("pbt_cf"), g("pbt"), "Cash-flow profit before tax = P&L profit before tax", hard=borrowed)
    ps.checks = checks
    hard = [c for c in checks if c["hard"]]
    if any(not c["passed"] for c in hard):
        ps.validation_status = "failed"
    elif hard and len({c["check"] for c in hard} & {"balance_sheet_balances", "equity_plus_liabilities", "pat_reconciles"}) >= 2:
        ps.validation_status = "passed"
    elif hard:
        ps.validation_status = "partial"
    else:
        ps.validation_status = "not_checked"


def extract_financials(doc: Any) -> ExtractionResult:
    texts = [p.get_text() for p in doc]
    groups = find_statements(doc, texts)
    tables = [g[0] for g in groups]
    warnings = [w for t in tables for w in t.warnings]
    # a statement without readable periods borrows them from a statement on the same basis with the same columns;
    # the borrowed alignment is then confirmed by a hard check (P&L PBT = cash-flow PBT for every period)
    for gi, t in enumerate(list(tables)):
        if t.periods:
            continue
        for cand in groups[gi]:  # the best candidate whose column count matches a statement with readable periods
            donor = next((o for o in tables if o.periods and o.basis == cand.basis and len(o.periods) == cand.ncols), None)
            if donor:
                cand.periods = list(donor.periods)
                cand.borrowed_periods = True
                tables[gi] = cand
                warnings.append(f"p{cand.page}: periods taken from the {donor.kind} statement on p{donor.page}")
                break
        else:
            warnings.append(f"p{t.page}: {t.kind} statement skipped — its reporting periods could not be read")
    tables = [t for t in tables if t.periods]
    periods = merge_periods(tables, borrowed=any(t.borrowed_periods for t in tables))
    kinds = {t.kind for t in tables}
    status = "extracted" if kinds == {"bs", "pl", "cf"} else ("partial" if tables else "not_found")
    for k in ("bs", "pl", "cf"):
        if k not in kinds:
            warnings.append({"bs": "balance sheet", "pl": "profit and loss statement", "cf": "cash flow statement"}[k] + " not found")
    return ExtractionResult(status, len(texts), tables, periods, warnings)
