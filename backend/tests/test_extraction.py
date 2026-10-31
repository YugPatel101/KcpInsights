"""Offer-document pipeline: PDF parsing, validation, storage, download rules. Network access is mocked."""
from __future__ import annotations

import io
import zipfile
from datetime import date

import httpx
import pymupdf
import pytest
from sqlalchemy import func, select

from app.financials.disclosures import extract_disclosures, parse_peers
from app.financials.pdf_tables import parse_number
from app.financials.statement_parser import extract_financials, header_dates, norm_label
from app.ingestion.document_service import DocumentFetchError, pick_pdf, run_documents
from app.ingestion.http import PoliteClient
from app.models import (
    Company,
    DocumentExtraction,
    FinancialLineItem,
    FinancialStatement,
    IPOIssue,
    PeerSnapshot,
    ResearchScore,
    SourceDocument,
)
from tests.rhp_builder import build_rhp

URL = "https://nsearchives.nseindia.com/content/ipo/RHP_TESTCO.zip"


@pytest.fixture()
def rhp(tmp_path):
    path = tmp_path / "rhp.pdf"
    values = build_rhp(str(path))
    return path, values


def test_number_and_label_parsing():
    assert parse_number("1,664.72") == (True, 1664.72)
    assert parse_number("(218.38)") == (True, -218.38)
    assert parse_number("-") == (True, 0.0) and parse_number("--") == (True, 0.0)
    assert parse_number("[●]") == (True, None) and parse_number("NA") == (True, None)
    assert parse_number("Revenue")[0] is False and parse_number("30,")[0] is False
    assert norm_label("a) Revenue from operations") == "revenue from operations"
    assert norm_label("13 Profit for the year") == "profit for the year"
    assert norm_label("Total Current Liabilities (II)") == "total current liabilities"
    assert norm_label("Profit for the period/year E=(C-D)") == "profit for the period/year"


def test_period_headers_split_ranges_and_month_end_guard():
    assert header_dates("As at June As at March 30, 2026 31, 2026", 2) == [(date(2026, 6, 30), None), (date(2026, 3, 31), None)]
    assert header_dates("30-04-2026 31-03-2026 31-03- 2025", 3) is not None
    rng = header_dates("For the period April 1, 2026 to June 30, 2026 For the year ended March 31, 2026", 2)
    assert rng and rng[0][0] == date(2026, 6, 30) and rng[0][1] == 3
    # an interleaved header that would pair March with 30 is rejected rather than misread
    assert header_dates("ended March ended June 30, 31, 2026 2026", 2) is None


def test_statements_extracted_and_reconciled(rhp):
    path, v = rhp
    with pymupdf.open(path) as doc:
        r = extract_financials(doc)
    assert r.status == "extracted" and {t.kind for t in r.tables} == {"bs", "pl", "cf"}
    assert all(t.unit == "lakh" for t in r.tables)
    by = {p.label: p for p in r.periods}
    assert set(by) == {"FY2024", "FY2025", "FY2026", "3M Jun-2026"} and by["3M Jun-2026"].months == 3
    fy26 = by["FY2026"]  # column 1 in the document (stub first)
    assert fy26.get("revenue") == pytest.approx(v["revenue"][1] / 100)  # lakhs -> crore
    assert fy26.get("pat") == pytest.approx(v["pat"][1] / 100)
    assert fy26.get("total_equity") == pytest.approx(v["equity"][1] / 100)  # Indian GAAP "Total" under shareholders' funds
    assert fy26.get("total_debt") == pytest.approx((v["lt_borrowings"][1] + v["st_borrowings"][1]) / 100)
    assert fy26.get("capex") == pytest.approx(abs(v["capex"][1]) / 100)  # printed as an outflow
    assert by["FY2025"].get("operating_cash_flow") == pytest.approx(v["cfo"][2] / 100)  # bracketed negative
    assert fy26.get("ebitda") == pytest.approx((v["pbt"][1] + v["finance"][1] + v["depreciation"][1]) / 100)
    assert all(p.validation_status == "passed" for p in r.periods)
    assert fy26.figures["revenue"].page == 3 and fy26.figures["revenue"].raw_text == "9,000.00"


