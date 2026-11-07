"""Platform features added in the v2.1 overhaul: new ratios, industry profiles, classification, SEBI filings,
document retries and de-duplication, completeness, history, peers, caching and the new endpoints.

Every number asserted here is computed by hand in the comment next to it. Network access is mocked.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.financials.disclosures import business_overview
from app.financials.industry import classify_industry
from app.ingestion.document_service import DocRunStats, discover_sebi, record_failure, run_documents
from app.ingestion.http import PoliteClient
from app.ingestion.sources.base import ListingPriceRecord
from app.ingestion.sources.sebi import SEBIFilingsSource, parse_listing, pdf_url_from_filing
from app.models import Company, FieldObservation, IPOIssue, ResearchScore, SourceDocument, utcnow
from app.services import quant_engine as qe
from app.services.scoring_config import get_default_config, validate_config
from tests.conftest import ipo_id_by_name
from tests.rhp_builder import build_rhp

CFG = get_default_config()
FIX = Path(__file__).parent / "fixtures" / "sebi"


def fy(year: int, **kw) -> qe.FinPeriod:
    return qe.FinPeriod(label=f"FY{year}", period_end=date(year, 3, 31), months=12, basis="consolidated", data_status="verified",
                        validation_status="passed", **kw)


def three_years(**over) -> list[qe.FinPeriod]:
    base = dict(revenue=1000.0, cost_of_materials=600.0, ebitda=200.0, ebit=150.0, pat=100.0, interest_expense=20.0, eps_basic=5.0,
                total_assets=1200.0, current_assets=600.0, current_liabilities=300.0, total_equity=500.0, total_debt=240.0,
                cash_and_equivalents=80.0, inventory=150.0, trade_receivables=200.0, operating_cash_flow=120.0, capex=50.0)
    return [fy(2024, **{**base, "ebitda": 125.0, "eps_basic": 3.2, "total_assets": 1000.0, "pat": 60.0, "revenue": 640.0}),
            fy(2025, **{**base, "total_assets": 1000.0}),
            fy(2026, **{**base, **over})]


def issue(**kw) -> qe.IssueTerms:
    return qe.IssueTerms(company_name="X", sector="S", issue_type="mainboard", price_band_low=90.0, price_band_high=100.0,
                         pre_issue_shares=8_000_000.0, fresh_issue_cr=20.0, **kw)


# ------------------------------------------------------------------------------------------------ new ratios (hand-calculated)
def test_new_ratios_match_hand_calculations():
    m, _ = qe.compute_metrics(three_years(), issue(final_issue_price=100.0), [], CFG)
    assert m["roa"].value == pytest.approx(100 / ((1200 + 1000) / 2) * 100)  # PAT ÷ avg TA = 100 / 1100 = 9.0909 %
    assert m["gross_margin"].value == pytest.approx(40.0)  # (1000 − 600) / 1000
    assert m["ebitda_cagr"].value == pytest.approx(((200 / 125) ** (1 / 2.0) - 1) * 100, rel=1e-3)  # 26.49 %
    assert m["eps_cagr"].value == pytest.approx(((5.0 / 3.2) ** (1 / 2.0) - 1) * 100, rel=1e-3)  # 25.0 %
    assert m["debt_to_assets"].value == pytest.approx(0.2)  # 240 / 1200
    assert m["capex_intensity"].value == pytest.approx(5.0)  # 50 / 1000 × 100
    assert m["receivable_days"].value == pytest.approx(73.0)  # 200 / 1000 × 365
    assert m["inventory_days"].value == pytest.approx(54.75)  # 150 / 1000 × 365
    # post-issue shares = 8,000,000 + 20 cr / ₹100 = 10,000,000 → market cap ₹100 cr → P/S = 100 / 1000
    assert m["market_cap"].value == pytest.approx(100.0)
    assert m["price_to_sales"].value == pytest.approx(0.1)


def test_new_ratios_refuse_misleading_inputs():
    m, _ = qe.compute_metrics(three_years(revenue=0.0, cost_of_materials=None), issue(final_issue_price=100.0), [], CFG)
    assert m["gross_margin"].status == "unavailable"
    assert m["receivable_days"].status == "not_meaningful" and m["price_to_sales"].status == "not_meaningful"
    ps = three_years()
    ps[0].ebitda = -10.0  # a negative starting EBITDA has no meaningful CAGR
    m, _ = qe.compute_metrics(ps, issue(), [], CFG)
    assert m["ebitda_cagr"].value is None and m["ebitda_cagr"].status == "not_meaningful"


def test_peer_quartiles_inclusive_method():
    q = qe.quartiles([10.0, 20.0, 30.0, 40.0])
    assert q == {"min": 10.0, "q1": 17.5, "median": 25.0, "q3": 32.5, "max": 40.0}  # QUARTILE.INC
    peers = [qe.PeerMultiple(n, pe, None, None, "standalone", "FY2026", "verified") for n, pe in (("a", 10.0), ("b", 20.0), ("c", -5.0))]
    _, ctx = qe.compute_metrics(three_years(), issue(final_issue_price=100.0), peers, CFG)
    assert ctx["peers"]["median_pe"] == 15.0 and ctx["peers"]["excluded_loss_making"] == 1


# ------------------------------------------------------------------------------------------------ industry profiles
def lender_inputs() -> qe.EngineInputs:
    return qe.EngineInputs(issue=issue(final_issue_price=100.0), periods=three_years(), peers=[], facts=qe.RiskFacts(),
                           as_of=date(2026, 10, 1), profile="lender")


def test_lender_profile_marks_ratios_not_applicable_instead_of_penalising():
    r = qe.compute(lender_inputs(), CFG)
    assert r["profile"]["key"] == "lender"
    for k in ("roce", "current_ratio", "debt_to_equity", "interest_coverage", "ev_ebitda", "ocf_to_pat"):
        assert r["metrics"][k]["status"] == "not_applicable", k
    assert r["components"]["cash_flow"]["applicable"] is False
    prof = r["components"]["profitability"]
    assert {i["key"] for i in prof["items"]} == {"roe", "roa", "net_margin"} and prof["coverage"] == 100.0
    # lender financial health needs GNPA/NNPA/CRAR in verified form: Q is withheld, not computed on the wrong ratios
    assert r["components"]["financial_health"]["score"] is None and r["composite"] is None
    assert "Financial health" in r["fundamental"]["reason"]
    risk = {c["key"]: c for c in r["risk"]["components"]}
    assert risk["leverage"]["applicable"] is False and risk["cash_flow_weakness"]["applicable"] is False
    assert not any("Return on capital" in x for x in r["missing"])  # not applicable is never reported as missing


def test_general_profile_scores_unchanged_by_profiles():
    g = qe.compute(qe.EngineInputs(issue(final_issue_price=100.0), three_years(), [], qe.RiskFacts(), date(2026, 10, 1)), CFG)
    m = qe.compute(qe.EngineInputs(issue(final_issue_price=100.0), three_years(), [], qe.RiskFacts(), date(2026, 10, 1), "manufacturing"), CFG)
    assert g["composite"] is not None and g["composite"] == m["composite"]


def test_config_rejects_bad_profile_weights():
    cfg = get_default_config()
    cfg["profiles"]["lender"]["weights"]["profitability"] = {"roe": 0.5, "roa": 0.2}
    with pytest.raises(Exception, match="sum to 1.0"):
        validate_config(cfg)


def test_engine_version_is_part_of_the_fingerprint(monkeypatch):
    i = qe.EngineInputs(issue(), three_years(), [], qe.RiskFacts(), date(2026, 10, 1))
    a = qe.fingerprint(i, CFG)
    monkeypatch.setattr(qe, "ENGINE_VERSION", "9.9.9")
    assert qe.fingerprint(i, CFG) != a


# ------------------------------------------------------------------------------------------------ classification and overview
def test_industry_classifier_reads_evidence_and_declines_close_calls():
    nbfc = ["OUR BUSINESS\nOverview\nOur Company is registered with the RBI as an NBFC. Our loan book grew. Gross NPA was 1.2%. "
            "Disbursements rose; net interest margin and capital adequacy are healthy. " * 3]
    c = classify_industry(nbfc, "Example Finance Limited")
    assert c.sector == "NBFC & Lending" and c.profile == "lender" and c.status == "extracted" and c.evidence
    steel = ["OUR BUSINESS\nWe process steel coils into galvanised products at our plants. Stainless steel and colour coated coils. " * 4]
    assert classify_industry(steel, "Example Steels Limited").profile == "manufacturing"
    vague = ["OUR BUSINESS\nWe are a company with customers and products."]
    u = classify_industry(vague, "Example Limited")
    assert u.sector == "Unclassified" and u.status == "unavailable" and u.note


def test_business_overview_is_quoted_with_its_page():
    texts = ["cover", "OUR BUSINESS\nThis section contains forward-looking statements and risks that may affect our business.\n\n"
             "We are a manufacturer of speciality polymer compounds for cables and pipes, supplying more than 400 customers from two "
             "plants in Gujarat. Our products are used in telecom, power and automotive applications across India and abroad.\n\nMore."]
    d = business_overview(texts)
    assert d is not None and d.page == 2 and d.value.startswith("We are a manufacturer") and d.key == "business_overview"
    assert business_overview(["no such section"]) is None


# ------------------------------------------------------------------------------------------------ SEBI filings
def test_sebi_listing_parser_on_saved_pages():
    rhp = parse_listing((FIX / "rhp_list.html").read_text(), "rhp")
    assert rhp and all(f.kind == "rhp" for f in rhp)
    assert any(f.company_name == "BOMBAY COATED AND SPECIAL STEELS LIMITED" for f in rhp)
    assert not any("Addendum" in f.title for f in rhp)  # addenda are not offer documents
    drhp = parse_listing((FIX / "drhp_list.html").read_text(), "drhp")
    assert drhp and all(f.kind == "drhp" for f in drhp) and any("UDRHP" in f.title for f in drhp)
    assert pdf_url_from_filing((FIX / "filing.html").read_text()).startswith("https://www.sebi.gov.in/sebi_data/attachdocs/")
    assert pdf_url_from_filing('<iframe src="../web/?file=https://evil.example.com/x.pdf">') is None


def _sebi_transport(pdf_bytes: bytes) -> httpx.MockTransport:
    pages = {"smid=11": (FIX / "rhp_list.html").read_text(), "smid=10": (FIX / "drhp_list.html").read_text()}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        for k, body in pages.items():
            if k in url:
                return httpx.Response(200, text=body, headers={"content-type": "text/html"})
        if url.endswith(".html"):
            return httpx.Response(200, text=(FIX / "filing.html").read_text(), headers={"content-type": "text/html"})
        if url.lower().endswith(".pdf"):
            return httpx.Response(200, content=b"" if req.method == "HEAD" else pdf_bytes,
                                  headers={"content-type": "application/pdf", "last-modified": "Tue, 27 Oct 2026 05:36:46 GMT"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_sebi_discovery_matches_existing_issues_and_creates_pipeline_issues(db, tmp_path):
    company = Company(name="Bombay Coated and Special Steels Limited", sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    existing = IPOIssue(company_id=company.id, exchange="NSE", issue_type="mainboard", data_mode="source", data_status="verified", nse_symbol="BCSSL")
    db.add(existing)
    db.commit()
    client = PoliteClient(min_interval=0, transport=_sebi_transport(b"%PDF-1.4"), sleep=lambda s: None)
    st = DocRunStats()
    discover_sebi(db, SEBIFilingsSource(client), st)
    docs = list(db.execute(select(SourceDocument)).scalars())
    assert st.filings_seen == len(docs) > 0 and st.pipeline_ipos_created == len(docs) - 1
    bc = next(d for d in docs if "BOMBAY" in d.title.upper())
    assert bc.ipo_id == existing.id and bc.source_key == "sebi_rhp" and bc.archive_url is None and bc.published_date == date(2026, 10, 21)
    pipeline = db.execute(select(IPOIssue).where(IPOIssue.id != existing.id)).scalars().first()
    assert pipeline is not None and pipeline.open_date is None and "SEBI" in (pipeline.research_notes or "")
    from app.services.ipo_service import effective_status

    assert effective_status(pipeline) == "pipeline"
    discover_sebi(db, SEBIFilingsSource(client), DocRunStats())  # second run adds nothing
    assert len(list(db.execute(select(SourceDocument)).scalars())) == len(docs)


def test_sebi_rhp_is_downloaded_only_as_a_fallback_and_duplicates_are_detected(db, tmp_path):
    path = tmp_path / "rhp.pdf"
    build_rhp(str(path), company="Bombay Coated and Special Steels Limited")
    pdf = path.read_bytes()
    company = Company(name="Bombay Coated and Special Steels Limited", sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="NSE", issue_type="mainboard", data_mode="source", data_status="verified", nse_symbol="BCSSL",
                   open_date=date.today() + timedelta(days=3), close_date=date.today() + timedelta(days=5), price_band_high=82.0,
                   offer_document_url="https://nsearchives.nseindia.com/content/ipo/RHP_BCSSL.zip")
    db.add(ipo)
    db.commit()
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("RHP_BCSSL/BCSSL_RHP.pdf", pdf)
    sebi = _sebi_transport(pdf)

    def handler(req: httpx.Request) -> httpx.Response:
        if "nsearchives" in str(req.url):
            return httpx.Response(200, content=b"" if req.method == "HEAD" else zipped.getvalue(), headers={"content-type": "application/zip"})
        return sebi.handle_request(req)
    client = PoliteClient(min_interval=0, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    st = run_documents(db, client, [ipo], date.today(), sebi=True)
    docs = {d.source_key: d for d in db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id)).scalars()}
    assert docs["nse_rhp"].extraction_status == "extracted" and st.extracted >= 1
    assert docs["sebi_rhp"].extraction_status == "pending"  # the NSE copy was read: the SEBI copy is never fetched
    # if the NSE copy had failed, the SEBI copy would be fetched — and an identical file is marked a duplicate, not re-processed
    docs["nse_rhp"].extraction_status = "failed"
    docs["nse_rhp"].attempts = 99
    db.commit()
    run_documents(db, client, [ipo], date.today())
    db.refresh(docs["sebi_rhp"])
    assert docs["sebi_rhp"].extraction_status == "duplicate" and "SHA-256" in (docs["sebi_rhp"].extraction_error or "")


def test_failed_documents_back_off_exponentially_then_become_dead_letters(db):
    doc = SourceDocument(title="t", doc_type="rhp", sha256="", mime_type="application/pdf", data_status="verified", extraction_status="failed")
    hours = []
    for _ in range(4):
        before = utcnow()
        assert record_failure(doc, "HTTP 500") is False
        hours.append(round((doc.next_attempt_at - before).total_seconds() / 3600))
    assert hours == [1, 2, 4, 8]
    assert record_failure(doc, "HTTP 500") is True and doc.next_attempt_at is None and doc.attempts == 5


# ------------------------------------------------------------------------------------------------ completeness, caching, endpoints
def test_completeness_explains_every_gap(client, seeded):
    iid = ipo_id_by_name(client, "Aravalli")
    c = client.get(f"/api/ipos/{iid}/completeness").json()
    assert 0 < c["overall_pct"] <= 100 and {g["key"] for g in c["groups"]} == {"issue", "financials", "ratios", "valuation", "risk", "verification"}
    fields = {f["key"]: f for g in c["groups"] for f in g["fields"]}
    assert fields["revenue"]["status"] == "available" and fields["revenue"]["period"]
    assert fields["litigation"]["status"] == "unavailable" and "never treated" in fields["litigation"]["reason"]
    assert all(f["reason"] for f in fields.values() if f["status"] == "unavailable")  # no unexplained gap
    assert [p["stage"] for p in c["pipeline"]][0] == "discovered"
    listed = client.get("/api/ipos", params={"page_size": 100}).json()["items"]
    assert any(i["completeness_pct"] is not None for i in listed)


def test_pipeline_issue_without_documents_says_why_financials_are_missing(db):
    from app.services.completeness import compute_completeness
    from app.services.ipo_service import build_engine_inputs, get_active_config

    company = Company(name="Pipeline Co Limited", sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="Not announced", issue_type="mainboard", data_mode="source", data_status="verified")
    db.add(ipo)
    db.commit()
    cfg = get_active_config(db)
    c = compute_completeness(db, ipo, qe.compute(build_engine_inputs(db, ipo), cfg), cfg)
    fields = {f["key"]: f for g in c["groups"] for f in g["fields"]}
    assert fields["open_date"]["status"] == "pending" and "not announced" in fields["open_date"]["reason"]
    assert fields["revenue"]["status"] == "unavailable" and "no offer document" in fields["revenue"]["reason"]
    assert c["readiness"]["level"] == "insufficient"


def test_lists_read_stored_scores_instead_of_recomputing(client, seeded, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the engine must not run during a list request")
    monkeypatch.setattr(qe, "compute", boom)
    body = client.get("/api/ipos", params={"page_size": 100}).json()
    assert body["total"] > 0 and any(i["scores"]["composite"] is not None for i in body["items"])
    assert client.get("/api/dashboard/summary").status_code == 200


def test_new_reference_endpoints(client, seeded):
    f = client.get("/api/fields").json()
    assert {x["key"] for x in f["fields"]} >= {"open_date", "revenue", "pe", "litigation"} and abs(sum(f["group_weights"].values()) - 1) < 1e-9
    m = client.get("/api/methodology").json()
    assert m["active_version"] == "2.1.0" and "lender" in m["config"]["profiles"] and m["formulas"]["roa"].startswith("ROA")
    ind = client.get("/api/industries").json()
    assert {p["key"] for p in ind["profiles"]} >= {"general", "lender", "technology"}
    h = client.get("/api/system/health").json()
    assert {s["stage"] for s in h["pipeline_funnel"]} >= {"discovered", "scored"} and "ocr_available" in h["documents"]
    iid = ipo_id_by_name(client, "Aravalli")
    p = client.get(f"/api/ipos/{iid}/peers").json()
    assert p["selection_rationale"] and "benchmarks" in p
    r = client.post("/api/admin/data-sync", json={"job": "nonsense"})
    assert r.status_code in (401, 403, 422)


def test_listing_history_uses_point_in_time_scores_only(client, db, tmp_path):
    from app.ingestion.ipo_data_service import apply_listing_price
    from app.services.ipo_service import score_ipo

    company = Company(name="Listed Co Limited", sector="Metals & Steel", data_status="verified")
    db.add(company)
    db.flush()
    listing = date.today() - timedelta(days=5)
    ipo = IPOIssue(company_id=company.id, exchange="NSE", issue_type="mainboard", data_mode="source", data_status="verified", nse_symbol="LCL",
                   open_date=listing - timedelta(days=8), close_date=listing - timedelta(days=6), final_issue_price=100.0, price_band_high=100.0,
                   listing_date=listing, listing_date_status="actual")
    db.add(ipo)
    db.commit()
    db.refresh(ipo)
    lp = ListingPriceRecord(symbol="LCL", trade_date=listing, open_price=112.0, close_price=95.0, previous_close=100.0, series="EQ", isin=None,
                            source_url="https://nsearchives.nseindia.com/x.zip", high_price=118.0, low_price=94.0)
    apply_listing_price(db, ipo, lp)
    db.commit()
    assert ipo.listing_high_price == 118.0 and ipo.listing_low_price == 94.0
    assert db.execute(select(FieldObservation).where(FieldObservation.field == "listing_high_price")).scalar_one().data_status == "verified"
    # a score computed from statements in a document published AFTER listing must not enter the outcome analysis
    doc = SourceDocument(ipo_id=ipo.id, title="Annual report", doc_type="annual_report", sha256="x", mime_type="application/pdf",
                         data_status="verified", published_date=listing + timedelta(days=1))
    db.add(doc)
    db.commit()
    from app.models import FinancialStatement

    for y, rev in ((2025, 800.0), (2026, 1000.0)):
        db.add(FinancialStatement(company_id=company.id, period_label=f"FY{y}", period_end=date(y, 3, 31), period_months=12, basis="standalone",
                                  revenue=rev, pat=rev * 0.1, ebitda=rev * 0.2, ebit=rev * 0.15, interest_expense=10.0, total_assets=1500.0,
                                  current_assets=700.0, current_liabilities=300.0, total_equity=600.0, total_debt=200.0, cash_and_equivalents=50.0,
                                  operating_cash_flow=90.0, capex=30.0, data_status="verified", validation_status="passed", document_id=doc.id))
    db.commit()
    score_ipo(db, ipo)
    h = client.get("/api/history").json()
    row = next(r for r in h["items"] if r["id"] == ipo.id)
    assert row["listing_gain_pct"] == 12.0 and row["listing_close_return_pct"] == -5.0  # (112−100)/100, (95−100)/100
    assert row["listing_high_return_pct"] == 18.0 and row["listing_low_return_pct"] == -6.0
    assert row["score_available"] is True and row["point_in_time_ok"] is False and row["pre_listing_score"] is None
    doc.published_date = listing - timedelta(days=20)  # now the inputs predate the listing
    db.commit()
    row = next(r for r in client.get("/api/history").json()["items"] if r["id"] == ipo.id)
    assert row["point_in_time_ok"] is True and row["pre_listing_score"] is not None
    assert db.execute(select(ResearchScore).where(ResearchScore.ipo_id == ipo.id)).scalars().first() is not None


def test_spearman_rank_correlation():
    from app.api.routes.analytics import _spearman

    assert _spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert _spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert _spearman([1, 2], [1, 2]) is None


def test_ocr_is_skipped_with_a_reason_when_disabled(monkeypatch):
    import pymupdf

    from app.config import get_settings
    from app.financials.statement_parser import ExtractionResult
    from app.ingestion.document_service import _ocr_extract

    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    doc = pymupdf.open()
    doc.new_page()
    empty = ExtractionResult("not_found", 1, [], [], [])
    res, pages, note = _ocr_extract(doc, [0, 1, 2], empty)
    assert res is empty and not pages and "OCR is disabled" in note


def test_datetime_of_scores_is_utc_naive():
    assert isinstance(utcnow(), datetime) and utcnow().tzinfo is None


@pytest.mark.skipif(not __import__("app.financials.ocr", fromlist=["x"]).tesseract_available(), reason="Tesseract not installed")
def test_scanned_statements_are_read_by_ocr_but_never_scored(db, tmp_path):
    """A prospectus whose statement pages are images: OCR reads them, checks run, and the periods are stored as 'extracted' only."""
    import pymupdf

    from app.financials.ocr import OcrDocument, image_only_pages
    from app.financials.statement_parser import extract_financials
    from app.ingestion.financial_store import StoreStats, store_statements

    src = tmp_path / "text.pdf"
    values = build_rhp(str(src))
    scanned = pymupdf.open()
    with pymupdf.open(src) as pdf:
        for page in pdf:  # every page becomes a picture with no text layer, as in a scanned document
            pix = page.get_pixmap(dpi=220)
            new = scanned.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, pixmap=pix)
    texts = [p.get_text() for p in scanned]
    assert len(image_only_pages(texts)) == scanned.page_count
    od = OcrDocument(scanned, image_only_pages(texts), dpi=300)
    result = extract_financials(od)
    fy26 = next(p for p in result.periods if p.label == "FY2026")
    assert fy26.get("revenue") == pytest.approx(values["revenue"][1] / 100, rel=1e-6)  # ₹9,000 lakh = ₹90 crore, read by OCR
    company = Company(name="Testco Industries Limited", sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="NSE", issue_type="mainboard", data_mode="source", data_status="verified")
    doc = SourceDocument(title="RHP (scanned)", doc_type="rhp", sha256="s", mime_type="application/pdf", data_status="verified")
    db.add_all([ipo, doc])
    db.flush()
    store_statements(db, ipo, doc, result, StoreStats(), ocr_pages=od.ocr_pages)
    from app.models import FinancialStatement

    rows = list(db.execute(select(FinancialStatement).where(FinancialStatement.company_id == company.id)).scalars())
    assert rows and all(r.data_status != "verified" for r in rows)  # OCR figures are never used in scores
