"""Mode A — synthetic demonstration fixtures.

Every company, number and peer below is FICTIONAL. The records are loaded through the
same validated import pipeline as user data, with ``data_status = synthetic`` and
``data_mode = demo``, so the UI labels them and they earn no evidence credit.
Dates are generated relative to the seed date so the demo always contains
upcoming, open, closed and listed issues.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, DataMode, IPOIssue, SourceDocument
from app.services.import_service import commit_bundle, validate_bundle

SRC = "demo"


def _latest_fy_end(today: date) -> date:
    """Most recent 31 March at least ~4 months before today (audited results plausibly exist)."""
    y = today.year if today >= date(today.year, 7, 31) else today.year - 1
    return date(y, 3, 31)


def _periods(today: date, revenues: list[float], ebitda_m: list[float], *, da_pct: float, interest: list[float],
             tax: float, ocf_conv: list[float], capex_pct: float, debt: list[float], cash: list[float],
             equity0: float, dividend_pct: float = 0.0) -> list[dict[str, Any]]:
    end = _latest_fy_end(today)
    n = len(revenues)
    out = []
    equity = equity0
    for i, rev in enumerate(revenues):
        pe = date(end.year - (n - 1 - i), 3, 31)
        ebitda = rev * ebitda_m[i] / 100
        ebit = ebitda - rev * da_pct / 100
        pbt = ebit - interest[i]
        pat = pbt * (1 - tax) if pbt > 0 else pbt
        equity = equity + pat * (1 - dividend_pct)
        ocf = ebitda * ocf_conv[i] - max(pbt, 0) * tax
        liabilities = debt[i] + rev * 0.18
        assets = liabilities + equity
        out.append({
            "period_label": f"FY{pe.year}",
            "period_end": pe.isoformat(),
            "period_months": 12,
            "revenue": round(rev, 2),
            "ebitda": round(ebitda, 2),
            "ebit": round(ebit, 2),
            "pat": round(pat, 2),
            "operating_cash_flow": round(ocf, 2),
            "capex": round(rev * capex_pct / 100, 2),
            "interest_expense": round(interest[i], 2),
            "total_assets": round(assets, 2),
            "total_liabilities": round(liabilities, 2),
            "total_debt": round(debt[i], 2),
            "cash_and_equivalents": round(cash[i], 2),
            "total_equity": round(equity, 2),
            "current_assets": round(rev * 0.35 + cash[i], 2),
            "current_liabilities": round(rev * 0.2, 2),
            "source_key": SRC,
        })
    return out


def _peers(sector: str, as_of: date, base: dict[str, float], spread: list[float], names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for name, f in zip(names, spread, strict=True):
        row: dict[str, Any] = {"name": f"{name} (synthetic peer)", "sector": sector, "as_of": as_of.isoformat(),
                               "selection_reason": f"Fictional listed {sector.lower()} comparable for demonstration", "source_key": SRC}
        for k, v in base.items():
            row[k] = round(v * f, 2)
        rows.append(row)
    return rows


def _company(name: str, sector: str, industry: str, desc: str, model: str, sources: list[tuple[str, float]], conc: float | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {
        "name": name, "sector": sector, "industry": industry,
        "description": f"[SYNTHETIC] {desc}",
        "business_model": f"[SYNTHETIC] {model}",
        "revenue_sources": [{"segment": s, "share_pct": p} for s, p in sources],
    }
    if conc is not None:
        c["customer_concentration_pct"] = conc
        c["customer_concentration_basis"] = "top 5 customers"
    return c


def _issue(price: float, band_width: float, lot: int, fresh: float, ofs: float, target_mcap: float, *,
           exchange: str, issue_type: str, open_d: date, days_open: int = 2, listing_after: int = 3,
           listing_price: float | None = None, promoter_pre: float, promoter_post: float,
           reviewed: bool = True, today: date) -> dict[str, Any]:
    post_shares = round(target_mcap * 1e7 / price)
    pre_shares = round(post_shares - fresh * 1e7 / price)
    close_d = open_d + timedelta(days=days_open)
    listing_d = close_d + timedelta(days=listing_after)
    d: dict[str, Any] = {
        "exchange": exchange, "issue_type": issue_type,
        "open_date": open_d.isoformat(), "close_date": close_d.isoformat(), "listing_date": listing_d.isoformat(),
        "price_band_low": round(price - band_width, 2), "price_band_high": price, "face_value": 10 if issue_type == "mainboard" else 10,
        "lot_size": lot, "issue_size_cr": round(fresh + ofs, 2), "fresh_issue_cr": fresh, "ofs_cr": ofs,
        "pre_issue_shares": pre_shares, "post_issue_shares": post_shares,
        "promoter_holding_pre_pct": promoter_pre, "promoter_holding_post_pct": promoter_post,
        "use_of_proceeds": [
            {"purpose": "Capital expenditure", "amount_cr": round(fresh * 0.5, 2)},
            {"purpose": "Repayment of borrowings", "amount_cr": round(fresh * 0.3, 2)},
            {"purpose": "General corporate purposes", "amount_cr": round(fresh * 0.2, 2)},
        ] if fresh else [],
        "risk_disclosures_reviewed": reviewed,
        "source_key": SRC,
    }
    if listing_price is not None and listing_d <= today:
        d["final_issue_price"] = price
        d["listing_price"] = listing_price
    return d


def _subs(close_d: date, qib: float, nii: float, retail: float) -> list[dict[str, Any]]:
    ts = datetime.combine(close_d, time(17, 0)).isoformat()
    total = round(qib * 0.5 + nii * 0.15 + retail * 0.35, 2)
    return [{"as_of": ts, "category": c, "times_subscribed": v, "source_key": SRC}
            for c, v in (("qib", qib), ("nii", nii), ("retail", retail), ("total", total))]


def build_demo_bundle(today: date | None = None) -> dict[str, Any]:
    t = today or date.today()
    recent = t - timedelta(days=5)
    ipos: list[dict[str, Any]] = []

    # 1. Upcoming, healthy specialty chemicals
    o = t + timedelta(days=6)
    ipos.append({
        "company": _company("Aravalli Specialty Chemicals Ltd", "Specialty Chemicals", "Agro & pharma intermediates",
                            "Manufacturer of custom-synthesis intermediates for agrochemical and pharmaceutical customers.",
                            "B2B contract manufacturing under multi-year supply agreements; revenue billed per batch delivered.",
                            [("Agro intermediates", 58), ("Pharma intermediates", 34), ("Others", 8)], conc=46.0),
        "issue": _issue(412, 22, 36, 450, 300, 4100, exchange="NSE, BSE", issue_type="mainboard", open_d=o,
                        promoter_pre=88.0, promoter_post=68.5, today=t),
        "financials": _periods(t, [820, 965, 1140], [18.5, 19.2, 20.1], da_pct=4.0, interest=[18, 17, 15], tax=0.25,
                               ocf_conv=[0.78, 0.84, 0.88], capex_pct=6.5, debt=[240, 230, 210], cash=[45, 60, 80], equity0=620),
        "peers": _peers("Specialty Chemicals", recent, {"pe": 32.0, "ev_ebitda": 19.0, "pb": 5.2, "ps": 3.8, "market_cap_cr": 8000},
                        [0.78, 0.92, 1.05, 1.18, 1.34], ["Sindhu Fine Chem", "Narmada Synthesis", "Tapti Intermediates", "Chambal Molecules", "Ganga Crop Science"]),
        "disclosures": [
            {"category": "litigation", "severity": "low", "status": "confirmed_disclosure", "title": "Pending tax demand under appeal",
             "description": "[SYNTHETIC] Disputed indirect-tax demand of ₹6.2 cr under appeal before the tribunal.", "amount_cr": 6.2, "source_key": SRC},
            {"category": "concentration", "severity": "medium", "status": "confirmed_disclosure", "title": "Top-5 customers contribute 46% of revenue",
             "description": "[SYNTHETIC] Loss of a key customer could materially affect revenue.", "source_key": SRC},
        ],
    })

    # 2. Open now, high-growth IT with a rich valuation
    o = t - timedelta(days=1)
    ipos.append({
        "company": _company("Kaveri Cloud Systems Ltd", "Information Technology", "SaaS & cloud services",
                            "Provides cloud migration and subscription workflow software to mid-market enterprises.",
                            "Recurring SaaS subscriptions (annual contracts) plus implementation services.",
                            [("Subscriptions", 71), ("Implementation services", 29)], conc=22.0),
        "issue": _issue(565, 30, 26, 600, 900, 8200, exchange="NSE, BSE", issue_type="mainboard", open_d=o,
                        promoter_pre=61.0, promoter_post=46.0, today=t),
        "financials": _periods(t, [310, 425, 590], [16.0, 19.5, 22.0], da_pct=3.0, interest=[3, 2.5, 2], tax=0.25,
                               ocf_conv=[0.9, 0.95, 0.97], capex_pct=2.5, debt=[20, 15, 10], cash=[90, 140, 210], equity0=380),
        "peers": _peers("Information Technology", recent, {"pe": 48.0, "ev_ebitda": 30.0, "pb": 9.0, "ps": 8.0, "market_cap_cr": 15000},
                        [0.72, 0.88, 1.0, 1.12, 1.3], ["Krishna Softworks", "Yamuna Digital", "Sabarmati Infotech", "Pennar Cloud", "Mahanadi Systems"]),
        "subscriptions": [
            {"as_of": datetime.combine(o, time(17, 0)).isoformat(), "category": "qib", "times_subscribed": 0.42, "source_key": SRC},
            {"as_of": datetime.combine(o, time(17, 0)).isoformat(), "category": "nii", "times_subscribed": 1.15, "source_key": SRC},
            {"as_of": datetime.combine(o, time(17, 0)).isoformat(), "category": "retail", "times_subscribed": 1.62, "source_key": SRC},
            {"as_of": datetime.combine(o, time(17, 0)).isoformat(), "category": "total", "times_subscribed": 0.95, "source_key": SRC},
        ],
        "grey_market": [{"observed_at": datetime.combine(o, time(10, 0)).isoformat(), "premium_inr": 48.0, "source_key": SRC}],
        "disclosures": [
            {"category": "related_party", "severity": "medium", "status": "confirmed_disclosure", "title": "Office lease from promoter entity",
             "description": "[SYNTHETIC] Principal office leased from a promoter-group company at disclosed market rent.", "source_key": SRC},
        ],
    })

    # 3. Upcoming FMCG, steady
    o = t + timedelta(days=15)
    ipos.append({
        "company": _company("Nilgiri Consumer Foods Ltd", "FMCG", "Packaged foods",
                            "Regional packaged snacks and staples brand with distribution across southern India.",
                            "Branded products sold through distributors and modern trade.",
                            [("Snacks", 55), ("Staples", 37), ("Exports", 8)]),
        "issue": _issue(268, 14, 55, 250, 650, 6200, exchange="NSE, BSE", issue_type="mainboard", open_d=o,
                        promoter_pre=79.0, promoter_post=60.0, today=t),
        "financials": _periods(t, [1480, 1610, 1755], [12.0, 12.4, 12.9], da_pct=2.5, interest=[22, 20, 18], tax=0.25,
                               ocf_conv=[0.85, 0.88, 0.9], capex_pct=4.0, debt=[260, 240, 220], cash=[70, 85, 95], equity0=780),
        "peers": _peers("FMCG", recent, {"pe": 52.0, "ev_ebitda": 33.0, "pb": 10.0, "ps": 5.0, "market_cap_cr": 22000},
                        [0.8, 0.9, 1.02, 1.1, 1.25], ["Cauvery Foods", "Palar Brands", "Vaigai Consumer", "Bhima Snacks", "Tunga Staples"]),
        "disclosures": [],
    })

    # 4. Closed, awaiting listing — leveraged renewables
    o = t - timedelta(days=4)
    ipos.append({
        "company": _company("Sahyadri Renewable Power Ltd", "Renewable Energy", "Solar IPP",
                            "Develops and operates utility-scale solar plants under long-term power purchase agreements.",
                            "Tariff income from 25-year PPAs with state utilities.",
                            [("Power sales", 92), ("EPC services", 8)], conc=74.0),
        "issue": _issue(118, 6, 125, 900, 200, 7200, exchange="NSE, BSE", issue_type="mainboard", open_d=o, days_open=2, listing_after=4,
                        promoter_pre=92.0, promoter_post=72.0, today=t),
        "financials": _periods(t, [560, 640, 790], [72.0, 74.0, 75.0], da_pct=28.0, interest=[150, 168, 190], tax=0.25,
                               ocf_conv=[0.82, 0.8, 0.84], capex_pct=60.0, debt=[2800, 3300, 3900], cash=[120, 150, 210], equity0=1350),
        "peers": _peers("Renewable Energy", recent, {"pe": 60.0, "ev_ebitda": 17.0, "pb": 4.5, "ps": 12.0, "market_cap_cr": 30000},
                        [0.75, 0.9, 1.0, 1.15, 1.4], ["Western Ghats Solar", "Deccan Green Energy", "Satpura Power", "Kutch Wind", "Konkan Sun"]),
        "subscriptions": _subs(o + timedelta(days=2), 3.1, 2.2, 1.4),
        "disclosures": [
            {"category": "regulatory", "severity": "medium", "status": "confirmed_disclosure", "title": "Tariff petition pending before regulator",
             "description": "[SYNTHETIC] Tariff true-up petition for one plant pending before the state commission.", "source_key": SRC},
            {"category": "contingent_liability", "severity": "high", "status": "confirmed_disclosure", "title": "Corporate guarantees for SPV borrowings",
             "description": "[SYNTHETIC] Guarantees of ₹640 cr given for subsidiary borrowings.", "amount_cr": 640, "source_key": SRC},
        ],
    })

    listed_open = t - timedelta(days=62)
    # 5. Listed — housing finance (valued on P/B)
    ipos.append({
        "company": _company("Godavari Housing Finance Ltd", "Housing Finance", "Affordable housing loans",
                            "Lends to first-time home buyers in tier-2 and tier-3 towns.",
                            "Net interest income on a retail mortgage book funded by bank lines and NCDs.",
                            [("Interest income", 90), ("Fees", 10)]),
        "issue": _issue(305, 15, 49, 700, 400, 8600, exchange="NSE, BSE", issue_type="mainboard", open_d=listed_open,
                        listing_price=318.5, promoter_pre=70.0, promoter_post=58.0, today=t),
        "financials": _periods(t, [920, 1150, 1420], [62.0, 63.0, 63.5], da_pct=1.0, interest=[390, 480, 590], tax=0.25,
                               ocf_conv=[0.2, 0.15, 0.18], capex_pct=0.5, debt=[6200, 7700, 9400], cash=[400, 520, 640], equity0=1500, dividend_pct=0.1),
        "peers": _peers("Housing Finance", listed_open - timedelta(days=3), {"pe": 24.0, "pb": 3.2, "ps": 5.5, "market_cap_cr": 12000},
                        [0.7, 0.85, 1.0, 1.2, 1.45], ["Krishna Home Loans", "Tungabhadra Finance", "Indravati Housing", "Sharavathi Capital", "Mandakini HFC"]),
        "subscriptions": _subs(listed_open + timedelta(days=2), 48.0, 22.5, 6.8),
        "disclosures": [
            {"category": "concentration", "severity": "low", "status": "confirmed_disclosure", "title": "Geographic concentration",
             "description": "[SYNTHETIC] 62% of the loan book is in two states.", "source_key": SRC},
        ],
    })

    # 6. Listed — SME logistics
    ipos.append({
        "company": _company("Thar Logistics Ltd", "Logistics", "Road freight & warehousing",
                            "Operates a fleet of trucks and two warehouses serving FMCG distributors in western India.",
                            "Freight charges per trip and warehousing rentals.",
                            [("Freight", 78), ("Warehousing", 22)], conc=58.0),
        "issue": _issue(96, 4, 1200, 38, 6, 145, exchange="NSE Emerge", issue_type="sme", open_d=listed_open - timedelta(days=10),
                        listing_price=91.2, promoter_pre=96.0, promoter_post=70.5, today=t),
        "financials": _periods(t, [92, 118, 141], [9.5, 10.2, 11.0], da_pct=3.5, interest=[2.6, 3.0, 3.1], tax=0.25,
                               ocf_conv=[0.6, 0.7, 0.66], capex_pct=8.0, debt=[30, 36, 38], cash=[3, 4, 6], equity0=32),
        "peers": _peers("Logistics", listed_open - timedelta(days=13), {"pe": 26.0, "ev_ebitda": 13.0, "pb": 3.5, "ps": 1.6, "market_cap_cr": 2500},
                        [0.75, 0.95, 1.05, 1.25], ["Luni Transport", "Banas Freight", "Mahi Movers", "Sabari Cargo"]),
        "subscriptions": _subs(listed_open - timedelta(days=8), 12.0, 25.0, 31.0),
        "disclosures": [
            {"category": "litigation", "severity": "medium", "status": "unresolved_concern", "title": "Motor accident claims",
             "description": "[SYNTHETIC] Several motor accident claims pending; aggregate exposure not quantified in the document.", "source_key": SRC},
        ],
    })

    # 7. Listed — auto components, negative listing
    ipos.append({
        "company": _company("Brahmaputra Auto Components Ltd", "Auto Components", "Precision forgings",
                            "Supplies forged and machined components to two-wheeler and tractor OEMs.",
                            "Long-term supply contracts with price-variation clauses for steel.",
                            [("Two-wheeler", 64), ("Tractor", 28), ("Aftermarket", 8)], conc=69.0),
        "issue": _issue(244, 12, 61, 200, 520, 1350, exchange="NSE, BSE", issue_type="mainboard", open_d=listed_open + timedelta(days=12),
                        listing_price=226.0, promoter_pre=74.0, promoter_post=52.0, today=t),
        "financials": _periods(t, [1050, 990, 1120], [13.0, 11.2, 12.6], da_pct=4.5, interest=[30, 34, 33], tax=0.25,
                               ocf_conv=[0.7, 0.62, 0.75], capex_pct=7.0, debt=[410, 450, 430], cash=[35, 30, 40], equity0=760),
        "peers": _peers("Auto Components", listed_open + timedelta(days=9), {"pe": 30.0, "ev_ebitda": 15.0, "pb": 4.0, "ps": 2.2, "market_cap_cr": 9000},
                        [0.8, 0.92, 1.05, 1.2, 1.3], ["Subansiri Forge", "Teesta Engineering", "Barak Precision", "Manas Motors Parts", "Lohit Castings"]),
        "subscriptions": _subs(listed_open + timedelta(days=14), 1.4, 0.8, 1.1),
        "disclosures": [
            {"category": "promoter", "severity": "medium", "status": "confirmed_disclosure", "title": "Large offer for sale by promoters",
             "description": "[SYNTHETIC] Promoters sell ₹520 cr of shares in the OFS.", "amount_cr": 520, "source_key": SRC},
        ],
    })

    # 8. Upcoming — loss-making healthtech (P/E not meaningful)
    o = t + timedelta(days=9)
    ipos.append({
        "company": _company("Vindhya Healthtech Ltd", "Healthcare", "Diagnostics platform",
                            "Runs an app-led diagnostics and home sample-collection network.",
                            "Per-test fees from consumers and B2B corporate wellness contracts.",
                            [("Consumer diagnostics", 66), ("Corporate wellness", 34)]),
        "issue": _issue(182, 9, 82, 500, 300, 5400, exchange="NSE, BSE", issue_type="mainboard", open_d=o,
                        promoter_pre=38.0, promoter_post=29.0, today=t),
        "financials": _periods(t, [210, 330, 470], [-22.0, -9.0, -2.5], da_pct=6.0, interest=[6, 7, 7], tax=0.0,
                               ocf_conv=[1.1, 1.2, 1.4], capex_pct=9.0, debt=[60, 70, 65], cash=[180, 120, 90], equity0=520),
        "peers": _peers("Healthcare", recent, {"pe": 70.0, "ev_ebitda": 38.0, "pb": 11.0, "ps": 9.5, "market_cap_cr": 18000},
                        [0.7, 0.85, 1.0, 1.2, 1.35], ["Satluj Diagnostics", "Ravi Labs", "Beas Pathology", "Chenab Health", "Jhelum Care"]),
        "disclosures": [
            {"category": "other", "severity": "high", "status": "confirmed_disclosure", "title": "History of losses",
             "description": "[SYNTHETIC] The company has incurred losses in each of the last three fiscal years.", "source_key": SRC},
        ],
    })

    # 9. Upcoming — insufficient data (one fiscal year only, no peers)
    o = t + timedelta(days=21)
    ipos.append({
        "company": _company("Konkan Retail Ventures Ltd", "Retail", "Value fashion retail",
                            "Operates value-fashion stores in coastal Maharashtra and Goa.",
                            "Store sales of private-label apparel.", [("Apparel", 88), ("Footwear", 12)]),
        "issue": _issue(140, 7, 100, 180, 120, 2100, exchange="NSE, BSE", issue_type="mainboard", open_d=o,
                        promoter_pre=82.0, promoter_post=66.0, reviewed=False, today=t),
        "financials": _periods(t, [610], [9.0], da_pct=3.0, interest=[14], tax=0.25, ocf_conv=[0.7], capex_pct=5.0,
                               debt=[150], cash=[25], equity0=300),
        "peers": [],
        "disclosures": [],
    })

    # 10. Open — SME agro processing
    o = t - timedelta(days=1)
    ipos.append({
        "company": _company("Malwa Agro Processing Ltd", "FMCG", "Edible oils & pulses",
                            "Processes soybean and mustard into edible oils and packaged pulses.",
                            "Commodity processing margin; sold to wholesalers.", [("Edible oil", 70), ("Pulses", 30)], conc=35.0),
        "issue": _issue(72, 3, 1600, 24, 0, 96, exchange="BSE SME", issue_type="sme", open_d=o,
                        promoter_pre=100.0, promoter_post=73.4, today=t),
        "financials": _periods(t, [188, 205, 236], [5.2, 5.8, 6.1], da_pct=1.2, interest=[3.5, 3.6, 3.4], tax=0.25,
                               ocf_conv=[0.4, 0.55, 0.6], capex_pct=2.0, debt=[34, 36, 35], cash=[2, 3, 3], equity0=36),
        "peers": _peers("FMCG", recent, {"pe": 22.0, "ev_ebitda": 12.0, "pb": 2.8, "ps": 0.9, "market_cap_cr": 1200},
                        [0.75, 0.95, 1.1, 1.3], ["Chambal Oils", "Kshipra Agro", "Betwa Foods", "Parbati Pulses"]),
        "subscriptions": [
            {"as_of": datetime.combine(o, time(17, 0)).isoformat(), "category": "retail", "times_subscribed": 2.4, "source_key": SRC},
            {"as_of": datetime.combine(o, time(17, 0)).isoformat(), "category": "nii", "times_subscribed": 1.1, "source_key": SRC},
            {"as_of": datetime.combine(o, time(17, 0)).isoformat(), "category": "total", "times_subscribed": 1.8, "source_key": SRC},
        ],
        "disclosures": [],
    })

    return {
        "dataset_label": "KcpInsights synthetic demonstration fixture",
        "sources": [{
            "key": SRC,
            "title": "KcpInsights synthetic demonstration fixture (fictional companies and figures)",
            "source_type": "synthetic_fixture",
            "data_status": "synthetic",
            "notes": "Generated by app.services.demo_seed for UI and pipeline demonstration. Not real financial data.",
        }],
        "ipos": ipos,
    }


DEMO_DOCUMENT = """[SYNTHETIC DEMONSTRATION DOCUMENT — FICTIONAL CONTENT]
Aravalli Specialty Chemicals Ltd — Red Herring Prospectus (excerpt, synthetic)

