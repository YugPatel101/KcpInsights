"""Live-data ingestion tests. Network access is mocked with payloads captured from NSE on 2026-10-29."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.ingestion import normalizer as nz
from app.ingestion.http import PoliteClient, SourceError
from app.ingestion.ingestion_scheduler import IngestionRunner, acquire_lock, release_lock
from app.ingestion.ipo_data_service import UpsertStats, set_field, upsert_issue
from app.ingestion.sources.base import IssueRecord
from app.ingestion.sources.nse import NSEOfficialSource
from app.models import FieldChange, FieldObservation, IngestionJob, IPOIssue, JobLock, SubscriptionSnapshot, utcnow
from tests.conftest import register

FIX = Path(__file__).parent / "fixtures" / "nse"
TODAY = date(2026, 10, 29)


def _bhav_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BhavCopy_NSE_CM_0_0_0_20261028_F_0000.csv", (FIX / "bhavcopy_20261028.csv").read_text())
    return buf.getvalue()


class FakeNSE:
    """Serves fixtures; records calls; can be switched into failure modes."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mode = "ok"
        self.overrides: dict[str, object] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if self.mode == "down":
            return httpx.Response(503)
        if self.mode == "blocked":
            return httpx.Response(403, text="Access Denied")
        for key, payload in self.overrides.items():
            if key in url:
                return httpx.Response(200, json=payload)
        path = request.url.path
        if path == "/api/all-upcoming-issues":
            return httpx.Response(200, json=json.loads((FIX / "upcoming.json").read_text()))
        if path == "/api/ipo-current-issue":
            return httpx.Response(200, json=json.loads((FIX / "current.json").read_text()))
        if path == "/api/public-past-issues":
            return httpx.Response(200, json=json.loads((FIX / "past.json").read_text()))
        if path == "/api/ipo-detail":
            sym = request.url.params.get("symbol")
            if sym not in ("JPL", "BCSSL"):  # only these two detail payloads were captured
                return httpx.Response(200, json={"companyName": sym, "metaInfo": {}, "issueInfo": {"dataList": []}, "activeCat": {}})
            return httpx.Response(200, json=json.loads((FIX / ("jpl.json" if sym == "JPL" else "detail.json")).read_text()))
        if path == "/api/ipo-active-category":
            return httpx.Response(200, json=json.loads((FIX / "detail.json").read_text())["activeCat"])
        if "BhavCopy_NSE_CM_0_0_0_20261028" in path:
            return httpx.Response(200, content=_bhav_zip(), headers={"content-type": "application/zip"})
        if "BhavCopy" in path:
            return httpx.Response(404)
        if "bseindia" in url:
            return httpx.Response(403, text="Access Denied")
        return httpx.Response(404)


@pytest.fixture()
def fake():
    return FakeNSE()