def test_failed_reconciliation_is_flagged_not_accepted(tmp_path):
    path = tmp_path / "bad.pdf"
    build_rhp(str(path), break_balance_sheet=True)
    with pymupdf.open(path) as doc:
        r = extract_financials(doc)
    by = {p.label: p for p in r.periods}
    assert by["FY2026"].validation_status == "failed"
    assert any(c["check"] == "equity_plus_liabilities" and not c["passed"] for c in by["FY2026"].checks)
    assert by["FY2025"].validation_status == "passed"


def test_peers_and_disclosures(rhp):
    path, _ = rhp
    with pymupdf.open(path) as doc:
        texts = [p.get_text() for p in doc]
        peers = parse_peers(doc, texts, "Testco Industries Limited")
        facts = extract_disclosures(doc, texts)
    assert peers is not None and peers.reliable and peers.basis == "standalone" and peers.period_label == "FY2026"
    listed = [p for p in peers.rows if not p.is_company]
    assert [p.name for p in listed] == ["Alpha Metals Limited", "Beta Steels Limited", "Gamma Coatings Limited"]
    assert [p.pe for p in listed] == [20.0, 25.0, 30.0] and all(p.check_note.startswith("P/E consistent") for p in listed)
    assert facts["pre_issue_shares"].value == 5_000_000
    assert facts["customer_concentration_pct"].value == 58.4  # the latest full fiscal year, not the stub
    assert facts["auditor_qualifications"].value == "none"


def _zip(*members: tuple[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


def test_archive_member_selection_and_safety(rhp):
    path, _ = rhp
    pdf = path.read_bytes()
    gid = pymupdf.open()
    gid.new_page().insert_text((50, 50), "General Information Document")
    gid_bytes = gid.tobytes()
    name, data = pick_pdf(_zip(("RHP_X/Testco_GID.pdf", gid_bytes), ("RHP_X/Testco_RHP.pdf", pdf)), 50 * 1024 * 1024)
    assert name == "Testco_RHP.pdf" and data == pdf
    with pytest.raises(DocumentFetchError):
        pick_pdf(_zip(("readme.txt", b"hello")), 10_000_000)
    with pytest.raises(DocumentFetchError):
        pick_pdf(b"<html>not a document</html>", 10_000_000)
    with pytest.raises(DocumentFetchError):  # a highly compressible member is treated as a zip bomb
        pick_pdf(_zip(("RHP.pdf", b"%PDF-" + b"0" * 5_000_000)), 50 * 1024 * 1024)


class FakeArchive:
    def __init__(self, body: bytes, etag: str = '"v1"') -> None:
        self.body, self.etag, self.calls = body, etag, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, str(request.url)))
        if request.url.host != "nsearchives.nseindia.com":
            return httpx.Response(404)
        headers = {"etag": self.etag, "last-modified": "Wed, 28 Oct 2026 10:00:00 GMT", "content-type": "application/zip"}
        return httpx.Response(200, headers=headers, content=b"" if request.method == "HEAD" else self.body)


def _ipo(db) -> IPOIssue:
    c = Company(name="Testco Industries Limited", sector="Unclassified", data_status="verified")
    db.add(c)
    db.flush()
    ipo = IPOIssue(company_id=c.id, exchange="NSE", issue_type="mainboard", nse_symbol="TESTCO", open_date=date(2026, 11, 2),
                   close_date=date(2026, 11, 4), price_band_low=95.0, price_band_high=100.0, fresh_issue_cr=20.0,
                   offer_document_url=URL, data_mode="source", data_status="verified")
    db.add(ipo)
    db.commit()
    return ipo


