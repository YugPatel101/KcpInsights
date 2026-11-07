"""Issue-data completeness: NSE field variants, offer-document terms, official fallbacks and the key-facts list.

Regression cases come from real gaps: BLS Polymers' face value was published by NSE as "Re. 10 per Equity Share" and lost;
every SME issue lost its lot size because SME pages title it "Lot Size" instead of "Bid Lot"; the old share-count pattern
read authorised capital or the post-offer count as the pre-issue share count.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.financials.disclosures import pre_issue_shares
from app.financials.offer_terms import extract_offer_terms, listing_exchanges, objects_of_issue, promoter_holding_pre, promoters
from app.ingestion import normalizer as nz
from app.ingestion.financial_store import StoreStats, store_facts, store_offer_terms
from app.ingestion.http import PoliteClient
from app.ingestion.ingestion_scheduler import IngestionRunner
from app.ingestion.ipo_data_service import UpsertStats, apply_shareholding, set_field
from app.ingestion.sources.base import ShareholdingRecord
from app.ingestion.sources.nse import NSEEquityList, NSEOfficialSource, NSEShareholdingSource
from app.models import Company, FieldObservation, IPOIssue, SourceDocument

FIX = Path(__file__).parent / "fixtures" / "nse"
TODAY = date(2026, 11, 2)

# ----------------------------------------------------------------------------- offer-document pages (as PDF text layers print them)
COVER = """CORPORATE IDENTITY NUMBER: U24111DL1991PLC042745 REGISTERED OFFICE 604, Indra Prakash, New Delhi
Website: www.blspolymers.com
E-mail:
corporate@blspolymers.com
OUR PROMOTERS: VINOD AGGARWAL, SUSHIL AGGARWAL, MADHUKAR AGGARWAL AND KARAN AGGARWAL
DETAILS OF ISSUE TO PUBLIC Type Fresh Issue size Up to 1,70,00,000 Equity Shares of face
value of ₹ 10 each aggregating up to ₹ [•] lakhs
The face value of our Equity Shares is ₹ 10 each. The Floor Price, Cap Price and Issue Price ...
LISTING The Equity Shares, when issued through this Red Herring Prospectus, are proposed to be listed on the Stock Exchanges
being National Stock Exchange of India Limited ("NSE") and BSE Limited ("BSE"). Our Company has received 'in-principle'
approvals from BSE and NSE. BOOK RUNNING LEAD MANAGER Unistone Capital www.unistonecapital.com REGISTRAR KFin www.kfintech.com
RED HERRING PROSPECTUS 100% Book Built Issue"""
CAPITAL = """A AUTHORIZED SHARE CAPITAL 7,00,00,000 Equity Shares of face value of ₹ 10 each 7,000.00
B ISSUED, SUBSCRIBED AND PAID-UP SHARE CAPITAL BEFORE THE ISSUE 4,50,31,834 Equity Shares of face value of ₹ 10 each 4,503.18
C PROPOSED ISSUE Issue of up to 1,70,00,000 Equity Shares D ISSUED, SUBSCRIBED AND PAID-UP CAPITAL AFTER THE ISSUE [•] Equity Shares"""
PATTERN = """3. Shareholding Pattern of our Company Category (I) Category of Shareholder (II) ...
(A) Promote r s and Promoter Group 14 4,43,70,6 83 - - 4,43,70, 683 98.53 4,43,70,6 83 - 4,43,70,6 83 98.5 3
(B) Public 49 6,61,151 - - 6,61,151 1.47 6,61,151 - 6,61,151 1.47 (C) Non Promoter - Non Public - - -"""
OBJECTS = """OBJECTS OF THE ISSUE Requirement of Funds and Utilisation of Net Proceeds The Net Proceeds are proposed to be utilised and
deployed in accordance with the estimated schedule as specified below: (₹ in lakhs) Particulars Amount(1) Financing the capital
expenditure requirement towards expansion of our Manufacturing Facility 7,756.07 Funding working capital requirements of our
Company 8,950.00 General Corporate Purposes(1) [●] Net Proceeds(1) [●] (1)To be finalised upon determination of the Issue Price."""


def _pages(**over: str) -> list[str]:
    pages = [COVER] + ["Definitions and abbreviations"] * 24 + [CAPITAL, PATTERN, OBJECTS]
    for k, v in over.items():
        pages[{"cover": 0, "capital": 25, "pattern": 26, "objects": 27}[k]] = v
    return pages


# ----------------------------------------------------------------------------- normaliser
def test_rupee_prefixes_issue_method_and_short_years():
    assert nz.parse_rupees_per_share("Re. 10 per Equity Share") == 10.0  # BLS Polymers (regression)
    assert nz.parse_rupees_per_share("Re.1") == 1.0
    assert nz.parse_rupees_per_share("Rs.5 per Equity Share") == 5.0
    assert nz.parse_rupees_per_share("₹ 2 each") == 2.0 and nz.parse_rupees_per_share("INR 1") == 1.0
    assert nz.parse_rupees_per_share("ten rupees") is None
    assert nz.parse_issue_method("Book Building") == "book_built" and nz.parse_issue_method("Fixed Price") == "fixed_price"
    assert nz.parse_issue_method("NA") is None
    assert nz.parse_date("22-Oct-26") == date(2026, 10, 22)  # NSE SME equity list
    assert nz.parse_issue_components("Fresh Issue aggregating up to ₹ 255 crore") == {"fresh_cr": 255.0}


@pytest.mark.parametrize("text, expected", [
    # real NSE issue-size sentences that were left unparsed
    ("Initial Public Offering of upto 42,67,200 fresh equity shares (Including market maker portion of 2,14,400 equity shares)",
     {"fresh_shares": 4267200.0}),
    ("Fresh Issue up to 58,90,800 Equity Shares and Offer for Sale up to 7,14,000 (Including market maker portion of 3,31,200 Equity Shares)",
     {"fresh_shares": 5890800.0, "ofs_shares": 714000.0}),
    ("Initial Public offer comprising of Fresh issue up to 9,897,000 and offer for sale up to 1,350,000 Equity Shares",
     {"fresh_shares": 9897000.0, "ofs_shares": 1350000.0}),  # "Re" inside "fresh" is not a rupee sign (regression)
    ("Initial Public Offering comprising of Fresh offer 38,46,000 Equity Shares (including Anchor Allocation of 10,62,000 Equity Shares)",
     {"fresh_shares": 3846000.0}),
    ("Initial Public Offer comprising of fresh issue aggregating up to 3200 million and offer for sale up to 14,306,785 Equity shares",
     {"fresh_cr": 320.0, "ofs_shares": 14306785.0}),
    ("Initial Public Offer of 45,56,400 Equity Shares at the aggregating to 4,283.02 lakhs.", {"total_shares": 4556400.0, "total_cr": pytest.approx(42.8302)}),
    ("Initial Public Offer of 16,98,000 Equity Shares (Including Market Maker portion of 85,200 Equity Shares)", {"total_shares": 1698000.0}),
    ("Fresh Issue of 50 lakh equity shares", None),  # lakh of shares, not rupees: refused rather than misread
])
def test_issue_size_sentence_variants(text, expected):
    assert nz.parse_issue_components(text) == expected


def test_whole_issue_size_sets_the_total_but_not_an_invented_split(db):
    ipo = _ipo(db, price_band_high=67.0, issue_size_text="Initial Public Offer of 16,98,000 Equity Shares (Including Market Maker portion)")
    from app.ingestion.ipo_data_service import apply_issue_size
    from app.models import utcnow

    apply_issue_size(db, ipo, source_key="nse_ipo", source_url=None, now=utcnow(), stats=UpsertStats())
    assert ipo.issue_size_cr == pytest.approx(16_98_000 * 67 / 1e7) and ipo.fresh_issue_cr is None and ipo.ofs_cr is None


# ----------------------------------------------------------------------------- NSE adapters
def _detail(renames: dict[str, str], values: dict[str, str]) -> dict:
    d = copy.deepcopy(json.loads((FIX / "detail.json").read_text()))
    for row in d["issueInfo"]["dataList"]:
        t = row.get("title")
        if t in renames:
            row["title"] = t = renames[t]
        if t in values:
            row["value"] = values[t]
    return d


def _nse(payload: object) -> NSEOfficialSource:
    return NSEOfficialSource(PoliteClient(min_interval=0, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)),
                                          sleep=lambda s: None))


def test_detail_page_variants_mainboard_and_sme():
    rec, _ = _nse(_detail({}, {"Face Value": "Re. 10 per Equity Share"})).fetch_ipo_details("BLSPOLY", "EQ").data  # type: ignore[misc]
    assert rec.face_value == 10.0 and rec.lot_size == 182 and rec.issue_method == "book_built" and rec.final_issue_price is None
    sme = _detail({"Bid Lot": "Lot Size"}, {"Lot Size": "1200 Equity Shares", "Face Value": "Rs.5 per Equity Share",
                                            "Issue Type": "Fixed Price", "Price Range": "Rs.80 per equity share"})
    rec, _ = _nse(sme).fetch_ipo_details("RAVITA", "SME").data  # type: ignore[misc]
    assert rec.lot_size == 1200 and rec.face_value == 5.0  # SME pages title the lot "Lot Size" (regression)
    assert rec.issue_method == "fixed_price" and rec.price_band_low == rec.price_band_high == rec.final_issue_price == 80.0


def test_unpublished_subscription_multiple_is_not_stored_as_zero():
    # NSE's consolidated block for some closed SME issues: bids but no shares offered and "0" times (35 issues showed 0.00x)
    rows = [{"srNo": "1", "category": "Qualified Institutional Buyers(QIBs)", "noOfShareOffered": "0", "noOfSharesBid": "26012400", "noOfTime": "0"},
            {"srNo": "2", "category": "Non Institutional Investors", "noOfShareOffered": "0", "noOfSharesBid": "0", "noOfTime": "0"},
            {"srNo": "3", "category": "Retail Individual Investors(RIIs)", "noOfShareOffered": "1000", "noOfSharesBid": "0", "noOfTime": "0"},
            {"category": "Total", "noOfShareOffered": "2000", "noOfSharesBid": "5000", "noOfTime": "2.5"}]
    recs = NSEOfficialSource.parse_subscription(rows, "Updated as on 16-Oct-2026 19:00:00")
    assert [(r.category, r.times_subscribed) for r in recs] == [("retail", 0.0), ("total", 2.5)]  # a real 0x (shares offered, none bid) is kept


def test_shareholding_and_equity_list_parsers():
    rows = [{"date": "30-SEP-2026", "pr_and_prgrp": "89.35", "public_val": "10.65", "broadcastDate": "12-OCT-2026 19:25:28"},
            {"date": "30-JUN-2026", "pr_and_prgrp": "89.35", "public_val": "10.65"},
            {"date": "bad", "pr_and_prgrp": "x"}]
    recs = NSEShareholdingSource.parse(rows, "CORDELIA", "u")
    assert [r.as_of for r in recs] == [date(2026, 6, 30), date(2026, 9, 30)] and recs[0].promoter_pct == 89.35
    assert NSEShareholdingSource.parse({"error": "x"}, "X", "u") == []
    main = "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\nBLSPOLY,BLS Polymers Limited,EQ,03-NOV-2026,10,1,INE0ABC01011,10\n"
    sme = "SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,PAID_UP_VALUE,ISIN_NUMBER,FACE_VALUE,\nRAVITA,Ravita Engineering Services Limited,ST,22-Oct-26,5,INE1UEL01023,5,\n"
    assert NSEEquityList.parse_records(main)["BLSPOLY"] == {"name": "BLS Polymers Limited", "series": "EQ", "isin": "INE0ABC01011",
                                                            "face_value": 10.0, "listing_date": date(2026, 11, 3)}
    r = NSEEquityList.parse_records(sme)["RAVITA"]
    assert r["face_value"] == 5.0 and r["isin"] == "INE1UEL01023" and r["listing_date"] == date(2026, 10, 22)


# ----------------------------------------------------------------------------- offer-document terms
def test_offer_terms_from_cover_capital_structure_and_objects():
    texts = _pages()
    t = extract_offer_terms(texts)
    assert t["face_value"].value == 10.0 and t["issue_method"].value == "book_built"
    assert t["listing_exchanges"].value == "NSE, BSE"
    assert t["promoters"].value == ["Vinod Aggarwal", "Sushil Aggarwal", "Madhukar Aggarwal", "Karan Aggarwal"]
    assert t["website"].value == "www.blspolymers.com" and t["email"].value == "corporate@blspolymers.com"  # not the BRLM's
    assert t["promoter_holding_pre_pct"].value == 98.53 and t["promoter_holding_pre_pct"].page == 27  # split words, wrapped digits
    rows = t["objects_of_issue"].value
    assert [r["amount_cr"] for r in rows] == [pytest.approx(77.5607), pytest.approx(89.5), None]  # lakhs -> crore; [●] stays None
    assert rows[0]["purpose"].startswith("Financing the capital expenditure") and rows[-1]["purpose"] == "General Corporate Purposes"
    p = pre_issue_shares(texts)
    assert p is not None and p.value == 45031834  # not the authorised 7,00,00,000 (regression)
    assert "post_issue_shares" not in t  # printed as [•]


def test_offer_terms_variants_and_refusals():
    assert listing_exchanges(["are proposed to be listed on the SME Platform of National Stock Exchange of India Limited (“NSE EMERGE”)."]).value == "NSE Emerge"
    assert listing_exchanges(["proposed to be listed on a recognised stock exchange being BSE Limited (“BSE”)."]).value == "BSE"
    assert extract_offer_terms(["Up to [●] Equity Shares of face value ₹5 each aggregating up to ₹4,500.00 million"])["face_value"].value == 5.0
    assert promoters(["THE PROMOTERS OF OUR COMPANY: MR. JAI AGARWAL, MRS. PREMLATA AGARWAL, AND MS. AANYA AGARWAL DETAILS OF THE OFFER"]).value == [
        "Jai Agarwal", "Premlata Agarwal", "Aanya Agarwal"]
    assert promoters(["Our Company does not have an identifiable promoter."]).value == []
    # promoter and public rows that do not add up are refused, never guessed
    bad = "(A) Promoters and Promoter Group 4 1,06,42,300 - - 1,06,42,300 60.00 (B) Public 167 4,47,35,100 - - 4,47,35,100 10.00 (C) Non"
    assert promoter_holding_pre([bad]) is None
    a1a2 = ("A1 Promoter 5 1,62,18,764 - - 1,62,18,764 99.99% 1,62,18,764 A2 Promoter Group 3 135 - - 135 0.00% 135 "
            "B Public - - - - - C Non- Promoter- Non-Public - -")
    assert promoter_holding_pre([a1a2]).value == 99.99
    whole = "(A) Promoters and Promoter Group 9 243,578,096 - - 243,578,096 100 243,578,096 (B) Public - - - - - - (C) Non"
    assert promoter_holding_pre([whole]).value == 100.0
    numbered = ["x"] * 21 + ["OBJECTS OF THE OFFER The Net Proceeds are proposed to be utilized in the following manner: 1. Funding incremental "
                             "working capital requirements of our Company; and 2. Repayment of borrowings availed by our Company; and 3. General "
                             "corporate purposes. (collectively, referred to herein as “Objects”)"]
    rows = objects_of_issue(numbered).value
    assert [r["purpose"] for r in rows] == ["Funding incremental working capital requirements of our Company",
                                            "Repayment of borrowings availed by our Company", "General corporate purposes"]
    assert all(r["amount_cr"] is None for r in rows)
    sme_post = "Equity Shares outstanding after the Offer 1,55,16,763 Equity Shares having face value of ₹10/- each"
    assert extract_offer_terms([sme_post])["post_issue_shares"].value == 15516763


# ----------------------------------------------------------------------------- storage, derivation and precedence
def _ipo(db, **kw) -> IPOIssue:
    company = Company(name="BLS Polymers Limited", sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="NSE", issue_type="mainboard", data_mode="source", data_status="verified",
                   nse_symbol="BLSPOLY", risk_disclosures_reviewed=False, **kw)
    db.add(ipo)
    db.flush()
    return ipo


def _doc(db, ipo: IPOIssue, key: str = "nse_rhp") -> SourceDocument:
    doc = SourceDocument(ipo_id=ipo.id, title="RHP", doc_type="rhp", sha256="s" + key, mime_type="application/pdf", data_status="verified",
                         source_key=key, archive_url="https://nsearchives.nseindia.com/content/ipo/RHP_BLSPOLY.zip")
    db.add(doc)
    db.flush()
    return doc


def _store(db, ipo: IPOIssue, doc: SourceDocument, texts: list[str]) -> None:
    from app.financials.disclosures import Disclosure

    p = pre_issue_shares(texts)
    store_facts(db, ipo, doc, {"pre_issue_shares": p} if p else dict[str, Disclosure](), StoreStats())
    store_offer_terms(db, ipo, doc, extract_offer_terms(texts), StoreStats())
    db.commit()


def test_store_offer_terms_derives_post_issue_figures_for_a_fresh_issue(db):
    text = "Initial Public Offer comprising of Fresh Issue aggregating upto 1,70,00,000 Equity Shares (including Anchor portion)"
    ipo = _ipo(db, issue_size_text=text, fresh_issue_cr=255.0, ofs_cr=0.0, issue_size_cr=255.0, price_band_high=150.0)
    _store(db, ipo, _doc(db, ipo), _pages())
    assert ipo.face_value == 10.0 and ipo.issue_method == "book_built" and ipo.listing_exchanges == "NSE, BSE"
    assert ipo.pre_issue_shares == 45031834 and ipo.post_issue_shares == 45031834 + 17000000  # exact: share count, no price needed
    assert ipo.promoter_holding_pre_pct == 98.53
    assert ipo.promoter_holding_post_pct == pytest.approx(98.53 * 45031834 / 62031834, abs=0.01)
    assert ipo.use_of_proceeds and ipo.use_of_proceeds[1]["amount_cr"] == pytest.approx(89.5)
    assert ipo.company.website == "https://www.blspolymers.com"
    obs = db.execute(select(FieldObservation).where(FieldObservation.ipo_id == ipo.id, FieldObservation.field == "promoter_holding_post_pct")).scalar_one()
    assert obs.source_key == "nse_rhp:derived" and "fresh issue only" in (obs.basis or "")
    facts = ipo.document_facts or {}
    assert facts["face_value"]["page"] == 1 and facts["offer_terms_version"]["value"]

    # the shareholding pattern filed with NSE for listing replaces the derivation; the latest filing is kept as well
    ipo.listing_date = date(2026, 11, 3)
    recs = [ShareholdingRecord("BLSPOLY", date(2026, 11, 2), 71.4, 28.6, None, "u"), ShareholdingRecord("BLSPOLY", date(2026, 12, 31), 70.9, 29.1, None, "u")]
    st = apply_shareholding(db, ipo, recs)
    assert st.fields_changed == 1 and ipo.promoter_holding_post_pct == 71.4
    assert ipo.document_facts["shareholding_latest"]["value"] == 70.9
    # re-reading the document later does not derive over the filed figure
    _store(db, ipo, _doc(db, ipo), _pages())
    latest = db.execute(select(FieldObservation).where(FieldObservation.ipo_id == ipo.id, FieldObservation.field == "promoter_holding_post_pct")
                        .order_by(FieldObservation.id.desc()).limit(1)).scalar_one()
    assert latest.source_key == "nse_shareholding" and ipo.promoter_holding_post_pct == 71.4


def test_post_issue_promoter_holding_is_not_derived_when_promoters_may_sell(db):
    ipo = _ipo(db, fresh_issue_cr=100.0, ofs_cr=50.0, issue_size_cr=150.0, price_band_high=150.0)
    _store(db, ipo, _doc(db, ipo), _pages())
    assert ipo.promoter_holding_pre_pct == 98.53 and ipo.promoter_holding_post_pct is None
    assert apply_shareholding(db, ipo, [ShareholdingRecord("X", date(2026, 6, 30), 60.0, 40.0, None, "u")]).fields_changed == 0  # no listing date


def test_face_value_stated_two_ways_is_refused():
    assert "face_value" not in extract_offer_terms(_pages(cover=COVER.replace("₹ 10 each", "₹ 2 each")))  # 2 vs 10: ambiguous


def test_nse_value_keeps_precedence_over_a_sebi_copy(db):
    ipo = _ipo(db)
    set_field(db, ipo, "face_value", 10.0, source_key="nse_ipo", source_url=None, status="verified", stats=UpsertStats())
    _store(db, ipo, _doc(db, ipo, "sebi_drhp"), _pages(cover=COVER.replace("₹ 10 each", "₹ 2 each"), capital=CAPITAL.replace("₹ 10 each", "₹ 2 each")))
    assert ipo.face_value == 10.0
    conflict = db.execute(select(FieldObservation).where(FieldObservation.ipo_id == ipo.id, FieldObservation.field == "face_value",
                                                         FieldObservation.source_key == "sebi_drhp")).scalar_one()
    assert conflict.applied is False and conflict.conflict is True


# ----------------------------------------------------------------------------- jobs: weekly gap re-checks and official fallbacks
class FakeNSE:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if request.url.path == "/api/ipo-detail":
            sme = _detail({"Bid Lot": "Lot Size"}, {"Lot Size": "1200 Equity Shares", "Face Value": "Rs.5 per Equity Share"})
            sme["metaInfo"] = {"isin": "INE1UEL01023"}
            return httpx.Response(200, json=sme)
        if "corporate-share-holdings-master" in url:
            return httpx.Response(200, json=[{"date": "21-OCT-2026", "pr_and_prgrp": "53.46", "public_val": "46.54"}])
        if url.endswith("SME_EQUITY_L.csv"):
            return httpx.Response(200, text="SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,PAID_UP_VALUE,ISIN_NUMBER,FACE_VALUE,\n"
                                            "OLDSME,Old SME Limited,ST,01-Jul-26,10,INE9XYZ01015,10,\n")
        if url.endswith("EQUITY_L.csv"):
            return httpx.Response(200, text="SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n")
        return httpx.Response(404)


@pytest.fixture()
def runner(db, tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings

    monkeypatch.setenv("KCP_CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    fake = FakeNSE()
    client = PoliteClient(min_interval=0, backoff_base=0, transport=httpx.MockTransport(fake), sleep=lambda _s: None)
    r = IngestionRunner(sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False), client=client, today=lambda: TODAY)
    r.fake = fake  # type: ignore[attr-defined]
    yield r
    get_settings.cache_clear()


def _listed(db, symbol: str, issue_type: str = "sme", **kw) -> IPOIssue:
    company = Company(name=f"{symbol} Limited", sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="NSE Emerge", issue_type=issue_type, data_mode="source", data_status="verified",
                   nse_symbol=symbol, risk_disclosures_reviewed=False, open_date=date(2026, 10, 14), close_date=date(2026, 10, 16),
                   listing_date=date(2026, 10, 22), listing_date_status="actual", price_band_low=105.0, price_band_high=112.0, **kw)
    db.add(ipo)
    db.commit()
    return ipo


def test_listed_issue_with_gaps_is_rechecked_weekly(db, runner):
    ipo = _listed(db, "RAVITA")
    r = runner.run("details", "test")
    assert r["status"] == "success" and r["detail"]["gap_rechecks"] == 1
    db.refresh(ipo)
    assert ipo.lot_size == 1200 and ipo.face_value == 5.0 and ipo.isin == "INE1UEL01023" and ipo.details_checked_at is not None
    ipo.lot_size = None  # a field still missing: not fetched again within the week
    db.commit()
    assert runner.run("details", "test")["detail"]["fetched"] == 0
    ipo.details_checked_at -= timedelta(days=8)
    db.commit()
    assert runner.run("details", "test")["detail"]["fetched"] == 1


def test_enrichment_fills_face_value_isin_and_post_issue_promoter_holding(db, runner):
    old = _listed(db, "OLDSME")
    ravita = _listed(db, "RAVITA", face_value=5.0, isin="INE1UEL01023")
    r = runner.run("enrichment", "test")
    assert r["status"] == "success", r
    db.refresh(old)
    db.refresh(ravita)
    assert old.face_value == 10.0 and old.isin == "INE9XYZ01015"
    assert ravita.promoter_holding_post_pct == 53.46  # pattern as of the day before listing
    assert old.promoter_holding_post_pct == 53.46 and ravita.shareholding_checked_at is not None
    calls = len(runner.fake.calls)  # type: ignore[attr-defined]
    assert runner.run("enrichment", "test")["status"] == "skipped"  # found, nothing left to fetch
    assert len(runner.fake.calls) == calls  # type: ignore[attr-defined]


def test_issue_facts_give_a_value_source_or_reason_for_every_field(db, client):
    ipo = _ipo(db, open_date=date(2026, 10, 27), close_date=date(2026, 10, 29), price_band_low=142.0, price_band_high=150.0, lot_size=100,
               fresh_issue_cr=255.0, ofs_cr=0.0, issue_size_cr=255.0,
               issue_size_text="Initial Public Offer comprising of Fresh Issue aggregating upto 1,70,00,000 Equity Shares")
    _store(db, ipo, _doc(db, ipo), _pages())
    facts = {f["key"]: f for f in client.get(f"/api/ipos/{ipo.id}").json()["issue_facts"]}
    assert facts["face_value"]["value"] == 10.0 and facts["face_value"]["source"] == "NSE RHP" and facts["face_value"]["page"] == 1
    assert facts["lot_value"]["value"] == 15000 and facts["lot_value"]["status"] == "estimated"  # 100 × ₹150 upper band
    assert facts["promoter_holding_post"]["status"] == "derived"
    assert facts["promoters"]["value"][0] == "Vinod Aggarwal"
    assert facts["pe_pre"]["value"] is None and "annual statements" in facts["pe_pre"]["reason"]
    for f in facts.values():
        assert f["value"] is not None or f["reason"], f  # never blank without a reason
        assert f["value"] != 0 or f["key"] == "issue_split"

    # statements read as printed but not reconciled: the P/E is shown, labelled unverified (never scored)
    from app.models import FinancialStatement

    db.add(FinancialStatement(company_id=ipo.company_id, period_label="FY2026", period_end=date(2026, 3, 31), period_months=12, pat=27.0094,
                              eps_basic=5.99, eps_diluted=5.99, data_status="extracted", is_current=True))
    db.commit()
    facts = {f["key"]: f for f in client.get(f"/api/ipos/{ipo.id}").json()["issue_facts"]}
    assert facts["pe_pre"]["value"] == pytest.approx(150 / 5.99, abs=0.01) and facts["pe_pre"]["status"] == "unverified"
    assert facts["pe_post"]["value"] == pytest.approx(62031834 * 150 / 1e7 / 27.0094, abs=0.01)
    db.query(FinancialStatement).update({"data_status": "requires_review"})
    db.commit()
    facts = {f["key"]: f for f in client.get(f"/api/ipos/{ipo.id}").json()["issue_facts"]}
    assert facts["pe_post"]["value"] is None and "failed an accounting check" in facts["pe_post"]["reason"]


@pytest.mark.parametrize("page, expected", [
    # "Offer Proceeds" wording, "Sr. No." header, whole-rupee amounts (lakhs)
    ("OBJECTS OF THE OFFER Requirement of Funds: The Offer Proceeds are proposed to be utilized towards the following objects: (₹ in Lakhs) "
     "Sr. No. Particulars Amount 1 Funding incremental working capital requirements of our Company 2,461.04 2 Repayment of certain borrowings "
     "800.00 3 General Corporate Purposes [●] Total [●]",
     [("Funding incremental working capital requirements of our Company", 24.6104), ("Repayment of certain borrowings", 8.0),
      ("General Corporate Purposes", None)]),
    # "[ ]" where the ● glyph was lost
    ("OBJECTS OF THE ISSUE The Net Proceeds are proposed to be utilized in accordance with the details provided in the following table: "
     "(₹ in Lakhs) Particulars Estimated Amount Repayment of certain outstanding borrowings availed by our Company 7,100.00 "
     "General Corporate Purposes* [ ] Total",
     [("Repayment of certain outstanding borrowings availed by our Company", 71.0), ("General Corporate Purposes", None)]),
    # header text read into the first row, ahead of the first enumerated object
    ("OBJECTS OF THE ISSUE The Net Proceeds are proposed to be deployed as set forth below: (₹ in million) Particulars Estimated amount "
     "Fiscal 2027 Fiscal 2028 1. Funding the capital expenditure for a new plant 549.29 300.00 249.29 2. General Corporate Purposes [●] [●] [●]",
     [("Funding the capital expenditure for a new plant", 54.929), ("General Corporate Purposes", None)]),
])
def test_objects_table_variants(page, expected):
    rows = objects_of_issue(["x"] * 21 + [page]).value
    assert [(r["purpose"], r["amount_cr"]) for r in rows] == [(p, pytest.approx(a) if a else None) for p, a in expected]


def test_objects_of_an_offer_for_sale_only():
    page = ("OBJECTS OF THE OFFER The objects of the Offer are to (i) carry out the Offer for Sale of [●] Equity Shares of face value of ₹ 5 "
            "each aggregating up to ₹12,000 million by the Promoter Selling Shareholder; and (ii) achieve the benefits of listing the Equity "
            "Shares on the Stock Exchanges. Our Company will not receive any proceeds from the Offer.")
    d = objects_of_issue(["x"] * 21 + [page])
    assert d is not None and "receives no proceeds" in (d.basis or "")
    assert [r["amount_cr"] for r in d.value] == [pytest.approx(1200.0), None]
    assert d.value[1]["purpose"].startswith("Achieve the benefits of listing")


@pytest.mark.parametrize("page, expected", [
    # no "(A)"/"(B)" brackets, split words and a split last decimal ("70.7 9", "28.8 0")
    ("Category Total A Promot er & Promot er Group 6 3,09,78, 500 - - 3,09,78, 500 70.7 9 3,09,78, 500 B Public 13 1,25,87, 908 - - 28.8 0 "
     "C Non Promoter", 70.79),
    # a public row longer than the window used to require a following "(C)"
    ("(A) Promoter and Promoter Group 4 299,507,360 0 0 299,507, 360 65.90 % 299,507,36 0 (B) Public 255 154,990,310 0 0 154,990, 310 "
     "34.10 % " + "0 " * 200, 65.9),
])
def test_shareholding_pattern_variants(page, expected):
    assert promoter_holding_pre([page]).value == pytest.approx(expected)


def test_company_without_a_promoter():
    rows = "(A) Promoters and Promoter Group - - - - - - - - (B) Public 227,999 1,670,555,049 - - 67.50% (C) Non Promoter- Non Public 32.50%"
    assert promoter_holding_pre([rows]) is None  # a blank row alone is not evidence of zero
    d = promoter_holding_pre(["Our Company does not have an identifiable promoter.", rows])
    assert d is not None and d.value == 0.0 and "no identifiable promoter" in (d.basis or "")