@pytest.fixture()
def client_for(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("KCP_CACHE_DIR", str(tmp_path / "cache"))
    from app.config import get_settings

    get_settings.cache_clear()
    yield lambda: PoliteClient(min_interval=0, backoff_base=0, transport=httpx.MockTransport(fake), sleep=lambda _s: None)
    get_settings.cache_clear()


@pytest.fixture()
def runner(db, client_for):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    return IngestionRunner(factory, client=client_for(), today=lambda: TODAY)


# ----------------------------------------------------------------------------- normaliser
def test_parsers():
    assert nz.parse_date("29-Oct-2026") == date(2026, 10, 29)
    assert nz.parse_date("23-OCT-2026") == date(2026, 10, 23)
    assert nz.parse_date("2026-10-28") == date(2026, 10, 28)
    assert nz.parse_date("") is None and nz.parse_date("31-Foo-2026") is None and nz.parse_date(None) is None
    assert nz.parse_number("1.6533012E7") == 16533012.0
    assert nz.parse_number("1,65,32,880") == 16532880.0
    assert nz.parse_number("  1119") == 1119.0 and nz.parse_number("") is None
    assert nz.parse_price_band("Rs.78 to Rs.82") == (78.0, 82.0)
    assert nz.parse_price_band("Rs. 1065 to Rs. 1119 per Equity Share") == (1065.0, 1119.0)
    assert nz.parse_price_band("Rs.90 to Rs.80") == (None, None)
    assert nz.parse_first_int("182 Equity Shares and in multiples thereof") == 182
    assert nz.parse_rupees_per_share("Rs. 10 per Equity Share") == 10.0
    assert nz.parse_update_time("Updated as on 29-Oct-2026 17:00:00") == datetime(2026, 10, 29, 17, 0)
    assert nz.issue_type_for_series("SME") == "sme" and nz.issue_type_for_series("EQ") == "mainboard" and nz.issue_type_for_series("N3") is None
    assert nz.add_working_days(date(2026, 10, 30), 1) == date(2026, 11, 2)  # Friday + 1 -> Monday
    assert nz.normalize_company_name("M. K. Sons Fine Jewels Limited") == nz.normalize_company_name("M K Sons Fine Jewels Ltd")


def test_subscription_category_mapping_and_issue_components():
    assert nz.subscription_category("Qualified Institutional Buyers(QIBs)", "1") == "qib"
    assert nz.subscription_category("Foreign Institutional Investors(FIIs)", "1(a)") is None
    assert nz.subscription_category("Non Institutional Investors", "2") == "nii"
    assert nz.subscription_category("Retail Individual Investors(RIIs)", "3") == "retail"
    assert nz.subscription_category("Total", None) == "total"
    assert nz.parse_issue_components("Initial Public Offer comprising of Fresh Issue of up to 54,26,400 Equity Shares and Offer for sale of up to "
                                     "6,03,600 Equity Shares (including market maker portion of 3,04,800 equity shares)") == {"fresh_shares": 5426400.0, "ofs_shares": 603600.0}
    rupees = "Fresh Issue aggregating upto Rs. 1,830.57 million (including Anchor portion of 65,97,500 Equity Shares)"
    assert nz.parse_issue_components(rupees) == {"fresh_cr": pytest.approx(183.057)}
    assert nz.parse_issue_components("Fresh Issue of Rs 100 crore and 5,00,000 equity shares") is None  # ambiguous -> unavailable
    assert nz.parse_issue_components("Something else") is None


def test_nse_adapter_parses_fixtures(client_for):
    nse = NSEOfficialSource(client_for())
    up = nse.fetch_upcoming_ipos()
    assert up.status == "ok" and up.data
    sme = next(r for r in up.data if r.series == "SME")
    assert sme.issue_type == "sme" and sme.lot_size and sme.price_band_low < sme.price_band_high
    cur = nse.fetch_open_ipos().data
    bcssl = next(r for r in cur if r.symbol == "BCSSL")
    assert (bcssl.open_date, bcssl.close_date, bcssl.price_band_high) == (date(2026, 10, 29), date(2026, 11, 2), 82.0)
    assert bcssl.shares_offered == 16533012  # shares, not rupees
    rec, subs = nse.fetch_ipo_details("BCSSL", "EQ").data
    assert rec.face_value == 10 and rec.lot_size == 182 and rec.registrar == "KFin Technologies Limited"
    assert rec.offer_document_url == "https://nsearchives.nseindia.com/content/ipo/RHP_BCSSL.zip"
    total = next(s for s in subs if s.category == "total")
    assert total.basis == "consolidated" and total.as_of == datetime(2026, 10, 29, 17, 0) and total.times_subscribed == pytest.approx(2.6731, rel=1e-3)
    assert {s.category for s in subs} == {"qib", "nii", "retail", "total"}
    past = nse.fetch_recently_listed_ipos(date(2026, 1, 1)).data
    dated = [r for r in past if r.listing_date and r.close_date]
    assert dated and all(0 <= (r.listing_date - r.close_date).days <= 30 for r in dated)
    assert not any(r.symbol in ("13DCCL28", "1150VIES30", "ANNAPURNA", "PARTYPP") for r in past)


# ----------------------------------------------------------------------------- http policy
def test_rate_limit_and_retry_policy():
    calls: list[float] = []
    waits: list[float] = []
    state = {"n": 0}

    def flaky(_req: httpx.Request) -> httpx.Response:
        state["n"] += 1
        calls.append(state["n"])
        return httpx.Response(503) if state["n"] < 3 else httpx.Response(200, json=[1])

    c = PoliteClient(min_interval=5, backoff_base=1, max_retries=2, transport=httpx.MockTransport(flaky), sleep=waits.append)
    assert c.get_json("https://www.nseindia.com/x") == [1]
    assert state["n"] == 3 and c.requests_made == 3
    assert any(w >= 4 for w in waits)  # minimum spacing between requests to one host was enforced
    c2 = PoliteClient(min_interval=0, backoff_base=0, max_retries=5, transport=httpx.MockTransport(lambda r: httpx.Response(403)), sleep=lambda _s: None)
    with pytest.raises(SourceError) as e:
        c2.get("https://www.bseindia.com/x")
    assert e.value.kind == "access_denied" and c2.requests_made == 1  # never retried
    c3 = PoliteClient(min_interval=0, backoff_base=0, max_retries=2, transport=httpx.MockTransport(lambda r: httpx.Response(503)), sleep=lambda _s: None)
    with pytest.raises(SourceError):
        c3.get("https://www.nseindia.com/y")
    assert c3.requests_made == 3  # bounded: 1 try + 2 retries
    c4 = PoliteClient(min_interval=0, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")), sleep=lambda _s: None)
    with pytest.raises(SourceError) as e4:
        c4.get_json("https://www.nseindia.com/z")
    assert e4.value.kind == "parse"


# ----------------------------------------------------------------------------- upserts & provenance
def test_discovery_creates_then_updates_without_duplicates(db, runner, fake):
    r1 = runner.run("discover", "test")
    assert r1["status"] == "success" and r1["records_created"] > 0
    n = db.execute(select(func.count(IPOIssue.id))).scalar_one()
    r2 = runner.run("discover", "test")
    assert r2["records_created"] == 0 and r2["fields_changed"] == 0
    assert db.execute(select(func.count(IPOIssue.id))).scalar_one() == n
    bcssl = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "BCSSL")).scalar_one()
    assert bcssl.data_mode == "source" and bcssl.data_status == "verified" and bcssl.price_band_high == 82
    assert bcssl.listing_date_status == "expected" and bcssl.listing_date == nz.add_working_days(date(2026, 11, 2), 3)
    obs = db.execute(select(FieldObservation).where(FieldObservation.ipo_id == bcssl.id, FieldObservation.field == "listing_date")).scalar_one()
    assert obs.data_status == "estimated" and "T+3" in (obs.basis or "")
    # second run re-verified instead of duplicating observations
    assert db.execute(select(func.count(FieldObservation.id)).where(FieldObservation.ipo_id == bcssl.id, FieldObservation.field == "price_band_high")).scalar_one() == 1


