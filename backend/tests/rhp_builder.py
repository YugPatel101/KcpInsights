"""Build a small synthetic offer document (PDF) laid out like a real RHP's restated financials.

Used by the extraction tests so they run offline without shipping a 10 MB prospectus. The layout
mirrors patterns seen in real documents: figures right of the label, one column per period,
bracketed negatives, "-" for nil, a header split over two lines, Indian GAAP section totals and a
listed-peer comparison table.
"""
from __future__ import annotations

from typing import Any

import pymupdf

COLS = [330, 400, 470, 540]  # x of each figure column
FY = ["FY2024", "FY2025", "FY2026"]

# ₹ lakhs; three fiscal years + a 3-month stub (column order: stub, FY26, FY25, FY24)
DEFAULT = {
    "share_capital": [500.00, 500.00, 400.00, 400.00],
    "reserves": [2_100.00, 1_900.00, 1_400.00, 1_000.00],
    "lt_borrowings": [600.00, 650.00, 700.00, 750.00],
    "dtl": [20.00, 18.00, 15.00, 12.00],
    "st_borrowings": [300.00, 280.00, 260.00, 240.00],
    "trade_payables": [450.00, 420.00, 380.00, 300.00],
    "other_cl": [130.00, 132.00, 145.00, 98.00],
    "ppe": [2_000.00, 1_950.00, 1_700.00, 1_500.00],
    "other_nca": [100.00, 100.00, 80.00, 60.00],
    "inventories": [800.00, 760.00, 700.00, 600.00],
    "receivables": [900.00, 850.00, 700.00, 500.00],
    "cash": [0.0, 0.0, 0.0, 0.0],  # set by derived() as the balancing figure
    "other_ca": [100.00, 100.00, 100.00, 100.00],
    "revenue": [2_500.00, 9_000.00, 7_500.00, 6_000.00],
    "other_income": [20.00, 60.00, 50.00, 40.00],
    "materials": [1_500.00, 5_400.00, 4_600.00, 3_800.00],
    "employee": [300.00, 1_100.00, 950.00, 800.00],
    "finance": [40.00, 150.00, 160.00, 170.00],
    "depreciation": [50.00, 190.00, 170.00, 150.00],
    "other_exp": [330.00, 1_220.00, 1_000.00, 820.00],
    "tax": [75.00, 250.00, 170.00, 75.00],
    "cfo": [300.00, 900.00, -150.00, 400.00],
    "capex": [-80.00, -440.00, -370.00, -300.00],
    "cfi": [-80.00, -440.00, -370.00, -300.00],
    "cff": [-210.00, -390.00, 500.00, -120.00],
}


def _fmt(v: float) -> str:
    if v == 0:
        return "-"
    s = f"{abs(v):,.2f}"
    return f"({s})" if v < 0 else s


def derived(d: dict[str, list[float]]) -> dict[str, list[float]]:
    """Totals consistent with the inputs, so every accounting check passes unless a test breaks one."""
    out: dict[str, list[float]] = {}
    z = range(4)
    out["equity"] = [d["share_capital"][i] + d["reserves"][i] for i in z]
    out["ncl"] = [d["lt_borrowings"][i] + d["dtl"][i] for i in z]
    out["cl"] = [d["st_borrowings"][i] + d["trade_payables"][i] + d["other_cl"][i] for i in z]
    out["e_and_l"] = [out["equity"][i] + out["ncl"][i] + out["cl"][i] for i in z]
    out["nca"] = [d["ppe"][i] + d["other_nca"][i] for i in z]
    # cash is the balancing figure so that assets = equity + liabilities in every period
    d["cash"] = [round(out["e_and_l"][i] - out["nca"][i] - d["inventories"][i] - d["receivables"][i] - d["other_ca"][i], 2) for i in z]
    out["ca"] = [d["inventories"][i] + d["receivables"][i] + d["cash"][i] + d["other_ca"][i] for i in z]
    out["assets"] = [out["nca"][i] + out["ca"][i] for i in z]
    out["total_income"] = [d["revenue"][i] + d["other_income"][i] for i in z]
    out["total_exp"] = [d["materials"][i] + d["employee"][i] + d["finance"][i] + d["depreciation"][i] + d["other_exp"][i] for i in z]
    out["pbt"] = [out["total_income"][i] - out["total_exp"][i] for i in z]
    out["pat"] = [out["pbt"][i] - d["tax"][i] for i in z]
    return out


