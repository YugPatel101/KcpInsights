from __future__ import annotations

import copy
import io
import json
from datetime import date

from sqlalchemy import select

from app.models import FinancialStatement, SourceRecord
from app.services.import_service import Report, upsert_statement, validate_bundle
from tests.conftest import register

BUNDLE = {
    "dataset_label": "test",
    "sources": [{"key": "rhp", "title": "RHP restated financials", "source_type": "document", "url": "https://www.sebi.gov.in/x", "data_status": "imported"}],
    "ipos": [{
        "company": {"name": "Imported Test Ltd", "sector": "Specialty Chemicals"},
        "issue": {"exchange": "NSE, BSE", "issue_type": "mainboard", "open_date": "2025-07-10", "close_date": "2025-07-14",
                  "price_band_low": 95, "price_band_high": 100, "issue_size_cr": 60, "fresh_issue_cr": 40, "ofs_cr": 20,
                  "post_issue_shares": 20000000, "pre_issue_shares": 16000000, "source_key": "rhp"},
        "unit": "lakh",
        "financials": [
            {"period_label": "FY2023", "period_end": "2023-03-31", "revenue": 10000, "ebitda": 1500, "pat": 800, "operating_cash_flow": 900,
             "total_equity": 8000, "total_debt": 3000, "cash_and_equivalents": 1000, "source_key": "rhp"},
            {"period_label": "FY2024", "period_end": "2024-03-31", "revenue": 12000, "ebitda": 1920, "pat": 1000, "operating_cash_flow": 1100,
             "total_equity": 9000, "total_debt": 3000, "cash_and_equivalents": 1200, "source_key": "rhp"},
        ],
        "peers": [{"name": "Peer A", "sector": "Specialty Chemicals", "as_of": "2025-07-01", "pe": 20, "source_key": "rhp"}],
    }],
}


def _upload(client, csrf, name, content, dry_run):
    return client.post("/api/imports/financials", files={"file": (name, io.BytesIO(content), "application/octet-stream")},
                       data={"dry_run": "true" if dry_run else "false"}, headers={"X-CSRF-Token": csrf})


def test_bundle_validation_errors():
    b = copy.deepcopy(BUNDLE)
    b["ipos"][0]["issue"]["close_date"] = "2025-07-01"
    _, rep = validate_bundle(b)
    assert not rep.as_dict()["ok"] and any("close_date" in e["message"] for e in rep.errors)
    b = copy.deepcopy(BUNDLE)
    b["ipos"][0]["financials"][1]["period_end"] = "2023-03-31"
    b["ipos"][0]["financials"][1]["period_label"] = "dup"
    _, rep = validate_bundle(b)
    assert any("duplicate financial periods" in e["message"] for e in rep.errors)
    b = copy.deepcopy(BUNDLE)
    b["ipos"][0]["unit"] = "furlongs"
    _, rep = validate_bundle(b)
    assert any("unsupported unit" in e["message"] for e in rep.errors)
    b = copy.deepcopy(BUNDLE)
    b["sources"][0]["data_status"] = "synthetic"
    _, rep = validate_bundle(b)
    assert any("synthetic" in e["message"] for e in rep.errors)
    b = copy.deepcopy(BUNDLE)
    b["ipos"][0]["financials"][0]["period_end"] = "2099-03-31"
    _, rep = validate_bundle(b, today=date(2026, 1, 1))
    assert any("future" in e["message"] for e in rep.errors)
    _, rep = validate_bundle({"sources": [], "ipos": []})
    assert rep.errors