def test_field_change_history_and_conflicts(db, runner, fake):
    runner.run("discover", "test")
    upcoming = json.loads((FIX / "upcoming.json").read_text())
    target = next(r for r in upcoming if r["symbol"] == "VPFL")
    target["issueStartDate"], target["issueEndDate"] = "05-Nov-2026", "09-Nov-2026"  # dates moved by the exchange
    fake.overrides["all-upcoming-issues"] = upcoming
    runner.client._cache.clear()
    r = runner.run("discover", "test")
    assert r["fields_changed"] > 0
    ipo = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "VPFL")).scalar_one()
    db.refresh(ipo)
    assert ipo.open_date == date(2026, 11, 5)
    changes = {c.field: c for c in db.execute(select(FieldChange).where(FieldChange.ipo_id == ipo.id)).scalars()}
    assert json.loads(changes["open_date"].old_value) == "2026-11-02" and json.loads(changes["open_date"].new_value) == "2026-11-05"
    assert "listing_date" in changes  # expected listing date recomputed from the new close date
    # a secondary source may not overwrite the official value
    st = UpsertStats()
    assert set_field(db, ipo, "price_band_high", 999.0, source_key="some_blog", source_url=None, status="secondary_source", stats=st) is False
    from app.ingestion import source_registry

    source_registry.SOURCE_AUTHORITY["some_blog"] = "secondary"
    assert set_field(db, ipo, "price_band_high", 999.0, source_key="some_blog", source_url=None, status="secondary_source", stats=st) is False
    assert ipo.price_band_high == 94
    db.flush()
    rejected = db.execute(select(FieldObservation).where(FieldObservation.source_key == "some_blog")).scalars().all()
    assert rejected and all(o.applied is False and o.conflict for o in rejected)


