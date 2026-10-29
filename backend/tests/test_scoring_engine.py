"""Quantitative engine tests. Expected values are written out by hand from the documented formulas."""
from __future__ import annotations

import copy
import math
from datetime import date

import pytest

from app.services import financial_metrics as fm
from app.services.normalization import (
    normalize_higher,
    normalize_lower,
    normalize_risk,
    normalize_target,
    percentile,
    winsorize,
)
from app.services.scenario import run_scenarios
from app.services.scoring_config import ConfigError, get_default_config, validate_config
from app.services.scoring_engine import (
    DisclosureInput,
    IssueInput,
    PeerInput,
    ScoringInputs,
    compute_scores,
    evidence_coverage,
    score_valuation,
)

CFG = get_default_config()
YEARS = 731 / 365.25  # 2023-03-31 -> 2025-03-31


def periods(status: str = "imported") -> list[fm.Period]:
    rows = [
        ("FY2023", date(2023, 3, 31), 100, 15, 12, 8, 9, 4, 2, 30, 10, 80),
        ("FY2024", date(2024, 3, 31), 120, 19.2, 15, 10, 11, 5, 2, 30, 12, 90),
        ("FY2025", date(2025, 3, 31), 150, 24, 19, 13, 14, 6, 2.5, 35, 15, 103),
    ]
    return [
        fm.Period(label=lbl, period_end=e, revenue=r, ebitda=eb, ebit=ebit, pat=pat, operating_cash_flow=ocf, capex=capex,
                  interest_expense=i, total_debt=d, cash_and_equivalents=c, total_equity=eq, data_status=status, source_record_id=n + 1)
        for n, (lbl, e, r, eb, ebit, pat, ocf, capex, i, d, c, eq) in enumerate(rows)
    ]


def issue(**kw) -> IssueInput:
    base = dict(ipo_id=1, company_name="Test Co", sector="Specialty Chemicals", issue_type="mainboard", price_band_low=95,
                price_band_high=100, post_issue_shares=2e7, issue_size_cr=60, fresh_issue_cr=40, ofs_cr=20,
                promoter_holding_post_pct=65, risk_disclosures_reviewed=False, open_date=date(2025, 9, 1), data_status="imported")
    base.update(kw)
    return IssueInput(**base)


def peers(status: str = "imported") -> list[PeerInput]:
    return [PeerInput(name=f"P{i}", as_of=date(2025, 8, 25), pe=v, ev_ebitda=v * 0.6, data_status=status, source_record_id=100 + i)
            for i, v in enumerate([10, 14, 18, 22, 30])]


def inputs(**kw) -> ScoringInputs:
    return ScoringInputs(issue=kw.pop("issue", issue()), periods=kw.pop("periods", periods()), peers=kw.pop("peers", peers()),
                         disclosures=kw.pop("disclosures", []), as_of=date(2025, 9, 1))


# ----------------------------------------------------------------------------- normalisation
def test_normalization_bounds_and_directions():
    assert normalize_higher(16, 0, 25) == pytest.approx(64)
    assert normalize_higher(-5, 0, 25) == 0 and normalize_higher(40, 0, 25) == 100
    assert normalize_lower(0.1, 0.1, 2.0) == 100 and normalize_lower(2.0, 0.1, 2.0) == 0
    assert normalize_lower(1.05, 0.1, 2.0) == pytest.approx(50)
    assert normalize_target(1.2, 0.9, 1.6, 0.9, 2.0) == 100
    assert normalize_target(0.45, 0.9, 1.6, 0.9, 2.0) == pytest.approx(50)
    assert normalize_target(2.6, 0.9, 1.6, 0.9, 2.0) == pytest.approx(50)
    assert normalize_target(0.0, 0.9, 1.6, 0.9, 2.0) == 0
    assert normalize_risk(50, 0, 100) == 50 and normalize_risk(52.5, 75, 30) == pytest.approx(50)
    with pytest.raises(ValueError):
        normalize_higher(1, 5, 5)
    with pytest.raises(ValueError):
        normalize_higher(float("nan"), 0, 1)


def test_percentile_and_winsorize():
    vals = [10, 14, 18, 22, 30]
    assert percentile(vals, 25) == 14 and percentile(vals, 50) == 18 and percentile(vals, 75) == 22
    assert percentile([1, 2], 50) == 1.5
    assert winsorize([1, 2, 3, 100], 0, 75) == [1, 2, 3, percentile([1, 2, 3, 100], 75)]