def test_pipeline_discovers_downloads_extracts_scores_and_skips_unchanged(db, rhp):
    path, v = rhp
    ipo = _ipo(db)
    fake = FakeArchive(_zip(("RHP_TESTCO/Testco_GID.pdf", b"%PDF-1.4 tiny"), ("RHP_TESTCO/Testco_RHP.pdf", path.read_bytes())))
    client = PoliteClient(min_interval=0, transport=httpx.MockTransport(fake), sleep=lambda s: None)

    st = run_documents(db, client, [ipo], date(2026, 10, 30))
    assert st.discovered == 1 and st.downloaded == 1 and st.extracted == 1 and not st.errors
    doc = db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id)).scalar_one()
    assert doc.extraction_status == "extracted" and doc.original_filename == "Testco_RHP.pdf" and doc.page_count == 5
    stmts = db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id)).scalars().all()
    assert len(stmts) == 4 and all(s.data_status == "verified" and s.document_id == doc.id for s in stmts)
    fy26 = next(s for s in stmts if s.period_label == "FY2026")
    assert fy26.revenue == pytest.approx(90.0) and fy26.unit == "crore"
    item = db.execute(select(FinancialLineItem).where(FinancialLineItem.statement_id == fy26.id, FinancialLineItem.field == "revenue")).scalar_one()
    assert item.page == 3 and item.raw_text == "9,000.00" and item.unit == "lakh"
    db.refresh(ipo)
    assert ipo.pre_issue_shares == 5_000_000 and ipo.document_facts["auditor_qualifications"]["value"] == "none"
    assert ipo.post_issue_shares == pytest.approx(5_000_000 + 20 * 1e7 / 100)  # estimated at the upper band
    assert db.execute(select(func.count(PeerSnapshot.id)).where(PeerSnapshot.ipo_id == ipo.id)).scalar_one() == 3
    score = db.execute(select(ResearchScore).where(ResearchScore.ipo_id == ipo.id)).scalars().all()[-1]
    assert score.composite is not None and score.breakdown["basis"] == "unknown" and score.breakdown["periods_used"] == ["FY2024", "FY2025", "FY2026"]

    # re-run: nothing is due (already extracted with the current parser)
    calls = len(fake.calls)
    st2 = run_documents(db, client, [ipo], date(2026, 10, 30))
    assert st2.downloaded == 0 and len(fake.calls) == calls

    # forced re-check with an unchanged archive: HEAD only, no download
    doc.last_checked_at = None
    db.commit()
    from app.ingestion.document_service import DocRunStats, fetch

    assert fetch(client, db, doc, DocRunStats()) is None
    assert [m for m, _ in fake.calls[calls:]] == ["HEAD"]


def test_revised_document_keeps_history(db, tmp_path):
    p1, p2 = tmp_path / "a.pdf", tmp_path / "b.pdf"
    build_rhp(str(p1))
    build_rhp(str(p2), {"revenue": [2_500.00, 9_100.00, 7_500.00, 6_000.00], "other_exp": [330.00, 1_320.00, 1_000.00, 820.00]})
    ipo = _ipo(db)
    fake = FakeArchive(_zip(("RHP_TESTCO/Testco_RHP.pdf", p1.read_bytes())))
    client = PoliteClient(min_interval=0, transport=httpx.MockTransport(fake), sleep=lambda s: None)
    run_documents(db, client, [ipo], date(2026, 10, 30))
    doc = db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id)).scalar_one()
    fake.body, fake.etag = _zip(("RHP_TESTCO/Testco_RHP.pdf", p2.read_bytes())), '"v2"'
    from app.ingestion.document_service import DocRunStats, fetch, process

    new = fetch(client, db, doc, DocRunStats())
    assert new is not None and new.id != doc.id  # a new document record; the old one stays
    process(db, new)
    rows = db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.period_label == "FY2026")
                      .order_by(FinancialStatement.id)).scalars().all()
    assert [r.is_current for r in rows] == [False, True] and rows[1].supersedes_id == rows[0].id
    assert rows[0].revenue == pytest.approx(90.0) and rows[1].revenue == pytest.approx(91.0)
    assert db.execute(select(func.count(DocumentExtraction.id))).scalar_one() == 2