def test_imported_record_is_matched_and_estimate_never_overrides_sourced_value(db, seeded):
    from app.models import Company

    company = Company(name="Bombay Coated and Special Steels Ltd", sector="Metals", data_status="imported")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="NSE", issue_type="mainboard", data_mode="imported", data_status="imported",
                   open_date=date(2026, 10, 29), close_date=date(2026, 11, 2), listing_date=date(2026, 11, 9), price_band_high=80)
    db.add(ipo)
    db.commit()
    rec = IssueRecord(symbol="BCSSL", company_name="Bombay Coated and Special Steels Limited", series="EQ", issue_type="mainboard",
                      source_url="https://www.nseindia.com/x", api_url="https://www.nseindia.com/api/x", open_date=date(2026, 10, 29),
                      close_date=date(2026, 11, 2), price_band_low=78, price_band_high=82)
    st = upsert_issue(db, rec, source_key="nse_ipo")
    db.commit()
    db.refresh(ipo)
    assert st.created == 0 and ipo.nse_symbol == "BCSSL"
    assert ipo.price_band_high == 82  # official exchange value outranks the import
    assert ipo.listing_date == date(2026, 11, 9)  # imported listing date kept; estimate not applied over it
    assert any("matched an imported record" in w for w in st.warnings)


def test_subscriptions_details_and_listing_prices(db, runner, fake):
    runner.run("discover", "test")
    d = runner.run("details", "test")
    assert d["status"] in ("success", "partial") and d["records_discovered"] > 0
    bcssl = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "BCSSL")).scalar_one()
    db.refresh(bcssl)
    assert bcssl.face_value == 10 and bcssl.registrar == "KFin Technologies Limited"
    assert bcssl.issue_size_cr == pytest.approx(183.057, rel=1e-4) and bcssl.fresh_issue_cr == pytest.approx(183.057, rel=1e-4)
    subs = db.execute(select(SubscriptionSnapshot).where(SubscriptionSnapshot.ipo_id == bcssl.id)).scalars().all()
    assert {s.category for s in subs} >= {"qib", "retail", "total"} and all(s.basis == "consolidated" for s in subs)
    s2 = runner.run("subscriptions", "test")
    assert s2["status"] in ("success", "partial")
    assert db.execute(select(func.count(SubscriptionSnapshot.id)).where(SubscriptionSnapshot.ipo_id == bcssl.id)).scalar_one() == len(subs)  # same timestamp -> no duplicate
    lst = runner.run("listings", "test")
    assert lst["status"] in ("success", "partial")
    jpl = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "JPL")).scalar_one()
    db.refresh(jpl)
    assert jpl.listing_date == date(2026, 10, 28) and jpl.listing_date_status == "actual"
    assert jpl.final_issue_price == 1119 and jpl.listing_price == 1358.0 and jpl.listing_close_price == 1417.5
    assert jpl.listing_price_basis == "listing_day_open" and jpl.listing_data_status == "verified"
    from app.services.ipo_service import listing_return_pct

    assert listing_return_pct(jpl) == pytest.approx((1358 - 1119) / 1119 * 100, abs=0.01)


