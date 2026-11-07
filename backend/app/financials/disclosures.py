"""Other prospectus disclosures used by the valuation and risk models.

* Listed-peer comparison table from "Basis for Issue/Offer Price" (SEBI ICDR prescribes it).
* Equity shares outstanding before the issue (for post-issue share count and market cap).
* Revenue share of the top customers.
* Auditor qualifications not given effect to in the restated financials.
* Contingent liabilities (summary table).

Every value carries the page it was read from. Anything not found is returned as None; nothing
is inferred from missing text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.financials.pdf_tables import Row, align, column_centres, is_year_row, merge_split_rows, page_rows
from app.financials.statement_parser import UNIT_TO_CRORE, _periods, _title_lines, detect_unit, period_label

_WS = re.compile(r"\s+")


def _flat(text: str) -> str:
    return _WS.sub(" ", text.replace(" ", " "))


# ---------------------------------------------------------------------------- peers
@dataclass
class PeerRow:
    name: str
    is_company: bool
    revenue_cr: float | None = None
    face_value: float | None = None
    closing_price: float | None = None
    eps_basic: float | None = None
    eps_diluted: float | None = None
    nav_per_share: float | None = None
    pe: float | None = None
    ronw_pct: float | None = None
    check_note: str | None = None


@dataclass
class PeerTable:
    page: int
    basis: str | None
    period_label: str | None
    price_date: date | None
    unit: str | None
    columns: list[str]
    rows: list[PeerRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def reliable(self) -> bool:
        return not any("need review" in w for w in self.warnings)


STANDARD_PEER_COLUMNS = ["revenue", "face_value", "closing_price", "eps_basic", "eps_diluted", "nav", "pe", "ronw"]
# Column orders seen in "Basis for Issue Price" peer tables; the one whose printed P/E matches
# price ÷ diluted EPS on most rows is used.
PEER_ORDERS = [
    STANDARD_PEER_COLUMNS,
    ["face_value", "closing_price", "revenue", "eps_basic", "eps_diluted", "nav", "pe", "ronw"],
    ["face_value", "revenue", "closing_price", "eps_basic", "eps_diluted", "nav", "pe", "ronw"],
    ["revenue", "face_value", "closing_price", "eps_basic", "eps_diluted", "pe", "ronw", "nav"],
    ["revenue", "face_value", "closing_price", "pe", "eps_basic", "eps_diluted", "ronw", "nav"],
]


def _consistent_rows(rows: list[Row], cols: list[str | None]) -> int:
    idx = {c: k for k, c in enumerate(cols) if c}
    if not {"closing_price", "eps_diluted", "pe"} <= idx.keys():
        return 0
    n = 0
    for r in rows:
        p, e, pe = (r.columns.get(idx[c]) for c in ("closing_price", "eps_diluted", "pe"))
        if p and e and pe and p.value and e.value and e.value > 0 and pe.value and abs(p.value / e.value - pe.value) <= 0.1 * pe.value:
            n += 1
    return n


def _classify(head: str) -> str | None:
    h = head.lower()
    if "p/e" in h or "p / e" in h or "price earning" in h or "price to earning" in h:
        return "pe"
    if "ronw" in h or "ron w" in h or "return on net worth" in h or "roe" in h:
        return "ronw"
    if "nav" in h or "net asset" in h or "book value" in h:
        return "nav"
    if "diluted" in h:
        return "eps_diluted"
    if "basic" in h:
        return "eps_basic"
    if "face" in h:
        return "face_value"
    if "closing" in h or "market price" in h or "cmp" in h:
        return "closing_price"
    if "revenue" in h or "total income" in h or "income from" in h:
        return "revenue"
    if "eps" in h:
        return "eps_basic"
    return None


def peer_pages(texts: list[str]) -> list[int]:
    out = []
    for i, t in enumerate(texts):
        low = _flat(t).lower()
        if re.search(r"listed (industry )?peers?|comparison (of accounting ratios )?with listed|peer group", low) and "p/e" in low \
                and ("nav" in low or "ronw" in low or "ron w" in low):
            out.append(i)
    return out


def parse_peers(doc: Any, texts: list[str], company_name: str) -> PeerTable | None:
    for pi in peer_pages(texts)[:8]:
        tbl = _parse_peer_page(doc, texts, pi, company_name)
        if tbl is not None and tbl.rows:
            return tbl
    return None


def _parse_peer_page(doc: Any, texts: list[str], pi: int, company_name: str) -> PeerTable | None:
    page = doc[pi]
    text = texts[pi]
    rows = page_rows(page, pi + 1)
    anchor = next((r.y for r in rows if re.search(r"listed (industry )?peers?|comparison", r.label, re.I)), 0.0)
    num_rows = [r for r in rows if r.y > anchor and len(r.cells) >= 5 and not is_year_row(r)]
    if not num_rows:
        return None
    centres = column_centres(num_rows)
    align(num_rows, centres)
    first_y = min(r.y for r in num_rows)
    head_rows = [r for r in rows if anchor < r.y < first_y]
    from app.financials.pdf_tables import header_text_by_column

    heads = header_text_by_column(page, centres, first_y - 1, anchor + 1)
    cols: list[str | None] = [_classify(h) for h in heads]
    candidates = [cols] + ([list(o) for o in PEER_ORDERS] if len(cols) == len(STANDARD_PEER_COLUMNS) else [])
    priced = [r for r in num_rows if sum(1 for c in r.cells if c.value) >= 6]
    scores = [_consistent_rows(priced, c) for c in candidates]
    best = max(range(len(candidates)), key=lambda k: (scores[k], -k))
    cols = candidates[best]
    column_check = "passed" if priced and scores[best] >= max(1, (len(priced) + 1) // 2) else "failed"
    header_blob = " ".join(r.label + " " + " ".join(c.text for c in r.cells) for r in head_rows)
    unit = detect_unit(header_blob) or detect_unit(text)
    factor = UNIT_TO_CRORE.get(unit or "")
    low = _flat(text).lower()
    basis = "standalone" if re.search(r"peers?[^.]{0,200}standalone|standalone[^.]{0,200}peers?", low) else (
        "consolidated" if re.search(r"peers?[^.]{0,200}consolidated|consolidated[^.]{0,200}peers?", low) else None)
    m = re.search(r"(?:year|fiscal) ended (?:on )?(march|december) (\d{1,2}),? (\d{4})", low)
    per = period_label(date(int(m.group(3)), 3 if m.group(1) == "march" else 12, int(m.group(2))), 12) if m else None
    m = re.search(r"(?:as on|as of|as at) (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* (\d{1,2}),? (\d{4})", _flat(header_blob + " " + text).lower())
    price_date = None
    if m:
        try:
            price_date = date(int(m.group(3)), ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(m.group(1)) + 1, int(m.group(2)))
        except ValueError:
            price_date = None
    tbl = PeerTable(pi + 1, basis, per, price_date, unit, [c or "?" for c in cols])
    if column_check == "failed":
        tbl.warnings.append("column layout could not be confirmed (printed P/E does not match price ÷ diluted EPS); peer figures need review")
    label_only = [r for r in rows if r.label and not r.cells and r.y > anchor]
    company_key = " ".join(company_name.lower().split()[:2]) if company_name else ""
    for r in sorted(num_rows, key=lambda r: r.y):
        name = r.label
        above = [lr for lr in label_only if 0 < r.y - lr.y <= 14]
        below = [lr for lr in label_only if 0 < lr.y - r.y <= 14]
        if not name or len(name) < 4:
            parts = [above[-1].label] if above and not re.search(r"name of|listed peers?|company", above[-1].label, re.I) else []
            if below and re.search(r"(limited|ltd\.?|industries|corporation|company)$", below[0].label, re.I) and not (parts and re.search(r"limited$", parts[0], re.I)):
                parts.append(below[0].label)
            name = " ".join(parts)
        name = re.sub(r"\*+$", "", name).strip()
        if not name:
            continue
        is_company = bool(company_key) and (name.lower().startswith(company_key) or name.lower() in ("our company", "the company"))
        pr = PeerRow(name[:200], bool(is_company))
        for k, cell in r.columns.items():
            if k >= len(cols) or cols[k] is None:
                continue
            v = cell.value
            c = cols[k] or ""
            if c == "revenue":
                pr.revenue_cr = None if v is None or factor is None else round(v * factor, 4)
            elif c == "nav":
                pr.nav_per_share = v
            elif c == "ronw":
                pr.ronw_pct = v
            else:
                setattr(pr, c, v)
        if pr.pe is not None and pr.closing_price and pr.eps_diluted and pr.eps_diluted > 0:
            implied = pr.closing_price / pr.eps_diluted
            pr.check_note = ("P/E consistent with price ÷ diluted EPS" if abs(implied - pr.pe) <= 0.1 * pr.pe
                             else f"printed P/E {pr.pe:g} differs from price ÷ diluted EPS ({implied:.2f})")
        tbl.rows.append(pr)
    if not any(not r.is_company for r in tbl.rows):
        tbl.warnings.append("no listed peers in the comparison table")
    return tbl


# ---------------------------------------------------------------------------- other disclosures
@dataclass
class Disclosure:
    key: str
    value: Any
    page: int
    text: str
    basis: str | None = None


_PRE_ISSUE = [re.compile(p, re.I) for p in (
    # capital structure: "ISSUED, SUBSCRIBED AND PAID-UP SHARE CAPITAL BEFORE THE ISSUE 4,50,31,834 Equity Shares";
    # offer summary: "Equity Shares outstanding prior to the Issue (as at the date of this RHP) 4,50,31,834 Equity Shares"
    r"(?:paid[- ]up|outstanding)[a-z ,]{0,40}?(?:before|prior to) the (?:issue|offer)[^\[●]{0,150}?\b(\d{1,3}(?:,\d{2,3})+)\s?"
    r"(?:fully paid[- ]up )?equity shares",
    r"(?:before|prior to) the (?:issue|offer)[^\[●\d]{0,150}?\b(\d{1,3}(?:,\d{2,3})+)\s?(?:fully paid[- ]up )?equity shares",
    r"([\d,]{5,})\s*equity shares[^.]{0,80}?(?:outstanding )?(?:prior to|before) the (?:issue|offer)",
)]


def pre_issue_shares(texts: list[str]) -> Disclosure | None:
    for i, t in enumerate(texts[:260]):
        flat = _flat(t)
        for pat in _PRE_ISSUE:
            m = pat.search(flat)
            if m:
                n = int(m.group(1).replace(",", ""))
                if n >= 100_000:
                    return Disclosure("pre_issue_shares", n, i + 1, flat[max(0, m.start() - 40): m.end() + 40])
    return None


_WORDS = {"three": 3, "five": 5, "ten": 10, "twenty": 20, "3": 3, "5": 5, "10": 10, "20": 20}


def customer_concentration(texts: list[str]) -> Disclosure | None:
    pat1 = re.compile(r"((?:\d{1,3}(?:\.\d+)?\s?%[\s,]*(?:and\s*)?){1,6})of (?:our )?(?:total )?revenue (?:from operations )?"
                      r"(?:was derived )?(?:from|contributed by|attributable to) (?:our )?top (three|five|ten|twenty|3|5|10|20) customers", re.I)
    pat2 = re.compile(r"top (three|five|ten|twenty|3|5|10|20) customers (?:contributed|accounted for|constituted|represented)[^%]{0,80}?(\d{1,3}(?:\.\d+)?)\s?%", re.I)
    for i, t in enumerate(texts[:300]):
        flat = _flat(t)
        m = pat1.search(flat)
        if m:
            vals = [float(x) for x in re.findall(r"(\d{1,3}(?:\.\d+)?)\s?%", m.group(1))]
            after = flat[m.end(): m.end() + 160].lower()
            idx = 1 if ("period ended" in after or "months" in after) and len(vals) > 1 else 0
            if vals and 0 < vals[idx] <= 100:
                return Disclosure("customer_concentration_pct", vals[idx], i + 1, flat[max(0, m.start() - 20): m.end() + 120],
                                  f"top {_WORDS[m.group(2).lower()]} customers, latest full fiscal year")
        m = pat2.search(flat)
        if m and 0 < float(m.group(2)) <= 100:
            return Disclosure("customer_concentration_pct", float(m.group(2)), i + 1, flat[max(0, m.start() - 20): m.end() + 60],
                              f"top {_WORDS[m.group(1).lower()]} customers")
    return None


def auditor_qualifications(texts: list[str]) -> Disclosure | None:
    none_pat = re.compile(r"there (?:are|were) no (?:audit |auditor'?s? )?qualifications|no qualifications? (?:by|of|in|from) (?:the )?(?:statutory )?auditors?|"
                          r"auditor qualifications?[^.]{0,120}?\b(nil|not applicable)\b", re.I)
    has_pat = re.compile(r"(qualified opinion|qualifications? (?:which|that) (?:has|have) not been given effect)", re.I)
    for i, t in enumerate(texts):
        flat = _flat(t)
        m = none_pat.search(flat)
        if m:
            return Disclosure("auditor_qualifications", "none", i + 1, flat[max(0, m.start() - 40): m.end() + 80])
    for i, t in enumerate(texts):
        flat = _flat(t)
        m = has_pat.search(flat)
        if m and not re.search(r"\bno\b|\bnot\b|\bnil\b", flat[max(0, m.start() - 60): m.start()], re.I):
            return Disclosure("auditor_qualifications", "disclosed", i + 1, flat[max(0, m.start() - 80): m.end() + 120])
    return None


def contingent_liabilities(doc: Any, texts: list[str]) -> Disclosure | None:
    for i, t in enumerate(texts[:300]):
        title = _title_lines(t, 4)
        if not re.search(r"summary of contingent liabilit", title, re.I) or "...." in title:
            continue
        rows: list[Row] = merge_split_rows(page_rows(doc[i], i + 1))
        title_y = next((r.y for r in rows if re.search(r"contingent liabilit", r.label, re.I)), 0.0)
        centres = column_centres([r for r in rows if r.y > title_y and not is_year_row(r)])
        if not centres:
            continue
        periods = _periods(doc[i], rows, centres, title_y)
        align(rows, centres)
        unit = detect_unit(t)
        factor = UNIT_TO_CRORE.get(unit or "")
        if not periods or factor is None:
            continue
        annual = [p for p in periods if p.months == 12]
        if not annual:
            continue
        latest = max(annual, key=lambda p: p.end)
        for pattern, incl in ((r"^(sub ?total|total)\s*\(a\)|^(total )?contingent liabilit(y|ies)\s*(\(a\))?$", False),
                              (r"^total contingent liabilit(y|ies) (and|&) commitments", True)):
            for r in rows:
                lab = re.sub(r"^\(?[a-z0-9]{1,3}[.)]\s*", "", r.label.lower().strip())  # keep "(A)" vs "(B)" apart
                if r.columns and re.search(pattern, lab) and latest.column in r.columns:
                    cell = r.columns[latest.column]
                    if cell.value is None:
                        continue
                    return Disclosure("contingent_liabilities_cr", round(cell.value * factor, 4), i + 1, f"{r.label}: {cell.text} ({unit})",
                                      f"{latest.label}{' incl. commitments' if incl else ''}")
    return None


def extract_disclosures(doc: Any, texts: list[str]) -> dict[str, Disclosure]:
    out: dict[str, Disclosure] = {}
    for fn in (pre_issue_shares, customer_concentration, auditor_qualifications, business_overview):
        d = fn(texts)
        if d is not None:
            out[d.key] = d
    d = contingent_liabilities(doc, texts)
    if d is not None:
        out[d.key] = d
    return out


_OVERVIEW_START = re.compile(r"^(we are|we were|we operate|we manufacture|we design|we provide|we offer|we specialise|we specialize|we're|"
                             r"our company is|our company was|our company operates|incorporated in)\b", re.I)


def business_overview(texts: list[str]) -> Disclosure | None:
    """The company's own description of its business: the first descriptive paragraph of the 'Our Business' section.

    Quoted as printed (whitespace normalised, cut at a sentence end), with its page. Not interpreted or summarised.
    """
    starts = [i for i, t in enumerate(texts) if re.search(r"(?im)^\s*our business\s*$", t[:500])]
    for s in starts:
        for i in range(s, min(s + 4, len(texts))):
            for para in re.split(r"\n\s*\n", texts[i]):
                flat = re.sub(r"\s+", " ", para).strip()
                if len(flat) < 150 or not _OVERVIEW_START.match(flat):
                    continue
                cut = flat[:900]
                if len(flat) > 900:
                    end = max(cut.rfind(". "), cut.rfind(".) "))
                    cut = cut[: end + 1] if end > 200 else cut + "…"
                return Disclosure(key="business_overview", value=cut, page=i + 1, text=cut, basis="Our Business — overview, as printed")
    return None