# ----------------------------------------------------------------------------- metrics
def test_unit_conversion():
    assert fm.to_crore(250, "lakh") == pytest.approx(2.5)
    assert fm.to_crore(1500, "million") == pytest.approx(150)
    assert fm.to_crore(2, "billion") == pytest.approx(200)
    assert fm.to_crore(None, "crore") is None
    with pytest.raises(fm.UnitError):
        fm.to_crore(1, "furlongs")


def test_cagr_edge_cases():
    v, _ = fm.cagr(100, 150, YEARS)
    assert v == pytest.approx((1.5 ** (1 / YEARS) - 1) * 100)
    assert fm.cagr(0, 10, 2)[0] is None
    assert fm.cagr(-5, 10, 2)[0] is None and "negative" in fm.cagr(-5, 10, 2)[1]
    assert fm.cagr(10, -1, 2)[0] is None
    assert fm.cagr(10, 20, 0)[0] is None
    assert fm.cagr(None, 20, 2)[0] is None


def test_metrics_hand_calculated():
    m = fm.compute_quality_metrics(periods())
    assert m["ebitda_margin"].value == pytest.approx(16.0)
    assert m["pat_margin"].value == pytest.approx(13 / 150 * 100)
    assert m["roe"].value == pytest.approx(13 / ((90 + 103) / 2) * 100)
    assert m["roce"].value == pytest.approx(19 / (103 + 35) * 100)
    assert m["revenue_cagr"].value == pytest.approx((1.5 ** (1 / YEARS) - 1) * 100)
    assert m["pat_cagr"].value == pytest.approx(((13 / 8) ** (1 / YEARS) - 1) * 100)
    assert m["latest_revenue_growth"].value == pytest.approx(25.0)
    assert m["ocf_to_pat"].value == pytest.approx(34 / 31)
    assert m["fcf_margin"].value == pytest.approx((34 - 15) / 370 * 100)
    assert m["debt_to_equity"].value == pytest.approx(35 / 103)
    assert m["interest_coverage"].value == pytest.approx(19 / 2.5)
    assert m["net_debt_to_ebitda"].value == pytest.approx(20 / 24)
    assert m["revenue_growth_volatility"].value == pytest.approx(math.sqrt(((20 - 22.5) ** 2 + (25 - 22.5) ** 2) / 1))
    assert m["positive_growth_share"].value == 1.0
    assert m["customer_concentration"].status == "unavailable"
    assert m["roe"].source_record_ids == [2, 3]


def test_zero_negative_and_missing_inputs():
    ps = periods()
    ps[-1].pat = -5
    ps[0].pat = -2
    ps[-1].total_equity = -10
    ps[-1].interest_expense = 0
    ps[-1].total_debt = 0
    ps[-1].cash_and_equivalents = 5
    ps[1].revenue = None
    m = fm.compute_quality_metrics(ps)
    assert m["pat_cagr"].status == "not_meaningful"
    assert m["debt_to_equity"].score_override == 0.0  # negative equity documented as weakest outcome
    assert m["interest_coverage"].score_override == 100.0  # debt-free rule
    assert m["net_debt_to_ebitda"].score_override == 100.0  # net cash rule
    assert m["roe"].status == "not_meaningful"
    assert m["ocf_to_pat"].status == "ok"  # cumulative PAT (-2 + 10 - 5 = 3) is still positive
    assert fm.compute_quality_metrics([])["ebitda_margin"].status == "unavailable"
    # interim periods are excluded from annual metrics
    interim = fm.Period(label="H1FY26", period_end=date(2025, 9, 30), months=6, revenue=90, ebitda=15, pat=9)
    assert fm.compute_quality_metrics(periods() + [interim])["ebitda_margin"].periods == ["FY2025"]


# ----------------------------------------------------------------------------- scores
def test_quality_score_hand_calculated():
    r = compute_scores(inputs(), CFG)
    q = r["quality"]
    P = 0.35 * 64 + 0.25 * (13 / 150 * 100 / 15 * 100) + 0.2 * (13 / 96.5 * 100 / 25 * 100) + 0.2 * (19 / 138 * 100 / 25 * 100)
    rc = (1.5 ** (1 / YEARS) - 1) * 100
    pc = ((13 / 8) ** (1 / YEARS) - 1) * 100
    G = 0.5 * (rc / 25 * 100) + 0.3 * (pc / 30 * 100) + 0.2 * 100
    C = 0.4 * 100 + 0.35 * (((34 - 15) / 370 * 100 + 5) / 15 * 100) + 0.25 * 100
    B = 0.4 * ((2 - 35 / 103) / 1.9 * 100) + 0.3 * ((7.6 - 1.5) / 6.5 * 100) + 0.3 * ((4 - 20 / 24) / 4 * 100)
    sd = math.sqrt(12.5)
    R = (0.4 * ((25 - sd) / 22 * 100) + 0.35 * 100) / 0.75  # customer concentration unavailable -> re-weighted
    assert q["components"]["profitability"]["score"] == pytest.approx(P, abs=0.01)
    assert q["components"]["growth"]["score"] == pytest.approx(G, abs=0.01)
    assert q["components"]["cash_flow"]["score"] == pytest.approx(C, abs=0.01)
    assert q["components"]["balance_sheet"]["score"] == pytest.approx(B, abs=0.01)
    assert q["components"]["revenue_stability"]["score"] == pytest.approx(R, abs=0.01)
    assert q["components"]["revenue_stability"]["weight_coverage"] == pytest.approx(0.75)
    assert q["score"] == pytest.approx(0.25 * P + 0.2 * G + 0.2 * C + 0.2 * B + 0.15 * R, abs=0.02)