def test_listing_price_rejected_when_reference_price_disagrees(db, runner, fake):
    runner.run("discover", "test")
    jpl = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "JPL")).scalar_one()
    jpl.final_issue_price = 1000.0  # bhavcopy previous close (1119) will not match
    db.commit()
    out = runner.run("listings", "test")
    db.refresh(jpl)
    assert jpl.listing_price is None
    assert any("differs from issue price" in w for w in db.get(IngestionJob, out["id"]).detail.get("warnings", []))


def test_source_outage_keeps_last_good_data(db, runner, fake):
    runner.run("discover", "test")
    n = db.execute(select(func.count(IPOIssue.id))).scalar_one()
    fake.mode = "down"
    runner.client._cache.clear()
    out = runner.run("discover", "test")
    assert out["status"] == "failed" and out["errors"]
    assert db.execute(select(func.count(IPOIssue.id))).scalar_one() == n
    from app.models import DataSource

    src = db.execute(select(DataSource).where(DataSource.key == "nse_ipo")).scalar_one()
    db.refresh(src)
    assert src.health_status in ("degraded", "down") and src.last_success_at is not None
    fake.mode = "blocked"
    runner.client._cache.clear()
    runner.run("discover", "test")
    db.refresh(src)
    assert src.health_status == "blocked"


def test_job_locks_prevent_overlap(db, runner):
    assert acquire_lock(db, "source:nse")
    db.query(JobLock).filter(JobLock.key == "source:nse").update({"owner": "someone-else"})
    db.commit()
    out = runner.run("discover", "test")
    assert out["status"] == "skipped" and "holds" in out["detail"]["reason"]
    db.query(JobLock).filter(JobLock.key == "source:nse").update({"expires_at": utcnow() - timedelta(minutes=1)})
    db.commit()
    assert runner.run("health", "test")["status"] == "success"
    assert acquire_lock(db, "source:nse")  # expired lock can be taken over
    release_lock(db, "source:nse")


def test_subscription_job_makes_no_requests_when_nothing_is_open(db, client_for, fake):
    from sqlalchemy.orm import sessionmaker

    r = IngestionRunner(sessionmaker(bind=db.get_bind()), client=client_for(), today=lambda: date(2030, 1, 1))
    out = r.run("subscriptions", "test")
    assert out["status"] == "skipped" and out["requests_made"] == 0


def test_stale_detection():
    from app.ingestion.data_quality_service import ipo_freshness

    ipo = IPOIssue(data_mode="source", last_verified_at=utcnow() - timedelta(hours=30), price_band_high=10, open_date=date(2026, 1, 1),
                   close_date=date(2026, 1, 3), lot_size=10, issue_size_cr=None)
    ipo.subscriptions = []
    f = ipo_freshness(ipo, "upcoming")
    assert f["is_stale"] and "issue size (₹)" in f["missing_critical"]
    demo = IPOIssue(data_mode="demo")
    demo.subscriptions = []
    assert ipo_freshness(demo, "upcoming")["is_stale"] is False


# ----------------------------------------------------------------------------- API
class FrozenDate(date):
    @classmethod
    def today(cls) -> date:  # type: ignore[override]
        return TODAY


