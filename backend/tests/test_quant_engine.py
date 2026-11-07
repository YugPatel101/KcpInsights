"""Quantitative engine: every formula checked against hand calculations."""
from __future__ import annotations

from datetime import date

import pytest

from app.services import quant_engine as qe
from app.services.scoring_config import ConfigError, get_default_config, validate_config

CFG = get_default_config()


def fy(year: int, **kw) -> qe.FinPeriod:
    return qe.FinPeriod(label=f"FY{year}", period_end=date(year, 3, 31), months=12, basis="consolidated", data_status="verified",
                        validation_status="passed", **kw)


BASE = dict(revenue=1000.0, ebitda=200.0, ebit=150.0, pbt=130.0, pat=100.0, depreciation=50.0, interest_expense=20.0, eps_basic=5.0,
            total_assets=1200.0, current_assets=600.0, current_liabilities=300.0, total_equity=500.0, total_debt=250.0,
            cash_and_equivalents=80.0, inventory=150.0, operating_cash_flow=120.0, capex=40.0)


def periods() -> list[qe.FinPeriod]:
    a = fy(2024, **{**BASE, "revenue": 640.0, "pat": 50.0, "ebitda": 120.0, "total_equity": 400.0, "total_assets": 1000.0, "current_liabilities": 250.0,
                    "eps_basic": 2.5, "operating_cash_flow": 60.0})
    b = fy(2025, **{**BASE, "revenue": 800.0, "pat": 80.0, "ebitda": 160.0, "total_equity": 420.0, "total_assets": 1100.0, "current_liabilities": 280.0,
                    "eps_basic": 4.0, "operating_cash_flow": 90.0})
    c = fy(2026, **BASE)
    return [a, b, c]


def issue(**kw) -> qe.IssueTerms:
    return qe.IssueTerms(company_name="X", sector="S", issue_type="mainboard", price_band_low=90.0, price_band_high=100.0,
                         pre_issue_shares=8_000_000.0, fresh_issue_cr=20.0, **kw)


def inputs(ps=None, peers=None, **kw) -> qe.EngineInputs:
    return qe.EngineInputs(issue=issue(**kw), periods=ps if ps is not None else periods(), peers=peers or [], facts=qe.RiskFacts(), as_of=date(2026, 10, 1))


def test_profitability_ratios_use_average_balances():
    m, _ = qe.compute_metrics(periods(), issue(), [], CFG)
    assert m["roe"].value == pytest.approx(100 / ((500 + 420) / 2) * 100)  # 21.739 %
    assert m["roce"].value == pytest.approx(150 / (((1200 - 300) + (1100 - 280)) / 2) * 100)  # EBIT / avg(TA − CL)
    assert m["net_margin"].value == pytest.approx(10.0)
    assert m["ebitda_margin"].value == pytest.approx(20.0)
    assert m["operating_margin"].value == pytest.approx(15.0)


def test_single_period_uses_closing_balance_and_says_so():
    m, _ = qe.compute_metrics([periods()[-1]], issue(), [], CFG)
    assert m["roe"].value == pytest.approx(20.0) and "closing equity" in (m["roe"].note or "")
    assert m["revenue_cagr"].value is None and "two" in (m["revenue_cagr"].reason or "")


def test_growth_cagr_yoy_and_misleading_cases():
    m, _ = qe.compute_metrics(periods(), issue(), [], CFG)
    assert m["revenue_cagr"].value == pytest.approx(((1000 / 640) ** (1 / 2.0) - 1) * 100, rel=1e-3)  # 25 %
    assert m["pat_cagr"].value == pytest.approx(((100 / 50) ** (1 / 2.0) - 1) * 100, rel=1e-3)
    assert m["revenue_yoy"].value == pytest.approx(25.0) and m["pat_yoy"].value == pytest.approx(25.0)
    assert m["eps_growth"].value == pytest.approx(25.0)
    assert m["revenue_volatility"].value == pytest.approx(0.0)
    assert m["growth_consistency"].value == pytest.approx(100.0)  # all changes positive, zero volatility
    loss = periods()
    loss[0].pat = -10.0
    m2, _ = qe.compute_metrics(loss, issue(), [], CFG)
    assert m2["pat_cagr"].value is None and m2["pat_cagr"].status == "not_meaningful"
    assert qe.cagr(0.0, 10.0, 2)[0] is None and qe.cagr(10.0, -5.0, 2)[0] is None


