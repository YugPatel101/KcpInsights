"""Fields filled by calculation or labelled estimate when no source publishes them (never scored, never shown as fact)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.financials.offer_terms import cover_intermediaries, proposed_offer
from app.ingestion import normalizer as nz
from app.models import Company, FinancialStatement, IPOIssue, SubscriptionSnapshot
from app.services.issue_facts import issue_facts

TODAY = date.today()


def _ipo(db, **kw) -> IPOIssue:
    company = Company(name="Testco Limited", sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="NSE", issue_type="mainboard", data_mode="source", data_status="verified",
                   risk_disclosures_reviewed=False, **kw)
    db.add(ipo)
    db.commit()
    return ipo


def _facts(db, ipo, result=None) -> dict:
    return {f["key"]: f for f in issue_facts(db, ipo, result=result)}


def test_reserved_portions_from_the_issue_size_sentence():
    assert nz.parse_reserved_portions("Fresh Issue of 1,03,62,000 Equity Shares (Including Market Maker portion of 5,22,000 Equity Shares and "
                                      "Anchor allocation of 29,48,400 Equity Shares)") == {"market_maker": 522000.0, "anchor": 2948400.0}
    assert nz.parse_reserved_portions("Fresh Issue aggregating up to Rs. 100 crore") == {}


def test_proposed_offer_on_a_draft_cover():
    shares = ["DETAILS OF THE OFFER TO THE PUBLIC Type Fresh Issue Size Offer for Sale size Total Offer size Fresh Issue and Offer for Sale "
              "Up to 31,93,500 Equity Shares of face value of ₹10 each, aggregating up to ₹ [●] Lakhs Up to 15,00,000 Equity Shares of face value "
              "of ₹10 each aggregating up to ₹ [●] Lakhs Up to 46,93,500 Equity Shares of face value of ₹10 each aggregating up to ₹ [●] Lakhs "
              "The Offer is being made pursuant to Regulation 6(2)"]
    assert proposed_offer(shares).value == {"fresh_shares": 3193500.0, "fresh_cr": None, "ofs_shares": 1500000.0, "ofs_cr": None,
                                            "total_shares": 4693500.0, "total_cr": None}
    rupees = ["DETAILS OF THE OFFER Fresh Issue and Offer for Sale [●] Equity Shares of face value of ₹10 each aggregating up to ₹6,980.00 million "
              "[●] Equity Shares of face value of ₹10 each aggregating up to ₹3,020.00 million [●] Equity Shares of face value of ₹10 each "
              "aggregating up to ₹10,000.00 million The Offer is being made"]
    v = proposed_offer(rupees).value
    assert (v["fresh_cr"], v["ofs_cr"], v["total_cr"]) == (698.0, 302.0, 1000.0)
    bad = [rupees[0].replace("₹10,000.00 million", "₹9,000.00 million")]
    assert proposed_offer(bad) is None  # parts that do not add up are refused


def test_cover_intermediaries_match_known_names_only():
    cover = ["BOOK RUNNING LEAD MANAGERS Mefcom Capital Markets Limited Kotak Mahindra Capital Company Limited REGISTRAR TO THE OFFER "
             "MUFG Intime India Private Limited (formerly Link Intime India Private Limited) Contact person ..."]
    out = cover_intermediaries(cover, ["MUFG Intime India Private Limited"],
                               ["Kotak Mahindra Capital Company Limited", "Capital Markets (India) Private Limited", "Mefcom Capital Markets Limited",
                                "Axis Capital Limited"])
    assert out["registrar"].value == "MUFG Intime India Private Limited"
    # "Capital Markets (India)" is generic and inside "Mefcom Capital Markets": not listed; Axis is not on the cover
    assert out["lead_managers"].value == "Mefcom Capital Markets Limited, Kotak Mahindra Capital Company Limited"


def test_estimates_for_an_unlisted_book_built_issue(db):
    # base rate from listed issues on record
    for _ in range(3):
        _ipo(db, price_band_low=90.0, price_band_high=100.0, final_issue_price=100.0, listing_date=TODAY - timedelta(days=30),
             listing_date_status="actual", open_date=TODAY - timedelta(days=40), close_date=TODAY - timedelta(days=38))
    ipo = _ipo(db, issue_method="book_built", open_date=TODAY - timedelta(days=3), close_date=TODAY - timedelta(days=1), price_band_low=140.0,
               price_band_high=150.0, pre_issue_shares=40_000_000, promoter_holding_pre_pct=80.0, fresh_issue_cr=150.0, ofs_cr=75.0,
               issue_size_text="Fresh Issue of 1,00,00,000 Equity Shares and Offer for Sale of 50,00,000 Equity Shares "
                               "(including Anchor portion of 45,00,000 Equity Shares)")
    ipo.post_issue_shares = 50_000_000
    db.commit()
    f = _facts(db, ipo)
    assert f["final_issue_price"]["value"] == 150.0 and f["final_issue_price"]["status"] == "estimated"
    assert f["final_issue_price"]["basis"].startswith("3 of 3 listed book-built issues")
    assert f["shares_offered"]["value"] == 10_500_000 and "anchor" in f["shares_offered"]["basis"]  # 1.5 cr − 45 lakh anchor
    # promoters held 3.2 cr shares; the 50 lakh offered for sale may all be theirs (low) or none (high)
    assert f["promoter_holding_post"]["unit"] == "pct_range" and f["promoter_holding_post"]["value"] == [pytest.approx(54.0), pytest.approx(64.0)]


def test_bidder_shares_from_stored_bid_details_and_derived_eps(db):
    ipo = _ipo(db, open_date=TODAY - timedelta(days=60), close_date=TODAY - timedelta(days=58), listing_date=TODAY - timedelta(days=55),
               listing_date_status="actual", price_band_low=95.0, price_band_high=100.0, final_issue_price=100.0, pre_issue_shares=10_000_000,
               post_issue_shares=12_000_000)
    db.add(SubscriptionSnapshot(ipo_id=ipo.id, as_of=TODAY - timedelta(days=58), category="total", times_subscribed=3.0, data_status="verified",
                                shares_offered=1_400_000, shares_bid=4_200_000))
    db.add(FinancialStatement(company_id=ipo.company_id, period_label="FY2026", period_end=date(2026, 3, 31), period_months=12, pat=10.0,
                              data_status="verified", is_current=True))
    db.commit()
    f = _facts(db, ipo)
    assert f["shares_offered"]["value"] == 1_400_000 and f["shares_offered"]["source"] == "NSE bid details (consolidated)"
    assert f["pe_pre"]["value"] == pytest.approx(100 / 10.0)  # EPS ₹10 = PAT ₹10 cr ÷ 1 cr shares (no EPS line printed)
    assert "no EPS line printed" in f["pe_pre"]["basis"]


def test_comparison_with_listed_peers(db):
    ipo = _ipo(db, open_date=TODAY - timedelta(days=60), close_date=TODAY - timedelta(days=58), listing_date=TODAY - timedelta(days=55),
               listing_date_status="actual", price_band_low=95.0, price_band_high=100.0, final_issue_price=100.0)
    result = {"peers": {"median_pe": 30.0, "with_pe": 4}, "metrics": {"pe": {"value": 20.0}}}
    f = _facts(db, ipo, result)
    assert f["peer_premium"]["value"] == pytest.approx(-33.3, abs=0.1) and f["peer_premium"]["status"] == "estimated"
    assert f["peer_price"]["value"] == pytest.approx(150.0) and "not a forecast" in f["peer_price"]["basis"]
    # before any price: an indicative equity value from verified profit
    pipe = _ipo(db)
    db.add(FinancialStatement(company_id=pipe.company_id, period_label="FY2026", period_end=date(2026, 3, 31), period_months=12, pat=50.0,
                              data_status="verified", is_current=True))
    db.commit()
    g = _facts(db, pipe, {"peers": {"median_pe": 30.0, "with_pe": 3}, "metrics": {}})
    assert g["peer_value"]["value"] == pytest.approx(1500.0) and g["peer_value"]["status"] == "estimated"
    assert _facts(db, pipe, {"peers": {"median_pe": None}, "metrics": {}})["peer_premium"]["reason"].startswith("fewer than two")


def test_proposed_terms_of_a_pipeline_issue(db):
    ipo = _ipo(db, pre_issue_shares=30_000_000, promoter_holding_pre_pct=100.0)
    ipo.document_facts = {"offer_terms_version": {"value": "1.3"}, "proposed_offer": {
        "value": {"fresh_shares": 0.0, "fresh_cr": 0.0, "ofs_shares": 6_000_000.0, "ofs_cr": None, "total_shares": 6_000_000.0, "total_cr": None},
        "page": 1, "document_id": None}}
    db.commit()
    f = _facts(db, ipo)
    assert f["issue_split"]["status"] == "proposed" and f["total_shares"]["value"] == 6_000_000
    assert f["promoter_holding_post"]["value"] == [pytest.approx(80.0), pytest.approx(100.0)]  # an offer for sale only adds no shares
    for fact in f.values():
        assert fact["value"] is not None or fact["reason"], fact
