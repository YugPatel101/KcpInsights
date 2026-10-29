from __future__ import annotations

from sqlalchemy import inspect

from tests.conftest import ipo_id_by_name, register


def test_migrations_create_schema(db):
    tables = set(inspect(db.get_bind()).get_table_names())
    for t in ("users", "user_sessions", "ipo_issues", "financial_statements", "source_records", "research_scores",
              "scoring_config_versions", "prediction_model_versions", "agent_conversations", "tool_call_audits", "alembic_version"):
        assert t in tables


def test_health_and_empty_state(client):
    assert client.get("/api/health").json()["database"] == "ok"
    r = client.get("/api/ipos")
    assert r.status_code == 200 and r.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
    dash = client.get("/api/dashboard/summary").json()
    assert dash["totals"]["ipos"] == 0 and dash["scatter"] == []


def test_list_filter_sort_paginate(client, seeded):
    allr = client.get("/api/ipos", params={"page_size": 100}).json()
    assert allr["total"] == 10
    assert all(i["data_status"] == "synthetic" and i["data_mode"] == "demo" for i in allr["items"])
    sme = client.get("/api/ipos", params={"issue_type": "sme"}).json()
    assert sme["total"] == 2 and all(i["issue_type"] == "sme" for i in sme["items"])
    listed = client.get("/api/ipos", params={"status": "listed"}).json()
    assert listed["total"] == 3 and all(i["listing_return_pct"] is not None for i in listed["items"])
    srt = client.get("/api/ipos", params={"sort": "-composite", "page_size": 100}).json()["items"]
    comps = [i["scores"]["composite"] for i in srt]
    nums = [c for c in comps if c is not None]
    assert nums == sorted(nums, reverse=True) and comps[-1] is None  # missing sorts last
    p2 = client.get("/api/ipos", params={"page": 2, "page_size": 4}).json()
    assert len(p2["items"]) == 4 and p2["total"] == 10
    q = client.get("/api/ipos", params={"q": "aravalli"}).json()
    assert q["total"] == 1
    assert client.get("/api/ipos", params={"min_quality": 101}).status_code == 422
    hi = client.get("/api/ipos", params={"risk_level": "low"}).json()
    assert all(i["scores"]["risk_level"] == "low" for i in hi["items"])


def test_detail_financials_scores_sources(client, seeded):
    iid = ipo_id_by_name(client, "Aravalli")
    d = client.get(f"/api/ipos/{iid}").json()
    assert d["company_name"].startswith("Aravalli") and d["documents"] and d["can_edit"] is False
    f = client.get(f"/api/ipos/{iid}/financials").json()
    assert len(f["statements"]) == 3 and f["unit"] == "crore"
    s = client.get(f"/api/ipos/{iid}/scores").json()
    assert s["status"] == "complete" and s["config_version"] == "1.0.0" and s["coverage"] == 0.0
    assert any("SYNTHETIC" in w for w in s["warnings"])
    src = client.get(f"/api/ipos/{iid}/sources").json()["sources"]
    assert src and src[0]["data_status"] == "synthetic"
    a = client.post(f"/api/ipos/{iid}/analyze").json()
    assert a["score_record_id"] and a["result"]["composite"] == s["composite"]
    hist = client.get(f"/api/ipos/{iid}/scores/history").json()
    assert len(hist) == 1  # identical inputs are not stored twice
    assert client.get("/api/ipos/9999").status_code == 404


def test_incomplete_analysis_is_explicit(client, seeded):
    iid = ipo_id_by_name(client, "Konkan")
    s = client.get(f"/api/ipos/{iid}/scores").json()
    assert s["status"] == "incomplete" and s["composite"] is None
    assert {m["component"] for m in s["missing_components"]} == {"quality", "valuation", "risk"}


def test_compare_and_scenario(client, seeded):
    a, b = ipo_id_by_name(client, "Aravalli"), ipo_id_by_name(client, "Kaveri")
    c = client.post("/api/ipos/compare", json={"ipo_ids": [a, b]}).json()
    assert len(c["items"]) == 2
    assert client.post("/api/ipos/compare", json={"ipo_ids": [a]}).status_code == 422
    assert client.post("/api/ipos/compare", json={"ipo_ids": [a, a]}).status_code == 422
    sc = client.post(f"/api/ipos/{a}/scenario", json={"overrides": {"bull": {"multiple": 40}}}).json()
    assert sc["status"] == "ok" and {s["name"] for s in sc["scenarios"]} == {"bear", "base", "bull"}
    assert client.post(f"/api/ipos/{a}/scenario", json={"overrides": {"bull": {"multiple": -1}}}).status_code == 422


def test_prediction_unavailable_without_real_data(client, seeded):
    iid = ipo_id_by_name(client, "Godavari")
    p = client.get(f"/api/ipos/{iid}/prediction").json()
    assert p["available"] is False and "0 real listed IPOs" in p["reason"]