def test_live_endpoints_and_admin_sync(client, db, runner, monkeypatch):
    import app.api.routes.live as live
    import app.services.ipo_service as ipo_service

    monkeypatch.setattr(ipo_service, "date", FrozenDate)
    monkeypatch.setattr(live, "date", FrozenDate)
    runner.run("discover", "test")
    runner.run("details", "test")
    up = client.get("/api/ipos/upcoming").json()
    op = client.get("/api/ipos/open").json()
    assert op["total"] >= 1 and all(i["status"] == "open" for i in op["items"])
    assert all(i["data_mode"] == "source" for i in up["items"] + op["items"])
    ov = client.get("/api/market/overview").json()
    assert ov["data"]["live_records"] > 0 and ov["data"]["last_successful_sync_at"]
    bc = next(i for i in op["items"] if i["nse_symbol"] == "BCSSL")
    sub = client.get(f"/api/ipos/{bc['id']}/subscription").json()
    assert sub["latest_as_of"] == "2026-10-29T17:00:00" and {r["category"] for r in sub["latest"]} >= {"qib", "total"}
    det = client.get(f"/api/ipos/{bc['id']}").json()
    listing = next(k for k in det["key_dates"] if k["key"] == "listing")
    assert listing["label"] == "Listing (expected)" and listing["status"] == "estimated"
    prov = client.get(f"/api/ipos/{bc['id']}/provenance").json()["fields"]
    assert prov["price_band_high"]["data_status"] == "verified" and prov["listing_date"]["data_status"] == "estimated"
    fr = client.get("/api/data/freshness").json()
    assert any(s["key"] == "nse_ipo" and s["health_status"] == "healthy" for s in fr["sources"])
    st = client.get("/api/data/sync-status").json()
    assert st["jobs"] and st["scheduler"]["running"] is False
    # ETag / conditional request
    r1 = client.get("/api/market/overview")
    r2 = client.get("/api/market/overview", headers={"If-None-Match": r1.headers["etag"]})
    assert r2.status_code == 304
    # admin-only sync
    assert client.post("/api/admin/data-sync", json={"job": "discover"}).status_code == 401
    csrf = register(client)
    assert client.post("/api/admin/data-sync", json={"job": "discover"}, headers={"X-CSRF-Token": csrf}).status_code == 403


def test_demo_hidden_once_real_data_exists(client, seeded, runner):
    assert client.get("/api/ipos").json()["demo_included"] is True
    runner.run("discover", "test")
    body = client.get("/api/ipos", params={"page_size": 100}).json()
    assert body["demo_included"] is False and all(i["data_mode"] != "demo" for i in body["items"])
    assert client.get("/api/ipos", params={"include_demo": "true", "page_size": 100}).json()["demo_included"] is True


# ----------------------------------------------------------------------------- research agent on live data
def test_agent_answers_live_questions_with_citations(db, runner):
    from app.agents.ipo_research_agent import IPOResearchAgent, parse_date_range
    from app.config import Settings

    runner.run("discover", "test")
    runner.run("details", "test")
    s = Settings(ai_provider="deterministic")
    assert parse_date_range("Which IPOs are opening next week?", TODAY) == (date(2026, 11, 2), date(2026, 11, 8), "next week")

    res = IPOResearchAgent(db, None, s, today=TODAY).run("Which IPOs are opening next week?")
    assert [t["tool"] for t in res["tool_calls"]] == ["search_ipos"]
    texts = " ".join(p["text"] for p in res["answer"]["points"])
    assert "Vedant Poly Fabs" in texts and "2026-11-02" in texts  # VPFL opens Mon 2 Nov per NSE
    ev = {e["id"]: e for e in res["evidence"]}
    cited = [ev[i] for p in res["answer"]["points"] for i in p["evidence"]]
    assert cited and all(c["url"] and c["url"].startswith("https://www.nseindia.com/") for c in cited)

    bc = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "BCSSL")).scalar_one()
    res2 = IPOResearchAgent(db, None, s, today=TODAY).run("When is Bombay Coated expected to list?")
    listing = next(p for p in res2["answer"]["points"] if p["text"].startswith("Listing (expected)"))
    assert listing["kind"] == "calculation" and "T+3" in listing["text"]
    assert res2["ipo_ids"] == [bc.id]

    res3 = IPOResearchAgent(db, None, s, today=TODAY).run("What is the latest subscription status?", context_ipo_id=bc.id)
    sub = next(p for p in res3["answer"]["points"] if p["text"].startswith("Subscription as of"))
    assert "2026-10-29T17:00:00" in sub["text"] and "QIB 6.55x" in sub["text"] and sub["kind"] == "fact"

    res4 = IPOResearchAgent(db, None, s, today=TODAY).run("Show me the source for that listing date", context_ipo_id=bc.id)
    assert "get_source_provenance" in [t["tool"] for t in res4["tool_calls"]]