def test_bundle_warnings_and_commit_with_unit_conversion(client, db):
    csrf = register(client)
    r = _upload(client, csrf, "b.json", json.dumps(BUNDLE).encode(), True).json()
    assert r["dry_run"] and r["report"]["ok"]
    msgs = " ".join(w["message"] for w in r["report"]["warnings"])
    assert "fewer than 3 annual periods" in msgs and "fewer than 3 peers" in msgs
    partial = copy.deepcopy(BUNDLE)
    del partial["ipos"][0]["financials"][0]["ebitda"]
    _, rep = validate_bundle(partial)
    assert any("missing fields: ebitda" in w["message"] for w in rep.warnings)
    r = _upload(client, csrf, "b.json", json.dumps(BUNDLE).encode(), False).json()
    assert r["committed"] and r["counts"]["financials"] == 2
    stmts = db.execute(select(FinancialStatement).order_by(FinancialStatement.period_end)).scalars().all()
    assert stmts[-1].revenue == 120.0 and stmts[-1].unit == "crore"  # 12,000 lakh -> 120 crore
    rec = db.get(SourceRecord, stmts[-1].source_record_id)
    assert "lakh" in rec.transformation and rec.raw_payload["raw_financials"][0]["unit"] == "lakh"
    ipo = client.get("/api/ipos", params={"q": "Imported Test"}).json()["items"][0]
    assert ipo["data_mode"] == "imported" and ipo["data_status"] == "imported"
    assert client.get(f"/api/ipos/{ipo['id']}").json()["can_edit"] is True
    s = client.get(f"/api/ipos/{ipo['id']}/scores").json()
    assert s["status"] == "incomplete" and s["coverage"] > 0  # imported evidence earns credit; not enough data to score


def test_non_admin_cannot_mark_verified(client, db):
    csrf = register(client)
    b = copy.deepcopy(BUNDLE)
    b["sources"][0]["data_status"] = "verified"
    r = _upload(client, csrf, "b.json", json.dumps(b).encode(), False).json()
    assert any("only administrators" in w["message"] for w in r["report"]["warnings"])
    assert all(s.data_status == "imported" for s in db.execute(select(FinancialStatement)).scalars())


def test_csv_import_validation_and_commit(client, db):
    csrf = register(client)
    _upload(client, csrf, "b.json", json.dumps(BUNDLE).encode(), False)
    header = "company_name,period_label,period_end,unit,source_title,data_status,revenue,pat,period_months"
    bad = f"{header}\nUnknown Co,FY2025,2025-03-31,crore,src,imported,10,1,12\nImported Test Ltd,FY2025,31/03/2025,crore,src,imported,10,1,12\n"
    r = _upload(client, csrf, "f.csv", bad.encode(), True).json()
    errs = " ".join(e["message"] for e in r["report"]["errors"])
    assert "not found" in errs and "invalid period_end" in errs
    dup = f"{header}\nImported Test Ltd,FY2025,2025-03-31,million,src,imported,1500,90,12\nImported Test Ltd,FY2025b,2025-03-31,crore,src,imported,150,9,12\n"
    r = _upload(client, csrf, "f.csv", dup.encode(), True).json()
    assert any("duplicate period" in e["message"] for e in r["report"]["errors"])
    good = f"{header}\nImported Test Ltd,FY2025,2025-03-31,million,src,imported,1500,90,12\n"
    r = _upload(client, csrf, "f.csv", good.encode(), False).json()
    assert r["committed"] and r["counts"]["financials"] == 1
    row = db.execute(select(FinancialStatement).where(FinancialStatement.period_label == "FY2025")).scalar_one()
    assert row.revenue == 150.0 and row.pat == 9.0
    assert _upload(client, csrf, "f.exe", b"MZ", True).status_code == 415
    assert client.get("/api/imports/templates/financials_csv").text.startswith("company_name,")


def test_verified_snapshot_is_never_overwritten(seeded):
    db = seeded
    from app.models import Company
    company = db.execute(select(Company)).scalars().first()
    vals = {"period_label": "FY2001", "period_end": date(2001, 3, 31), "period_months": 12, "unit": "crore", "currency": "INR",
            **{k: None for k in ("revenue", "ebitda", "ebit", "pat", "operating_cash_flow", "capex", "interest_expense", "total_assets",
                                 "total_liabilities", "total_debt", "cash_and_equivalents", "total_equity", "current_assets", "current_liabilities")}}
    rep = Report()
    assert upsert_statement(db, company.id, {**vals, "revenue": 100.0}, "verified", None, rep, "t") == "inserted"
    db.commit()
    assert upsert_statement(db, company.id, {**vals, "revenue": 999.0}, "imported", None, rep, "t") == "kept_verified"
    assert upsert_statement(db, company.id, {**vals, "revenue": 101.0}, "verified", None, rep, "t") == "versioned"
    db.commit()
    rows = db.execute(select(FinancialStatement).where(FinancialStatement.period_label == "FY2001")).scalars().all()
    assert sorted((r.revenue, r.is_current) for r in rows) == [(100.0, False), (101.0, True)]
