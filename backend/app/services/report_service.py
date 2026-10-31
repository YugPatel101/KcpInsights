"""Structured research reports assembled deterministically from engine outputs and stored evidence.

Every sentence is templated from computed values; every section lists the sources it relies on.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import IPOIssue, ResearchReport, utcnow
from app.services.ipo_service import current_statements, score_ipo, serialize_ipo_detail
from app.services.quant_engine import COMPONENT_LABELS, DISCLAIMER


def _fmt(v: Any, unit: str = "", nd: int = 2) -> str:
    if v is None:
        return "unavailable"
    if isinstance(v, (int, float)):
        return f"{v:,.{nd}f}{unit}"
    return str(v)


def _sec(key: str, title: str, paragraphs: list[str], facts: list[dict[str, Any]] | None = None, refs: list[str] | None = None) -> dict[str, Any]:
    return {"key": key, "title": title, "paragraphs": paragraphs, "facts": facts or [], "evidence": list(dict.fromkeys(refs or []))}


def _metric_facts(r: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for k in keys:
        m = r["metrics"].get(k)
        if m is None:
            continue
        unit = {"%": "%", "x": "x", "pp": " pp", "₹ cr": " ₹ cr", "₹": " ₹", "score": ""}.get(m["unit"], "")
        val = _fmt(m["value"], unit) if m["status"] == "ok" else (m.get("note") or m.get("reason") or "unavailable")
        if m["status"] == "ok" and m["value"] is None and m.get("note"):
            val = m["note"]
        out.append({"label": m["label"], "value": val, "status": m["status"], "formula": m["formula"], "period": m.get("period")})
    return out


def build_report(db: Session, ipo: IPOIssue) -> dict[str, Any]:
    d = serialize_ipo_detail(ipo)
    r = score_ipo(db, ipo)
    synthetic = ipo.data_status == "synthetic" or ipo.data_mode == "demo"
    stmts = [s for s in current_statements(db, ipo.company_id) if s.basis == r["basis"] and s.period_months == 12]

    citations: list[dict[str, Any]] = []
    cite_ids: dict[tuple[str, str], str] = {}

    def cite(kind: str, ref: Any, label: str, url: str | None = None, status: str | None = None) -> str:
        key = (kind, str(ref))
        if key not in cite_ids:
            cite_ids[key] = f"S{len(cite_ids) + 1}"
            citations.append({"id": cite_ids[key], "kind": kind, "label": label, "url": url, "data_status": status})
        return cite_ids[key]

    issue_ref = cite("issue", ipo.id, (d.get("source") or {}).get("title") or "Stored issue record", (d.get("source") or {}).get("url"), ipo.data_status)
    fin_refs = [cite("statement", s.id, f"{s.period_label} financial statements ({s.basis})", (s.source_record.source_url if s.source_record else None), s.data_status)
                for s in stmts]
    calc = cite("engine", r["config_version"], f"KcpInsights quantitative engine (configuration v{r['config_version']})")

    f, rk = r["fundamental"], r["risk"]
    sections: list[dict[str, Any]] = []
    head = (f"Fundamental score {_fmt(f['score'], '', 1)} / 100 — {f['classification']}." if f["score"] is not None
            else f"No overall fundamental score: {f['reason']}.")
    sections.append(_sec("executive_summary", "Executive summary", [
        f"{d['company_name']} — {d['issue_type'].upper()} issue on {d['exchange']}, status {d['status']}.",
        head,
        f"Risk score {_fmt(rk['score'], '', 1)} / 100 ({rk['level'] or 'unavailable'}); data coverage {_fmt(r['coverage'], '%', 0)}; "
        f"financial basis: {r['basis'] or 'none'}; latest annual period: {r['latest_period'] or 'none'}.",
        *(["This report uses SYNTHETIC demonstration data about a fictional company."] if synthetic else []),
    ], refs=[issue_ref, calc]))
    sections.append(_sec("issue", "Issue details", [
        f"Price band ₹{_fmt(d['price_band_low'])}–₹{_fmt(d['price_band_high'])}; final price {_fmt(d['final_issue_price'])}; lot {d['lot_size'] or 'unavailable'}; "
        f"issue size ₹{_fmt(d['issue_size_cr'])} cr (fresh ₹{_fmt(d['fresh_issue_cr'])} cr, offer for sale ₹{_fmt(d['ofs_cr'])} cr).",
        "Key dates: " + "; ".join(f"{k['label']} {k['date'] or 'unavailable'}" for k in d.get("key_dates", [])) + ".",
    ], refs=[issue_ref]))
    fin_facts = [{"label": f"{s.period_label} revenue / PAT", "value": f"₹{_fmt(s.revenue)} cr / ₹{_fmt(s.pat)} cr", "status": s.data_status}
                 for s in stmts]
    sections.append(_sec("financials", "Restated financial statements", [
        f"{len(stmts)} annual period(s) on the {r['basis'] or 'n/a'} basis are used; interim periods are not annualised."
        if stmts else "No usable annual financial statements are stored."], fin_facts, fin_refs))
    for key, keys in (("profitability", ("roe", "roce", "net_margin", "ebitda_margin", "operating_margin")),
                      ("growth", ("revenue_cagr", "pat_cagr", "revenue_yoy", "pat_yoy", "ebitda_growth", "eps_growth", "growth_consistency")),
                      ("financial_health", ("current_ratio", "quick_ratio", "cash_ratio", "debt_to_equity", "interest_coverage", "debt_to_ebitda")),
                      ("cash_flow", ("ocf_to_pat", "fcf", "fcf_margin", "cash_conversion", "cash_flow_consistency")),
                      ("valuation", ("market_cap", "eps_post_issue", "pe", "bvps_post_issue", "pb", "enterprise_value", "ev_ebitda"))):
        c = r["components"][key]
        para = (f"{COMPONENT_LABELS[key]} score {_fmt(c['score'], '', 1)} / 100 (coverage {_fmt(c['coverage'], '%', 0)})."
                if c["score"] is not None else f"{COMPONENT_LABELS[key]} score unavailable: {c['reason']}.")
        extra = []
        if key == "valuation":
            p = r["price"]
            extra.append(f"Price used: ₹{_fmt(p.get('price'))} ({p.get('price_basis') or 'not published'}).")
            pe = r["peers"] or {}
            extra.append(f"Listed peers with a P/E: {pe.get('with_pe', 0)}; median P/E {_fmt(pe.get('median_pe'))}." if pe.get("median_pe")
                         else (pe.get("note") or "No listed-peer data."))
        sections.append(_sec(key, COMPONENT_LABELS[key], [para, *extra], _metric_facts(r, keys), [calc, *fin_refs]))
    sections.append(_sec("risk", "Risk assessment", [
        f"Risk score {_fmt(rk['score'], '', 1)} / 100 ({rk['level'] or 'unavailable'}). {rk['formula']}."],
        [{"label": c["label"], "value": _fmt(c["points"], " pts", 0) if c["available"] else "not available", "status": c["kind"],
          "formula": c.get("detail") or ""} for c in rk["components"]], [calc, issue_ref]))
    sections.append(_sec("score", "Score breakdown", [f["formula"] + ".", *( [f["note"]] if f.get("note") else [])],
                         [{"label": c["label"], "value": _fmt(c["score"], "", 1), "status": "computed" if c["score"] is not None else "unavailable",
                           "formula": f"weight {f['weights'][k]:.2f}"} for k, c in r["components"].items()], [calc]))
    sections.append(_sec("missing", "Missing or unreliable information", r["missing"][:30] or ["No missing inputs detected."], refs=[calc]))
    sections.append(_sec("limitations", "Limitations and disclaimer", [DISCLAIMER, *r["warnings"]]))
    return {
        "title": f"{ipo.company.name} — IPO research report",
        "ipo_id": ipo.id,
        "company_name": ipo.company.name,
        "generated_at": utcnow().isoformat(),
        "generator": "deterministic",
        "config_version": r["config_version"],
        "scores": {"status": r["status"], "composite": r["composite"], "classification": r["classification"],
                   **{k: c["score"] for k, c in r["components"].items()}, "risk": rk["score"], "risk_level": rk["level"], "coverage": r["coverage"]},
        "synthetic": synthetic,
        "sections": sections,
        "citations": citations,
        "disclaimer": DISCLAIMER,
    }


def save_report(db: Session, user_id: int, ipo: IPOIssue, report: dict[str, Any]) -> ResearchReport:
    row = ResearchReport(user_id=user_id, ipo_id=ipo.id, title=report["title"], generator=report["generator"],
                         config_version=report["config_version"], content=report)
    db.add(row)
    db.commit()
    return row