def test_valuation_hand_calculated():
    v = score_valuation(inputs(), CFG)
    pe = 200 / 13
    assert v["status"] == "ok" and v["multiple"] == "pe"
    assert v["market_cap_cr"] == pytest.approx(200)
    assert v["ipo_multiple"] == pytest.approx(pe, abs=0.01)
    assert (v["peer_low"], v["peer_median"], v["peer_high"]) == (14, 18, 22)
    assert v["score"] == pytest.approx(100 * (22 - pe) / 8, abs=0.01)
    assert v["premium_to_median_pct"] == pytest.approx((pe / 18 - 1) * 100, abs=0.01)


def test_valuation_negative_earnings_and_insufficient_peers():
    ps = periods()
    ps[-1].pat = -4
    v = score_valuation(inputs(periods=ps), CFG)
    assert v["multiple"] == "ev_ebitda"  # P/E skipped, next applicable multiple used
    assert any("P/E not computed" in f for f in v["flags"])
    ev = 200 + 35 - 15 - 40
    assert v["ipo_multiple"] == pytest.approx(ev / 24, abs=0.01)
    v2 = score_valuation(inputs(peers=peers()[:2]), CFG)
    assert v2["status"] == "unavailable" and v2["score"] is None
    v3 = score_valuation(inputs(issue=issue(post_issue_shares=None)), CFG)
    assert v3["status"] == "unavailable" and "share count" in v3["reason"]
    # stale peers are excluded
    old = [PeerInput(name=p.name, as_of=date(2024, 1, 1), pe=p.pe) for p in peers()]
    assert score_valuation(inputs(peers=old), CFG)["status"] == "unavailable"


def test_risk_aggregation_and_flags():
    r = compute_scores(inputs(disclosures=[DisclosureInput(1, "litigation", "high", "confirmed_disclosure", "Case"),
                                           DisclosureInput(2, "other", "medium", "unresolved_concern", "Concern")]), CFG)
    k = r["risk"]
    w = CFG["risk"]["weights"]
    total = sum(w[n] * c["score"] for n, c in k["components"].items())
    assert k["score"] == pytest.approx(total, abs=0.02)
    fin = {i["key"]: i for i in k["components"]["financial"]["items"]}
    assert all(i["score"] == 0 for i in fin.values())  # healthy company: no distress flags
    gov = {i["key"]: i for i in k["components"]["governance"]["items"]}
    assert gov["confirmed_disclosures"]["score"] == pytest.approx(45 + 0.5 * 25)
    assert gov["ofs_share_of_issue"]["score"] == pytest.approx(normalize_risk(20 / 60 * 100, 30, 100), abs=0.01)
    assert k["components"]["data_quality"]["score"] == pytest.approx(100 - r["coverage"])


def test_missing_disclosures_are_not_treated_as_misconduct():
    r = compute_scores(inputs(), CFG)
    gov = {i["key"]: i for i in r["risk"]["components"]["governance"]["items"]}
    assert gov["confirmed_disclosures"]["score"] is None
    assert "not evidence of misconduct" in gov["confirmed_disclosures"]["evidence"]


def test_risk_rules_do_not_double_count_negative_equity():
    ps = periods()
    ps[-1].total_equity = -1
    k = compute_scores(inputs(periods=ps), CFG)["risk"]["components"]["financial"]
    items = {i["key"]: i for i in k["items"]}
    assert items["negative_equity"]["score"] == 100 and items["leverage_above"]["score"] == 0


def test_risk_config_metrics_appear_in_one_component_only():
    seen: dict[str, str] = {}
    for comp, items in CFG["risk"]["components"].items():
        for key in items:
            if key == "method":
                continue
            assert key not in seen, f"{key} used in {seen.get(key)} and {comp}"
            seen[key] = comp