def test_model_answer_stating_estimates_as_facts_is_labelled(db, runner):
    """A small local model presented an upper-band issue size as a plain fact; the validator must label it."""
    from app.agents.ipo_research_agent import IPOResearchAgent
    from app.config import Settings
    from app.services.llm_provider import ProviderSelection

    runner.run("discover", "test")
    runner.run("details", "test")
    bc = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "BCSSL")).scalar_one()
    bc.issue_size_cr = None  # as for live SME issues whose size NSE gives only in shares
    assert set_field(db, bc, "issue_size_cr", 56.682, source_key="nse_ipo:derived", source_url=None, status="estimated",
                     basis="share counts x upper end of the price band", stats=UpsertStats())
    db.commit()
    assert bc.listing_date_status == "expected"
    lst = bc.listing_date.strftime("%B %-d, %Y")

    class Model:
        name, model = "fake", "fake-model"

        def chat_json(self, system, messages, schema, timeout=None):
            if "summary" not in schema["properties"]:
                return {"action": "final"}
            assert "(estimated: share counts x upper end of the price band)" in messages[0]["content"]  # engine point is labelled
            return {"summary": f"Bombay Coated's issue size is ₹{bc.issue_size_cr} crore and it lists on {lst}."}

    s = Settings(ai_provider="ollama")
    res = IPOResearchAgent(db, None, s, ProviderSelection(Model(), "ollama", "mock", []), today=TODAY).run("Tell me about this IPO", context_ipo_id=bc.id)
    assert res["mode"] == "ollama:fake-model"
    assert res["answer"]["summary"] == f"Bombay Coated's issue size is ₹56.682 crore (estimated) and it lists on {lst} (expected)."
    size = next(p for p in res["answer"]["points"] if "issue size" in p["text"])
    assert size["kind"] == "calculation"
    assert any("labelled 2 estimated value(s)" in w for w in res["warnings"])


def test_busy_calendar_answer_stays_within_answer_size(db, runner):
    from app.agents.ipo_research_agent import IPOResearchAgent
    from app.config import Settings

    runner.run("discover", "test")
    runner.run("listings", "test")
    res = IPOResearchAgent(db, None, Settings(ai_provider="deterministic"), today=date(2026, 9, 21)).run(
        "Which IPOs list or get allotted in the next 3 weeks?")
    events = next(c for c in res["tool_calls"] if c["tool"] == "get_listing_schedule")
    assert int(events["summary"].split()[0]) > 12  # more events than an answer can hold
    assert 0 < len(res["answer"]["points"]) <= 12
    assert all(p["text"][:10].count("-") == 2 for p in res["answer"]["points"])  # grouped one point per date


def test_model_answer_with_misattributed_dates_falls_back(db, runner):
    from app.agents.ipo_research_agent import IPOResearchAgent
    from app.config import Settings
    from app.services.llm_provider import ProviderSelection

    runner.run("discover", "test")
    runner.run("details", "test")
    bc = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "BCSSL")).scalar_one()

    class Model:
        name, model = "fake", "fake-model"

        def chat_json(self, system, messages, schema, timeout=None):
            if "summary" not in schema["properties"]:
                return {"action": "final"}
            return {"summary": f"Bombay Coated bidding starts on {bc.allotment_date.isoformat()}."}  # the allotment date, called the opening

    res = IPOResearchAgent(db, None, Settings(ai_provider="ollama"), ProviderSelection(Model(), "ollama", "mock", []), today=TODAY).run(
        "When does it open?", context_ipo_id=bc.id)
    assert res["mode"] == "deterministic"
    assert any("AI summary rejected" in w and "allotment" in w for w in res["warnings"])