def test_auth_register_login_logout(client, db):
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "short", "display_name": "A"}).status_code == 422
    csrf = register(client, "a@example.com", "correct-horse-9")
    assert client.get("/api/auth/me").json()["user"]["email"] == "a@example.com"
    assert client.post("/api/auth/register", json={"email": "A@example.com", "password": "correct-horse-9", "display_name": "A"}).status_code == 409
    assert client.post("/api/auth/logout").status_code == 403  # CSRF required
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/auth/me").json() is None
    assert client.get("/api/watchlist").status_code == 401
    bad = client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password-1"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    ok = client.post("/api/auth/login", json={"email": "a@example.com", "password": "correct-horse-9"})
    assert ok.status_code == 200 and "kcp_session" in ok.cookies
    from app.models import User
    u = db.query(User).filter_by(email="a@example.com").one()
    assert u.password_hash.startswith("$argon2id$") and "correct-horse-9" not in u.password_hash


def test_login_rate_limit(client, db):
    register(client, "b@example.com", "correct-horse-9")
    codes = [client.post("/api/auth/login", json={"email": "b@example.com", "password": "nope-nope-1"}).status_code for _ in range(10)]
    assert 429 in codes and codes[0] == 401


def test_authorization_boundaries(client, seeded):
    iid = ipo_id_by_name(client, "Aravalli")
    csrf = register(client, "owner@example.com")
    rep = client.post("/api/reports/generate", json={"ipo_id": iid, "use_ai": False}, headers={"X-CSRF-Token": csrf}).json()
    chat = client.post("/api/agent/chat", json={"message": "Explain the score", "ipo_id": iid}, headers={"X-CSRF-Token": csrf}).json()
    assert chat["saved"] and chat["conversation_id"]
    assert client.post(f"/api/ipos/{iid}/watch", headers={"X-CSRF-Token": csrf}).status_code == 201
    # demo IPOs can only be edited by administrators
    assert client.patch(f"/api/ipos/{iid}", json={"research_notes": "x"}, headers={"X-CSRF-Token": csrf}).status_code == 403
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    csrf2 = register(client, "intruder@example.com")
    assert client.get(f"/api/reports/{rep['id']}").status_code == 404
    assert client.delete(f"/api/reports/{rep['id']}", headers={"X-CSRF-Token": csrf2}).status_code == 404
    assert client.get(f"/api/agent/conversations/{chat['conversation_id']}").status_code == 404
    r = client.post("/api/agent/chat", json={"message": "continue", "conversation_id": chat["conversation_id"]}, headers={"X-CSRF-Token": csrf2})
    assert r.status_code == 404
    assert client.get("/api/reports").json()["total"] == 0
    assert client.get("/api/watchlist").json() == []
    assert client.post("/api/models/train", json={"synthetic": True}, headers={"X-CSRF-Token": csrf2}).status_code == 403
    assert client.post("/api/sources/fetch", json={"url": "https://www.sebi.gov.in/x.pdf", "title": "x"}, headers={"X-CSRF-Token": csrf2}).status_code == 403


def test_cross_origin_post_rejected(client, db):
    r = client.post("/api/auth/login", json={"email": "x@example.com", "password": "whatever-1"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_rejected"


def test_security_headers_and_error_shape(client, db):
    r = client.get("/api/ipos/abc")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    h = client.get("/api/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"


def test_watchlist_and_reports_flow(client, seeded):
    csrf = register(client)
    iid = ipo_id_by_name(client, "Nilgiri")
    client.post(f"/api/ipos/{iid}/watch", headers={"X-CSRF-Token": csrf})
    wl = client.get("/api/watchlist").json()
    assert [w["id"] for w in wl] == [iid] and wl[0]["scores"]["config_version"] == "1.0.0"
    assert client.get(f"/api/ipos/{iid}").json()["watchlisted"] is True
    client.delete(f"/api/ipos/{iid}/watch", headers={"X-CSRF-Token": csrf})
    assert client.get("/api/watchlist").json() == []
    rep = client.post("/api/reports/generate", json={"ipo_id": iid, "use_ai": False}, headers={"X-CSRF-Token": csrf}).json()
    assert rep["generator"] == "deterministic" and len(rep["sections"]) == 12
    keys = [s["key"] for s in rep["sections"]]
    assert keys == ["executive_summary", "overview", "financial_facts", "quality", "valuation", "risk", "scenarios", "peers",
                    "missing", "sources", "methodology", "limitations"]
    assert all(len(s["evidence"]) == len(set(s["evidence"])) for s in rep["sections"])  # no duplicate citations
    cited = {e for s in rep["sections"] for e in s["evidence"]}
    assert cited <= {c["id"] for c in rep["citations"]}  # every section reference resolves
    full = client.get(f"/api/reports/{rep['id']}").json()
    assert full["title"] == rep["title"]
    dash = client.get("/api/dashboard/summary").json()
    assert dash["recent_reports"][0]["id"] == rep["id"]
