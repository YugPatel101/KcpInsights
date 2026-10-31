"""Rebuild table rows from PDF word positions.

Prospectus financial tables are laid out as a label followed by one figure per reporting period.
Text extraction in reading order interleaves them unpredictably, so rows are rebuilt from word
coordinates instead: words on the same baseline form a row, trailing numeric tokens are the
figures, and figures are assigned to period columns by their horizontal position.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

NUMBER_RE = re.compile(r"^\(?[-−–]?\(?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?\)?%?$")
NIL_TOKENS = {"-", "--", "–", "—", "nil", "Nil", "NIL"}
NA_TOKENS = {"NA", "N.A.", "N.A", "n.a.", "[●]", "[•]", "[●]*", "[•]*", "NM", "N/A"}


@dataclass
class Cell:
    text: str  # exactly as printed, e.g. "(218.38)"
    value: float | None  # parsed number; 0.0 for printed nil ("-"), None for "NA"/"[●]"
    x: float  # horizontal centre


@dataclass
class Row:
    label: str
    cells: list[Cell]
    y: float
    page: int
    label_x: float = 0.0
    columns: dict[int, Cell] = field(default_factory=dict)  # column index -> cell, once aligned

    @property
    def has_values(self) -> bool:
        return bool(self.cells)


def parse_number(tok: str) -> tuple[bool, float | None]:
    """(is_numeric_token, value). Brackets mean negative; "-" means a printed nil (zero)."""
    t = tok.strip().rstrip("*^#").strip()
    if t in NIL_TOKENS:
        return True, 0.0
    if t in NA_TOKENS:
        return True, None
    if not NUMBER_RE.match(t):
        return False, None
    neg = t.startswith("(") or t.startswith("-") or t.startswith("−") or t.startswith("–")
    digits = re.sub(r"[^\d.]", "", t)
    if not digits or digits == ".":
        return False, None
    try:
        v = float(digits)
    except ValueError:
        return False, None
    return True, -v if neg else v


def _is_serial(tok: str) -> bool:
    """Row enumerators like "1.", "(a)", "ii)" that sit before a label, not figures."""
    return bool(re.match(r"^\(?([a-z]|[ivx]{1,4}|\d{1,2})[.)]$", tok, re.I))


def page_rows(page: Any, page_no: int, y_tol: float = 2.6) -> list[Row]:
    """Rows of one PyMuPDF page: label text plus trailing numeric cells, in top-to-bottom order."""
    words = page.get_text("words")
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[tuple[float, float, float, str]]] = []
    centers: list[float] = []
    for x0, y0, x1, y1, text, *_ in words:
        cy = (y0 + y1) / 2
        if lines and abs(cy - centers[-1]) <= y_tol:
            lines[-1].append((x0, x1, cy, text))
        else:
            lines.append([(x0, x1, cy, text)])
            centers.append(cy)
    rows: list[Row] = []
    for ln, cy in zip(lines, centers, strict=True):
        ln.sort(key=lambda t: t[0])
        cells: list[Cell] = []
        i = len(ln) - 1
        while i >= 0:
            x0, x1, _, text = ln[i]
            ok, val = parse_number(text)
            if not ok:
                break
            cells.append(Cell(text, val, (x0 + x1) / 2))
            i -= 1
        label_tokens = [t for *_, t in ln[: i + 1]]
        # a lone enumerator ("1.") is part of the label, not a figure
        if not label_tokens and len(cells) == 1 and _is_serial(cells[0].text):
            label_tokens, cells = [cells[0].text], []
        cells.reverse()
        rows.append(Row(" ".join(label_tokens).strip(), cells, cy, page_no, ln[0][0] if ln else 0.0))
    return rows


def merge_split_rows(rows: list[Row]) -> list[Row]:
    """Attach figures printed on their own line to the label printed just below (or above) them."""
    out: list[Row] = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if r.has_values and not r.label:
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            if nxt is not None and nxt.label and not nxt.has_values:
                out.append(Row(nxt.label, r.cells, r.y, r.page, nxt.label_x))
                i += 2
                continue
            if out and out[-1].label and not out[-1].has_values:
                prev = out.pop()
                out.append(Row(prev.label, r.cells, r.y, r.page, prev.label_x))
                i += 1
                continue
        out.append(r)
        i += 1
    # labels wrapped over two lines, with the figures on either the first or the last line
    joined: list[Row] = []
    for r in out:
        last: Row | None = joined[-1] if joined else None
        continues = bool(r.label) and (r.label[0].islower() or r.label.startswith("(")) and not _ENUM.match(r.label)
        if last is not None and continues and last.label and r.page == last.page and r.y - last.y < 24:
            if not r.has_values:  # "Net cash from investing  (6.80) …" / "activities"
                last.label = f"{last.label} {r.label}"
                continue
            if not last.has_values:  # "Net cash (used in)/generated" / "from operating activities  2,217.25 …"
                joined[-1] = Row(f"{last.label} {r.label}", r.cells, r.y, r.page, last.label_x)
                continue
        joined.append(r)
    return joined


_ENUM = re.compile(r"^\(?([a-z]|[ivx]{1,4}|\d{1,2})[.)]\s")


def is_year_row(r: Row) -> bool:
    """A header line of bare years ("2026 2025 2024") is parsed as figures; it is not data."""
    return bool(r.cells) and all(re.fullmatch(r"(19|20)\d{2}", c.text) for c in r.cells)


def column_centres(rows: list[Row]) -> list[float]:
    """Horizontal centres of the figure columns, from the rows that have the most figures."""
    if not rows:
        return []
    counts = Counter(len(r.cells) for r in rows if len(r.cells) >= 2)
    if not counts:
        n = max((len(r.cells) for r in rows), default=0)
        if n == 0:
            return []
    else:
        # the most common figure count is the column count; rows with an extra token (e.g. a "(1)" marker) are outliers
        top = max(counts.values())
        n = max(k for k, v in counts.items() if v >= top * 0.5)
    full = [r for r in rows if len(r.cells) == n]
    return [sum(r.cells[k].x for r in full) / len(full) for k in range(n)]


def align(rows: list[Row], centres: list[float], tol: float = 40.0) -> None:
    """Assign each row's figures to the nearest column (rows with missing cells keep their place)."""
    for r in rows:
        r.columns = {}
        if len(r.cells) == len(centres):
            r.columns = dict(enumerate(r.cells))
            continue
        for c in r.cells:
            k = min(range(len(centres)), key=lambda j: abs(centres[j] - c.x))
            if abs(centres[k] - c.x) <= tol and k not in r.columns:
                r.columns[k] = c


def header_text_by_column(page: Any, centres: list[float], y_limit: float, y_from: float = 0.0) -> list[str]:
    """Header words above ``y_limit`` grouped into the figure column they sit over."""
    out: list[list[str]] = [[] for _ in centres]
    words = sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    if not centres:
        return []
    half = (min(centres[i + 1] - centres[i] for i in range(len(centres) - 1)) / 2) if len(centres) > 1 else 60.0
    for x0, y0, x1, y1, text, *_ in words:
        cy = (y0 + y1) / 2
        if cy >= y_limit or cy < y_from:
            continue
        cx = (x0 + x1) / 2
        k = min(range(len(centres)), key=lambda j: abs(centres[j] - cx))
        if abs(centres[k] - cx) <= half + 12:
            out[k].append(text)
    return [" ".join(t) for t in out]