def test_composite_formula_and_no_silent_renormalisation():
    r = compute_scores(inputs(), CFG)
    assert r["status"] == "complete"
    assert r["composite"] == pytest.approx(0.45 * r["quality"]["score"] + 0.30 * r["valuation"]["score"] + 0.25 * (100 - r["risk"]["score"]), abs=0.02)
    assert r["is_probability"] is False
    r2 = compute_scores(inputs(peers=[]), CFG)
    assert r2["status"] == "incomplete" and r2["composite"] is None
    assert {m["component"] for m in r2["missing_components"]} >= {"valuation"}
    r3 = compute_scores(inputs(periods=periods()[-1:]), CFG)
    assert r3["quality"]["status"] == "insufficient_data" and r3["composite"] is None


def test_evidence_coverage():
    cov = evidence_coverage(inputs(), CFG)
    total = sum(CFG["evidence"]["inputs"].values())
    expected = 100 * (total - CFG["evidence"]["inputs"]["risk_disclosures_reviewed"] - CFG["evidence"]["inputs"]["customer_concentration"]) / total
    assert cov["coverage"] == pytest.approx(expected, abs=0.01)
    syn = evidence_coverage(inputs(periods=periods("synthetic"), peers=peers("synthetic"), issue=issue(data_status="synthetic")), CFG)
    assert syn["coverage"] == 0.0 and syn["input_completeness"] > 80  # synthetic data never counts as evidence
    stale = ScoringInputs(issue=issue(), periods=periods(), peers=peers(), as_of=date(2027, 6, 1))
    assert evidence_coverage(stale, CFG)["financials_stale"] is True


def test_reproducibility_and_versioning():
    a = compute_scores(inputs(), CFG)
    b = compute_scores(inputs(), copy.deepcopy(CFG))
    for k in ("composite", "input_fingerprint", "config_version"):
        assert a[k] == b[k]
    cfg2 = copy.deepcopy(CFG)
    cfg2["version"] = "1.0.1"
    cfg2["composite"]["weights"] = {"quality": 0.5, "valuation": 0.25, "risk_inverse": 0.25}
    c = compute_scores(inputs(), cfg2)
    assert c["config_version"] == "1.0.1" and c["input_fingerprint"] != a["input_fingerprint"] and c["composite"] != a["composite"]


def test_config_validation():
    validate_config(get_default_config())
    bad = get_default_config()
    bad["composite"]["weights"]["quality"] = 0.5
    with pytest.raises(ConfigError):
        validate_config(bad)
    bad2 = get_default_config()
    bad2["quality"]["components"]["growth"]["revenue_cagr"]["b"] = -1
    with pytest.raises(ConfigError):
        validate_config(bad2)


# ----------------------------------------------------------------------------- scenarios
def test_scenario_hand_calculated():
    res = run_scenarios(inputs(), CFG)
    base = next(s for s in res["scenarios"] if s["name"] == "base")
    g = (1.5 ** (1 / YEARS) - 1) * 100
    rev = 150 * (1 + g / 100)
    pat = rev * 0.16 * (13 / 24)
    price = pat * 18 * 1e7 / 2e7  # peer median P/E, no market adjustment
    assert base["status"] == "ok"
    assert base["implied_price"] == pytest.approx(price, abs=0.01)
    assert base["implied_return_pct"] == pytest.approx((price - 100) / 100 * 100, abs=0.01)
    bear = next(s for s in res["scenarios"] if s["name"] == "bear")
    assert bear["implied_price"] < base["implied_price"]
    assert res["is_forecast"] is False


def test_scenario_unavailable_and_overrides():
    ps = periods()
    for p in ps:
        p.pat = -1
    res = run_scenarios(inputs(periods=ps, peers=[PeerInput(name="x", as_of=date(2025, 8, 1), pe=20)]), CFG)
    assert res["status"] == "unavailable"
    ov = run_scenarios(inputs(), CFG, {"base": {"revenue_growth_pct": 0, "ebitda_margin_pct": 20, "multiple": 10, "method": "pe"}})
    base = next(s for s in ov["scenarios"] if s["name"] == "base")
    assert base["implied_price"] == pytest.approx(150 * 0.20 * (13 / 24) * 10 * 1e7 / 2e7, abs=0.01)
    ev = run_scenarios(inputs(), CFG, {"base": {"method": "ev_ebitda", "multiple": 10, "revenue_growth_pct": 0, "ebitda_margin_pct": 16}})
    b2 = next(s for s in ev["scenarios"] if s["name"] == "base")
    equity = 24 * 10 - (35 - 15 - 40)
    assert b2["implied_price"] == pytest.approx(equity * 1e7 / 2e7, abs=0.01)