def test_liquidity_leverage_and_zero_denominators():
    m, _ = qe.compute_metrics(periods(), issue(), [], CFG)
    assert m["current_ratio"].value == pytest.approx(2.0)
    assert m["quick_ratio"].value == pytest.approx((600 - 150) / 300)
    assert m["cash_ratio"].value == pytest.approx(80 / 300)
    assert m["debt_to_equity"].value == pytest.approx(0.5)
    assert m["interest_coverage"].value == pytest.approx(7.5)
    assert m["debt_to_ebitda"].value == pytest.approx(1.25)
    ps = periods()
    ps[-1].interest_expense = 0.0
    ps[-1].total_equity = -5.0
    m2, _ = qe.compute_metrics(ps, issue(), [], CFG)
    assert m2["interest_coverage"].status == "ok" and m2["interest_coverage"].value is None and "no finance costs" in m2["interest_coverage"].note
    assert m2["debt_to_equity"].status == "not_meaningful"


def test_cash_flow_metrics():
    m, _ = qe.compute_metrics(periods(), issue(), [], CFG)
    assert m["ocf_to_pat"].value == pytest.approx(1.2)
    assert m["fcf"].value == pytest.approx(80.0)
    assert m["fcf_margin"].value == pytest.approx(8.0)
    assert m["cash_conversion"].value == pytest.approx(60.0)
    assert m["cash_flow_consistency"].value == pytest.approx(100.0)


def test_valuation_on_post_issue_shares_at_the_issue_price():
    m, ctx = qe.compute_metrics(periods(), issue(), [], CFG)
    shares = 8_000_000 + 20 * 1e7 / 100  # fresh issue of ₹20 cr at the upper band = 2,000,000 shares
    assert ctx["post_issue_shares"] == pytest.approx(shares) and ctx["price_status"] == "estimated"
    eps = 100 * 1e7 / shares
    assert m["eps_post_issue"].value == pytest.approx(eps)
    assert m["pe"].value == pytest.approx(100 / eps)  # 10x
    assert m["pb"].value == pytest.approx(100 / ((500 + 20) * 1e7 / shares))
    mcap = 100 * shares / 1e7
    assert m["market_cap"].value == pytest.approx(100.0) and mcap == pytest.approx(100.0)
    assert m["ev_ebitda"].value == pytest.approx((mcap + 250 - 80 - 20) / 200)
    loss = periods()
    loss[-1].pat = -1.0
    loss[-1].ebitda = -1.0
    m2, _ = qe.compute_metrics(loss, issue(), [], CFG)
    assert m2["pe"].status == "not_meaningful" and m2["ev_ebitda"].status == "not_meaningful"
    m3, _ = qe.compute_metrics(periods(), qe.IssueTerms(company_name="X", sector="S", issue_type="sme"), [], CFG)
    assert m3["pe"].reason == "issue price not yet published"


def test_normalisation_and_config_validation():
    assert qe.normalize(12.5, {"kind": "linear", "zero": 0, "full": 25}) == 50.0
    assert qe.normalize(1.0, {"kind": "linear", "zero": 2.0, "full": 0.0}) == 50.0  # lower is better
    band = {"kind": "band", "lo": 1.2, "hi": 3.0, "zero_low": 0.5, "zero_high": 6.0}
    assert qe.normalize(2.0, band) == 100 and qe.normalize(0.5, band) == 0 and qe.normalize(4.5, band) == 50
    validate_config(CFG)
    bad = get_default_config()
    bad["weights"]["overall"]["growth"] = 0.5
    with pytest.raises(ConfigError):
        validate_config(bad)


def test_overall_score_formula_and_classification():
    r = qe.compute(inputs(), CFG)
    w = CFG["weights"]["overall"]
    comps = {k: v["score"] for k, v in r["components"].items()}
    assert all(v is not None for v in comps.values())
    assert r["composite"] == pytest.approx(sum(w[k] * comps[k] for k in w), abs=0.02)
    assert r["status"] == "complete" and r["classification"] in [lbl for _, lbl in CFG["classification"]]
    assert r["coverage"] == 100.0


