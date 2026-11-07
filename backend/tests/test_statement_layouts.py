"""Statement layouts seen in real prospectuses that the parser used to leave unverified (regression cases).

Each test builds a one- or two-page PDF reproducing one layout. Corpus result when these were fixed (139 stored
offer documents): verified periods 228 -> 303, no previously verified period lost or changed, one sign error corrected.
"""
from __future__ import annotations

from typing import Any

import pymupdf
import pytest

from app.financials.statement_parser import (
    TITLES,
    Figure,
    Period,
    PeriodStatement,
    StatementTable,
    derive,
    extract_financials,
    norm_label,
    parse_statement,
    pbt_agreement,
    statement_title,
    table_score,
    validate,
)
from tests.rhp_builder import _header, _row

E_L = [10_000.0, 9_000.0, 8_000.0, 7_000.0]


def _pdf(pages: list[Any]) -> Any:
    doc = pymupdf.open()
    for build in pages:
        build(doc.new_page())
    return doc


def _bs_page(title: str, rows: list[tuple[str, list[float] | None]], *, heading_last: bool = False) -> Any:
    def build(page: Any) -> None:
        y = 130.0
        if not heading_last:
            y = _header(page, title)
        for label, values in rows:
            _row(page, y, label, values)
            y += 14
        if heading_last:  # the PDF's text stream carries the heading block after the table, as in some prospectuses
            _header(page, title)
    return build


def test_label_variants():
    assert norm_label("Less: Current Tax") == "current tax" and norm_label("Add: Deferred Tax") == "deferred tax"
    assert norm_label("Total (1+2+3+4)") == "total"


def test_sub_total_layout_and_grand_totals():
    # Indian GAAP layout: sections close with "Sub-Total", the sides with a bare "TOTAL" (document 19)
    rows = [("Shareholders' funds", None), ("Share capital", [1_000.0] * 4), ("Reserves and surplus", [4_000.0, 3_500.0, 3_000.0, 2_500.0]),
            ("Sub-Total", [5_000.0, 4_500.0, 4_000.0, 3_500.0]), ("Non-current liabilities", None), ("Long-term borrowings", [2_000.0] * 4),
            ("Sub-Total", [2_000.0] * 4), ("Current liabilities", None), ("Short-term borrowings", [3_000.0, 2_500.0, 2_000.0, 1_500.0]),
            ("Sub-Total", [3_000.0, 2_500.0, 2_000.0, 1_500.0]), ("TOTAL", E_L), ("Non-current assets", None), ("Property, plant and equipment", [4_000.0] * 4),
            ("Sub-Total", [4_000.0] * 4), ("Current assets", None), ("Trade receivables", [6_000.0, 5_000.0, 4_000.0, 3_000.0]),
            ("Sub-Total", [6_000.0, 5_000.0, 4_000.0, 3_000.0]), ("TOTAL", E_L)]
    doc = _pdf([_bs_page("Restated Statement of Assets and Liabilities", rows)])
    t = parse_statement(doc, 0, "bs", "unknown")
    assert t is not None
    got = {f: t.figures[(f, 0)].value for f in ("total_equity", "non_current_liabilities", "current_liabilities", "non_current_assets",
                                                  "current_assets", "total_assets", "total_equity_and_liabilities")}
    assert got == {"total_equity": 50.0, "non_current_liabilities": 20.0, "current_liabilities": 30.0, "non_current_assets": 40.0,
                   "current_assets": 60.0, "total_assets": 100.0, "total_equity_and_liabilities": 100.0}  # lakhs -> crore
    assert table_score(t)[1:3] == (0, 8)  # no failed check; both balance-sheet identities hold in all four periods


def test_side_totals_by_formula_and_by_two_equal_bare_totals():
    # "Total (1+2+3+4)" is the whole side, even when the last section header carried a subtotal (document 63)
    formula = [("A) EQUITY AND LIABILITIES", None), ("3 Non Current Liabilities", None), ("Long-term borrowings", [2_000.0] * 4),
               ("4 Current Liabilities", [2_000.0] * 4), ("Trade payables", [3_000.0] * 4), ("Total (1+2+3+4)", E_L), ("B) ASSETS", None),
               ("1. Non Current Assets", None), ("Property, plant and equipment", [4_000.0] * 4), ("2. Current Assets", [4_000.0] * 4),
               ("Total (1+2)", E_L)]
    t = parse_statement(_pdf([_bs_page("Restated Statement of Assets and Liabilities", formula)]), 0, "bs", "unknown")
    assert t is not None and t.figures[("total_assets", 1)].value == 90.0 and t.figures[("total_equity_and_liabilities", 1)].value == 90.0
    assert ("non_current_liabilities", 0) not in t.figures  # the side total is not mistaken for a section total
    # two bare "TOTAL" rows with equal figures and unlabelled section subtotals; heading printed after the table (document 23)
    bare = [("I EQUITY AND LIABILITIES", None), ("Share capital", [1_000.0] * 4), ("TOTAL", E_L), ("II ASSETS", None),
            ("Trade receivables", [6_000.0] * 4), ("TOTAL", E_L)]
    doc = _pdf([_bs_page("Annexure-I Restated Financial Statement", bare, heading_last=True)])
    assert statement_title(doc[0].get_text(), TITLES["bs"]) is not None  # no standard title, but the table opens with E&L
    assert statement_title("Our Business\nWe make compounds\nThe balance of trade", TITLES["bs"]) is None
    t = parse_statement(doc, 0, "bs", "unknown")
    assert t is not None and t.figures[("total_assets", 2)].value == 80.0 and t.figures[("total_equity_and_liabilities", 2)].value == 80.0