def test_unreadable_document_is_reported_not_invented(db, tmp_path):
    scanned = pymupdf.open()
    for _ in range(25):
        scanned.new_page()  # pages without a text layer, like a scanned prospectus
    ipo = _ipo(db)
    fake = FakeArchive(_zip(("RHP_TESTCO/RHP.pdf", scanned.tobytes())))
    client = PoliteClient(min_interval=0, transport=httpx.MockTransport(fake), sleep=lambda s: None)
    st = run_documents(db, client, [ipo], date(2026, 10, 30))
    doc = db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id)).scalar_one()
    assert st.extracted == 1 and doc.extraction_status == "not_found" and "no text layer" in (doc.extraction_error or "")
    assert db.execute(select(func.count(FinancialStatement.id))).scalar_one() == 0


def test_documents_api_calendar_and_exceptions(client, db, rhp):
    path, _ = rhp
    ipo = _ipo(db)
    fake = FakeArchive(_zip(("RHP_TESTCO/Testco_RHP.pdf", path.read_bytes())))
    run_documents(db, PoliteClient(min_interval=0, transport=httpx.MockTransport(fake), sleep=lambda s: None), [ipo], date(2026, 10, 30))
    docs = client.get("/api/documents", params={"ipo_id": ipo.id}).json()
    assert docs[0]["extraction_status"] == "extracted" and docs[0]["file_url"]
    f = client.get(docs[0]["file_url"])
    assert f.status_code == 200 and f.headers["content-type"] == "application/pdf"
    fin = client.get(f"/api/ipos/{ipo.id}/financials").json()
    sid = next(s["id"] for s in fin["statements"] if s["period_label"] == "FY2026")
    prov = client.get(f"/api/ipos/{ipo.id}/financials/{sid}/provenance").json()
    assert any(i["field"] == "revenue" and i["page"] == 3 for i in prov["items"]) and prov["checks"]
    runs = client.get(f"/api/documents/{docs[0]['id']}/extractions").json()["runs"]
    assert runs[0]["status"] == "extracted" and {s["kind"] for s in runs[0]["statements"]} == {"bs", "pl", "cf"}
    cal = client.get("/api/calendar", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    kinds = {(e["event"], e["status"]) for e in cal["events"] if e["ipo_id"] == ipo.id}
    assert ("open", "confirmed") in kinds and ("close", "confirmed") in kinds
    assert client.get("/api/calendar", params={"start": "2026-11-30", "end": "2026-11-01"}).status_code == 422
    exc = client.get("/api/data/exceptions").json()
    assert exc["documents"] == [] and exc["statements_requiring_review"] == []
    assert client.post(f"/api/admin/documents/{docs[0]['id']}/reprocess").status_code in (401, 403)


def test_reprocessing_a_document_replaces_its_earlier_reading(db, rhp):
    """Rows an older parser wrote from the same document are retired, even if they were marked verified."""
    from app.ingestion.document_service import process

    path, _ = rhp
    ipo = _ipo(db)
    fake = FakeArchive(_zip(("RHP_TESTCO/Testco_RHP.pdf", path.read_bytes())))
    run_documents(db, PoliteClient(min_interval=0, transport=httpx.MockTransport(fake), sleep=lambda s: None), [ipo], date(2026, 10, 30))
    doc = db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id)).scalar_one()
    # simulate a mislabelled period left by an older parser version
    stale = FinancialStatement(company_id=ipo.company_id, period_label="FY2023", period_end=date(2023, 12, 31), period_months=12, basis="unknown",
                               document_id=doc.id, data_status="verified", validation_status="passed", revenue=999.0, is_current=True)
    db.add(stale)
    fy26 = db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.period_label == "FY2026",
                                                       FinancialStatement.is_current.is_(True))).scalar_one()
    fy26.revenue = 1.0  # a wrong value from the older reading
    db.commit()
    res = process(db, doc)
    assert res["statements_retired"] == 1 and res["statements_superseded"] == 1
    db.refresh(stale)
    assert stale.is_current is False
    current = db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.period_label == "FY2026",
                                                          FinancialStatement.is_current.is_(True))).scalar_one()
    assert current.revenue == pytest.approx(90.0)