def _row(page: Any, y: float, label: str, values: list[float] | None, bold: bool = False) -> None:
    page.insert_text((50, y), label, fontsize=8, fontname="hebo" if bold else "helv")
    if values is not None:
        for x, v in zip(COLS, values, strict=True):
            t = _fmt(v)
            page.insert_text((x - len(t) * 2.2, y), t, fontsize=8)


def _header(page: Any, title: str, y0: float = 60) -> float:
    page.insert_text((50, y0), title, fontsize=11, fontname="hebo")
    page.insert_text((50, y0 + 16), "(Rs. in Lakhs)", fontsize=8)
    # header split over two lines, as in many prospectuses
    for x, t in zip(COLS, ["30 June", "31 March", "31 March", "31 March"], strict=True):
        page.insert_text((x - 22, y0 + 34), t, fontsize=8)
    for x, t in zip(COLS, ["2026", "2026", "2025", "2024"], strict=True):
        page.insert_text((x - 10, y0 + 44), t, fontsize=8)
    page.insert_text((50, y0 + 44), "Particulars", fontsize=8)
    return y0 + 64


def build_rhp(path: str, values: dict[str, list[float]] | None = None, *, company: str = "Testco Industries Limited",
              break_balance_sheet: bool = False) -> dict[str, list[float]]:
    d = {k: list(v) for k, v in {**DEFAULT, **(values or {})}.items()}
    t = derived(d)
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((50, 80), f"{company} — Red Herring Prospectus (synthetic test document)", fontsize=10)
    p.insert_text((50, 110), "Equity shares outstanding prior to the Issue 5,000,000 Equity Shares of face value Rs 10 each", fontsize=8)
    p.insert_text((50, 130), "We derived 62.10% and 58.40%, 55.00% and 50.00% of our revenue from our top ten customers for three months", fontsize=8)
    p.insert_text((50, 140), "period ended June 30, 2026, and for the Fiscals 2026, 2025 and 2024, respectively.", fontsize=8)
    p.insert_text((50, 160), "There are no qualifications by the Statutory Auditors which have not been given effect to.", fontsize=8)

    # balance sheet (Indian GAAP style section totals)
    p = doc.new_page()
    y = _header(p, "ANNEXURE - I RESTATED STATEMENT OF ASSETS AND LIABILITIES")
    eq_total = list(t["equity"])
    if break_balance_sheet:
        eq_total = [eq_total[0], eq_total[1] + 25.0, eq_total[2], eq_total[3]]  # an extraction-style error in one period
    for label, vals in (("EQUITY AND LIABILITIES", None), ("Shareholders' Funds", None), ("Share Capital", d["share_capital"]),
                        ("Reserves and Surplus", d["reserves"]), ("Total", eq_total), ("Non-Current Liabilities", None),
                        ("Long-term borrowings", d["lt_borrowings"]), ("Deferred tax liabilities", d["dtl"]), ("Total", t["ncl"]),
                        ("Current Liabilities", None), ("Short-term borrowings", d["st_borrowings"]), ("Trade payables", d["trade_payables"]),
                        ("Other current liabilities", d["other_cl"]), ("Total", t["cl"]), ("Total Equity and Liabilities", t["e_and_l"]),
                        ("ASSETS", None), ("Non-Current Assets", None), ("Property, plant and equipment", d["ppe"]),
                        ("Other non-current assets", d["other_nca"]), ("Total", t["nca"]), ("Current Assets", None),
                        ("Inventories", d["inventories"]), ("Trade receivables", d["receivables"]), ("Cash and cash equivalents", d["cash"]),
                        ("Other current assets", d["other_ca"]), ("Total", t["ca"]), ("Total Assets", t["assets"])):
        _row(p, y, label, vals, bold=vals is None)
        y += 14

    # profit and loss
    p = doc.new_page()
    y = _header(p, "ANNEXURE - II RESTATED STATEMENT OF PROFIT AND LOSS")
    for label, vals in (("1 Revenue from operations", d["revenue"]), ("2 Other income", d["other_income"]), ("3 Total income", t["total_income"]),
                        ("4 Expenses", None), ("Cost of materials consumed", d["materials"]), ("Employee benefits expense", d["employee"]),
                        ("Finance costs", d["finance"]), ("Depreciation and amortisation expense", d["depreciation"]),
                        ("Other expenses", d["other_exp"]), ("5 Total expenses", t["total_exp"]), ("6 Profit before tax", t["pbt"]),
                        ("7 Total tax expense", d["tax"]), ("8 Profit for the year", t["pat"]),
                        ("Basic (Rs)", [round(t["pat"][i] * 1e5 / (d["share_capital"][i] * 1e5 / 10), 2) for i in range(4)])):
        _row(p, y, label, vals, bold=vals is None)
        y += 14

    # cash flow
    p = doc.new_page()
    y = _header(p, "ANNEXURE - III RESTATED STATEMENT OF CASH FLOWS")
    for label, vals in (("Profit before tax", t["pbt"]), ("Net cash from operating activities (A)", d["cfo"]),
                        ("Purchase of property, plant and equipment", d["capex"]), ("Net cash used in investing activities (B)", d["cfi"]),
                        ("Net cash from/(used in) financing activities (C)", d["cff"])):
        _row(p, y, label, vals)
        y += 14

    # listed peers (Basis for Issue Price)
    p = doc.new_page()
    p.insert_text((50, 60), "BASIS FOR ISSUE PRICE", fontsize=11, fontname="hebo")
    p.insert_text((50, 80), "Comparison of accounting ratios with listed industry peers", fontsize=9)
    heads = ["Revenue", "Face", "Closing", "EPS", "EPS", "NAV", "P/E", "RoNW"]
    heads2 = ["(Rs Lakhs)", "Value", "price", "Basic", "Diluted", "", "", "(%)"]
    px = [230, 275, 320, 365, 410, 455, 500, 545]
    for x, h, h2 in zip(px, heads, heads2, strict=True):
        p.insert_text((x - 12, 100), h, fontsize=7)
        p.insert_text((x - 12, 110), h2, fontsize=7)
    p.insert_text((50, 110), "Name of the company", fontsize=7)
    rows = [(company, [9000.00, 10, None, 3.0, 3.0, 52.0, None, 9.0]), ("Listed peers", None),
            ("Alpha Metals Limited", [12000.00, 2, 300.00, 15.00, 15.00, 100.00, 20.00, 15.0]),
            ("Beta Steels Limited", [8000.00, 10, 450.00, 18.00, 18.00, 150.00, 25.00, 12.0]),
            ("Gamma Coatings Limited", [5000.00, 1, 90.00, 3.00, 3.00, 30.00, 30.00, 10.0])]
    y = 130
    for name, vals in rows:
        p.insert_text((50, y), name, fontsize=7)
        if vals:
            for x, v in zip(px, vals, strict=True):
                t2 = "NA" if v is None else (f"{v:,.2f}" if isinstance(v, float) else str(v))
                p.insert_text((x - len(t2) * 1.8, y), t2, fontsize=7)
        y += 14
    p.insert_text((50, y + 10), "The above information for listed industry peers is on a standalone basis for the year ended March 31, 2026.", fontsize=7)
    doc.save(path)
    doc.close()
    return {**d, **t}