\fSECTION II — RISK FACTORS
1. We depend on a limited number of customers. Our top five customers contributed 46% of revenue from operations in the latest fiscal year. Loss of any of these customers could adversely affect our business.
2. Our manufacturing facilities are concentrated in a single industrial cluster in Gujarat. Any disruption due to regulatory action, natural calamity or labour unrest could affect operations.
3. We are subject to stringent environmental regulations. Effluent discharge norms may become stricter and require additional capital expenditure.
4. There is an outstanding indirect-tax demand of ₹6.2 crore which is under appeal before the tribunal.

\fSECTION IV — OBJECTS OF THE OFFER
The net proceeds of the fresh issue of ₹450 crore are proposed to be used for: capital expenditure on a new multipurpose plant (₹225 crore), repayment of certain borrowings (₹135 crore) and general corporate purposes (₹90 crore).
The offer for sale of ₹300 crore comprises shares offered by the promoter selling shareholders; the company will not receive any proceeds from the offer for sale.

\fSECTION VI — INDUSTRY OVERVIEW
Demand for agrochemical intermediates is linked to global crop-protection volumes, which are cyclical and influenced by channel inventory. Contract manufacturing in India has grown as innovators diversify supply chains.
"""


def seed_demo(db: Session, *, reset: bool = False, today: date | None = None) -> dict[str, Any]:
    existing = db.execute(select(IPOIssue).where(IPOIssue.data_mode == DataMode.demo.value)).scalars().all()
    if existing and not reset:
        return {"skipped": True, "reason": f"{len(existing)} demo IPOs already present (use --reset)"}
    if reset:
        for ipo in existing:
            company = ipo.company
            db.delete(ipo)
            db.flush()
            if not company.ipos:
                db.delete(company)
        db.commit()
    bundle_dict = build_demo_bundle(today)
    bundle, rep = validate_bundle(bundle_dict, allow_synthetic=True, today=today)
    if bundle is None or rep.errors:
        raise RuntimeError(f"demo fixture failed validation: {rep.errors[:5]}")
    result = commit_bundle(db, bundle, rep, user_id=None, is_admin=True, filename="demo_fixture.json", data_mode=DataMode.demo.value)

    # Attach a synthetic offer-document excerpt so retrieval can be demonstrated offline.
    from app.services.rag import ingest_text_document  # local import to avoid a cycle

    aravalli = db.execute(
        select(IPOIssue).join(IPOIssue.company).where(
            IPOIssue.data_mode == DataMode.demo.value, Company.name == "Aravalli Specialty Chemicals Ltd"
        )
    ).scalars().first()
    if aravalli is not None and not db.execute(select(SourceDocument).where(SourceDocument.ipo_id == aravalli.id)).first():
        ingest_text_document(db, ipo_id=aravalli.id, title="Aravalli Specialty Chemicals — RHP excerpt (SYNTHETIC)",
                             doc_type="rhp", text=DEMO_DOCUMENT, source_url=None, user_id=None, data_status="synthetic", embed=False)
    return result