def test_agent_refreshes_only_stale_records_and_reports_it(db, runner):
    from app.agents.ipo_research_agent import IPOResearchAgent
    from app.config import Settings

    runner.run("discover", "test")
    bc = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "BCSSL")).scalar_one()
    calls: list[int] = []

    def refresher(ipo_id: int) -> dict:
        calls.append(ipo_id)
        return {"refreshed": False, "reason": "source unavailable; using stored data"}

    s = Settings(ai_provider="deterministic")
    IPOResearchAgent(db, None, s, refresher=refresher, today=TODAY).run("status?", context_ipo_id=bc.id)
    assert calls == []  # fresh record: no upstream request
    bc.last_verified_at = utcnow() - timedelta(days=3)
    db.commit()
    res = IPOResearchAgent(db, None, s, refresher=refresher, today=TODAY).run("What is the latest status?", context_ipo_id=bc.id)
    assert calls == [bc.id]
    assert any("live refresh" in w for w in res["warnings"]) and any("Stale data" in x for x in res["answer"]["limitations"])


def test_refresh_single_is_bounded(db, runner, fake):
    runner.run("discover", "test")
    bc = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == "BCSSL")).scalar_one()
    assert runner.refresh_single(bc.id)["refreshed"] is False  # verified moments ago
    bc.last_verified_at = utcnow() - timedelta(hours=2)
    db.commit()
    n = len(fake.calls)
    out = runner.refresh_single(bc.id)
    assert out["refreshed"] is True and len(fake.calls) == n + 1  # exactly one upstream request


def test_dead_process_locks_and_jobs_are_recovered(db):
    import socket

    from app.ingestion.ingestion_scheduler import recover_interrupted_jobs

    dead = f"{socket.gethostname()}:999999:abc"  # no such PID
    db.add(JobLock(key="source:nse", owner=dead, acquired_at=utcnow(), expires_at=utcnow() + timedelta(minutes=30)))
    db.add(IngestionJob(job_type="details", trigger="schedule", status="running", detail={"owner": dead}))
    db.commit()
    assert recover_interrupted_jobs(db) == 1
    assert db.get(JobLock, "source:nse") is None
    job = db.execute(select(IngestionJob)).scalar_one()
    assert job.status == "failed" and "interrupted" in job.errors[0]["error"]
    db.add(JobLock(key="source:nse", owner=dead, acquired_at=utcnow(), expires_at=utcnow() + timedelta(minutes=30)))
    db.commit()
    assert acquire_lock(db, "source:nse")  # a dead owner's unexpired lock is taken over


def test_chat_api_discovery_question_is_audited(client, db, runner):
    from app.models import ToolCallAudit

    runner.run("discover", "test")
    r = client.post("/api/agent/chat", json={"message": "Which IPOs are opening next week?"})
    assert r.status_code == 200, r.text
    calls = db.execute(select(ToolCallAudit)).scalars().all()
    assert calls and calls[0].tool_name == "search_ipos" and isinstance(calls[0].arguments["opening_from"], str)


def test_unconfirmed_listing_is_flagged_not_left_as_upcoming():
    from app.ingestion.data_quality_service import ipo_freshness

    ipo = IPOIssue(data_mode="source", last_verified_at=utcnow(), listing_date=date.today() - timedelta(days=20), listing_date_status="expected",
                   price_band_high=10, open_date=date.today() - timedelta(days=30), close_date=date.today() - timedelta(days=28), lot_size=1, issue_size_cr=5)
    ipo.subscriptions = []
    f = ipo_freshness(ipo, "closed")
    assert f["is_stale"] and f.get("listing_unconfirmed") and "BSE only" in f["stale_reasons"][0]