def test_no_overall_score_without_required_inputs_and_renormalised_without_valuation():
    r = qe.compute(inputs(ps=periods()[-1:]), CFG)  # growth needs two years
    assert r["composite"] is None and r["status"] == "insufficient" and "Growth" in r["fundamental"]["reason"]
    no_price = qe.EngineInputs(issue=qe.IssueTerms(company_name="X", sector="S", issue_type="sme"), periods=periods(), peers=[],
                               facts=qe.RiskFacts(), as_of=date(2026, 10, 1))
    r2 = qe.compute(no_price, CFG)
    assert r2["components"]["valuation"]["score"] is None and r2["composite"] is not None
    assert r2["status"] == "partial" and r2["fundamental"]["renormalized"] and "Valuation" in r2["fundamental"]["excluded"]


def test_bases_never_mixed_and_unverified_or_failed_periods_not_scored():
    ps = periods()
    standalone = [qe.FinPeriod(**{**p.__dict__, "basis": "standalone", "revenue": 1.0}) for p in ps[:2]]
    basis, chosen = qe.choose_basis(ps + standalone, set(CFG["usable_statuses"]))
    assert basis == "consolidated" and all(p.basis == "consolidated" for p in chosen)
    ps[-1].data_status = "extracted"  # read but not confirmed by an accounting check
    ps[-2].validation_status = "failed"
    _, chosen2 = qe.choose_basis(ps, set(CFG["usable_statuses"]))
    assert [p.label for p in chosen2] == ["FY2024"]


def test_peer_median_drives_relative_valuation():
    peers = [qe.PeerMultiple(name=n, pe=pe, pb=None, ronw_pct=None, basis="standalone", period_label="FY2026", data_status="verified")
             for n, pe in (("a", 20.0), ("b", 30.0), ("c", 1000.0))]  # the outlier does not move the median
    r = qe.compute(inputs(peers=peers), CFG)
    assert r["peers"]["median_pe"] == 30.0
    item = next(i for i in r["components"]["valuation"]["items"] if i["key"] == "pe")
    premium = (10.0 / 30.0 - 1) * 100
    assert item["score"] == pytest.approx(qe.normalize(premium, CFG["ranges"]["relative_premium"]), abs=0.01)
    one = qe.compute(inputs(peers=peers[:1]), CFG)
    assert one["peers"]["median_pe"] is None and "fewer than" in one["peers"]["note"]


def test_risk_score_excludes_missing_and_higher_means_riskier():
    facts = qe.RiskFacts(customer_concentration_pct=80.0, auditor_qualifications="none")
    r = qe.compute(qe.EngineInputs(issue(), periods(), [], facts, date(2026, 10, 1)), CFG)
    comps = {c["key"]: c for c in r["risk"]["components"]}
    assert comps["customer_concentration"]["points"] == 100.0 and comps["auditor_qualifications"]["points"] == 0.0
    assert comps["contingent_liabilities"]["available"] is False and comps["governance"]["available"] is False
    avail = [c for c in r["risk"]["components"] if c["available"]]
    expected = sum(c["weight"] * c["points"] for c in avail) / sum(c["weight"] for c in avail)
    assert r["risk"]["score"] == pytest.approx(expected, abs=0.01)
    leveraged = periods()
    leveraged[-1].total_debt = 1250.0  # D/E 2.5x
    r2 = qe.compute(qe.EngineInputs(issue(), leveraged, [], facts, date(2026, 10, 1)), CFG)
    assert r2["risk"]["score"] > r["risk"]["score"]


def test_price_sensitivity_and_determinism():
    rows = qe.price_sensitivity(inputs(), CFG)
    assert [x["label"] for x in rows] == ["lower end of band", "upper end of band"]
    assert rows[0]["pe"] < rows[1]["pe"]
    assert qe.compute(inputs(), CFG)["input_fingerprint"] == qe.compute(inputs(), CFG)["input_fingerprint"]


def test_risk_is_not_scored_from_data_quality_alone():
    """Regression: an IPO with no usable statements or disclosures showed 'elevated risk' from missing data alone."""
    cfg = get_default_config()
    inputs = qe.EngineInputs(issue=qe.IssueTerms(company_name="X", sector="Unclassified", issue_type="sme", price_band_high=100.0),
                             periods=[], peers=[], facts=qe.RiskFacts(), as_of=date(2026, 10, 31))
    r = qe.compute(inputs, cfg)
    assert r["risk"]["score"] is None and r["risk"]["level"] is None and r["risk"]["reason"]
    assert next(c for c in r["risk"]["components"] if c["key"] == "data_quality")["available"]