def _ps(**values: float) -> PeriodStatement:
    ps = PeriodStatement("unknown", __import__("datetime").date(2026, 3, 31), 12, "FY2026")
    for k, v in values.items():
        ps.figures[k] = Figure(k, v, str(v), k, 1, "crore")
    return ps


def test_tax_summed_from_printed_lines_confirms_pat():
    ps = _ps(pbt=154.766, tax_current=40.166, tax_earlier=0.0, tax_deferred=-0.971, pat=115.571)  # "Less: Current Tax", "Add: Deferred Tax"
    derive(ps)
    validate(ps)
    chk = next(c for c in ps.checks if c["check"] == "pat_reconciles")
    assert ps.derived["tax_expense"][0] == pytest.approx(39.195) and chk["passed"] and chk["hard"]
    # a tax line the parser did not recognise: recorded, but it does not fail the period
    ps = _ps(pbt=154.766, tax_current=40.166, pat=100.0)
    derive(ps)
    validate(ps)
    chk = next(c for c in ps.checks if c["check"] == "pat_reconciles")
    assert not chk["passed"] and not chk["hard"] and ps.validation_status != "failed"
    # a printed total tax line still fails hard when PAT does not reconcile
    ps = _ps(pbt=154.766, tax_expense=40.0, pat=100.0)
    validate(ps)
    assert ps.validation_status == "failed"


def _cf(page: int, pbt_values: list[float]) -> StatementTable:
    t = StatementTable("cf", page, "unknown", "crore", [Period(i, __import__("datetime").date(2026 - i, 3, 31), 12, f"FY{2026 - i}") for i in range(3)])
    for i, v in enumerate(pbt_values):
        t.figures[("pbt_cf", i)] = Figure("pbt_cf", v, str(v), "Profit before tax", page, "crore")
    return t


def test_cash_flow_is_paired_with_the_pl_it_agrees_with():
    pl = StatementTable("pl", 332, "unknown", "crore", _cf(0, []).periods)
    for i, v in enumerate([36.0, 28.0, 10.0]):
        pl.figures[("pbt", i)] = Figure("pbt", v, str(v), "Profit before tax", 332, "crore")
    summary, restated = _cf(90, [36.4, 27.0, 9.0]), _cf(335, [36.0, 28.0, 10.0])
    assert pbt_agreement(pl, summary) == 0 and pbt_agreement(pl, restated) == 3


def test_whole_document_with_split_heading_and_tax_lines():
    """A P&L whose tax is printed only as current + deferred, next to a balance sheet in the Sub-Total layout."""
    pl_rows = [("Revenue from operations", [5_000.0] * 4), ("Other income", [100.0] * 4), ("Total income", [5_100.0] * 4),
               ("Total expenses", [4_000.0] * 4), ("Profit before tax", [1_100.0] * 4), ("Tax expense:", None),
               ("Less: Current Tax", [300.0] * 4), ("Add: Deferred Tax", [(-20.0)] * 4), ("Profit for the year", [820.0] * 4)]
    cf_rows = [("Profit before tax", [1_100.0] * 4), ("Net cash from operating activities", [900.0] * 4)]
    bs_rows = [("Shareholders' funds", None), ("Share capital", [1_000.0] * 4), ("Sub-Total", [5_000.0] * 4), ("Current liabilities", None),
               ("Trade payables", [5_000.0] * 4), ("Sub-Total", [5_000.0] * 4), ("TOTAL", [10_000.0] * 4), ("Current assets", None),
               ("Trade receivables", [10_000.0] * 4), ("Sub-Total", [10_000.0] * 4), ("TOTAL", [10_000.0] * 4)]
    doc = _pdf([_bs_page("Restated Statement of Assets and Liabilities", bs_rows),
                _bs_page("Restated Statement of Profit and Loss", pl_rows, heading_last=True),
                _bs_page("Restated Statement of Cash Flows", cf_rows)])
    r = extract_financials(doc)
    assert r.status == "extracted"
    fy = next(p for p in r.periods if p.label == "FY2026")
    assert fy.validation_status == "passed", fy.checks
    assert {c["check"] for c in fy.checks if c["hard"] and c["passed"]} >= {"balance_sheet_balances", "pat_reconciles"}


def test_total_equity_includes_non_controlling_interests():
    # consolidated balance sheet: the owners' share is printed before the total (documents 41, 49, 55, ...)
    rows = [("Equity share capital", [1_000.0] * 4), ("Other equity", [6_000.0] * 4),
            ("Total equity attributable to equity holders of the Holding Company", [7_000.0] * 4),
            ("Non-controlling interests", [100.0] * 4), ("Total equity", [7_100.0] * 4),
            ("Total non-current liabilities", [1_000.0] * 4), ("Total current liabilities", [1_900.0] * 4),
            ("Total equity and liabilities", [10_000.0] * 4), ("Total assets", [10_000.0] * 4)]
    t = parse_statement(_pdf([_bs_page("Restated Consolidated Statement of Assets and Liabilities", rows)]), 0, "bs", "unknown")
    assert t is not None and t.figures[("total_equity", 0)].value == 71.0  # not the owners' 70.0
    assert table_score(t)[1] == 0  # equity + liabilities = assets holds
