"""Structured research reports built from engine outputs and stored evidence.

The report is assembled deterministically. When a local model is healthy it may add
short narrative paragraphs, which are accepted only if every number they contain
appears in the facts given to the model; otherwise the deterministic text is kept and
the reason is recorded. Every section lists the evidence it relies on.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.prompts import REPORT_SCHEMA, SYSTEM_REPORT
from app.agents.validation import compact_json, numbers_in_data, unsupported_numbers
from app.models import IPOIssue, ResearchReport, utcnow
from app.services.ipo_service import (
    build_scoring_inputs,
    current_statements,
    get_active_config,
    score_ipo,
    serialize_ipo_detail,
    serialize_statements,
)
from app.services.llm_provider import ProviderError, select_provider
from app.services.scenario import run_scenarios

DISCLAIMER = (
    "Educational research only — not investment advice, not a recommendation to subscribe, buy or sell, and not a "
    "forecast. Scores are rule-based summaries of stored inputs; the research score is not a probability of listing "
    "gains. Verify all facts against the offer document before relying on them."
)


def _fmt(v: Any, unit: str = "", nd: int = 2) -> str:
    if v is None:
        return "unavailable"
    if isinstance(v, (int, float)):
        s = f"{v:,.{nd}f}"
        return f"{s}{unit}"
    return str(v)


def _sec(key: str, title: str, paragraphs: list[str], facts: list[dict[str, Any]] | None = None, refs: list[str] | None = None) -> dict[str, Any]:
    # several stored values can share one source record: list each citation once, in order
    return {"key": key, "title": title, "paragraphs": paragraphs, "facts": facts or [], "evidence": list(dict.fromkeys(refs or []))}


def build_report(db: Session, ipo: IPOIssue, *, use_llm: bool = True) -> dict[str, Any]:
    d = serialize_ipo_detail(ipo)
    r = score_ipo(db, ipo)
    stmts = current_statements(db, ipo.company_id)
    fin = serialize_statements(stmts)
    scen = run_scenarios(build_scoring_inputs(db, ipo), get_active_config(db))
    q, v, k, e = r["quality"], r["valuation"], r["risk"], r["evidence"]
    synthetic = ipo.data_status == "synthetic" or ipo.data_mode == "demo"

    # --- citations ------------------------------------------------------------------
    citations: list[dict[str, Any]] = []
    cite_ids: dict[tuple, str] = {}

    def cite(kind: str, ref: Any, label: str, url: str | None = None, status: str | None = None) -> str:
        key = (kind, str(ref))
        if key not in cite_ids:
            cid = f"S{len(citations) + 1}"
            cite_ids[key] = cid
            citations.append({"id": cid, "kind": kind, "ref_id": ref, "label": label, "url": url, "data_status": status})
        return cite_ids[key]

    src_issue = cite("source_record", ipo.source_record_id, f"{ipo.company.name} issue details",
                     ipo.source_record.source_url if ipo.source_record else None, ipo.data_status)
    fin_refs = [cite("source_record", s.source_record_id, f"Financial statements {s.period_label}",
                     s.source_record.source_url if s.source_record else None, s.data_status) for s in stmts if s.source_record_id]
    calc = cite("calculation", f"scores:{ipo.id}:{r['input_fingerprint'][:12]}",
                f"Scoring engine output (config {r['config_version']}, inputs {r['input_fingerprint'][:12]})")
    peer_refs = sorted({cite("source_record", p["source_record_id"], f"Peer snapshot {p['name']}", None, p["data_status"])
                        for p in v.get("peers", []) if p.get("source_record_id")})
    disc_refs = [cite("source_record", x.source_record_id, f"Disclosure: {x.title}",
                      x.source_record.source_url if x.source_record else None, x.data_status) for x in ipo.disclosures if x.source_record_id]
    scen_ref = cite("calculation", f"scenario:{ipo.id}", "Scenario engine output")

    latest = fin[-1] if fin else None
    sections: list[dict[str, Any]] = []

    # 1 Executive summary (deterministic)
    if r["status"] == "complete":
        exec_txt = (f"{ipo.company.name} has a composite educational research score of {_fmt(r['composite'])} / 100 "
                    f"(quality {_fmt(q['score'])}, relative valuation {_fmt(v['score'])}, risk {_fmt(k['score'])}, {k['level']}). "
                    f"Evidence coverage is {_fmt(e['coverage'])}%.")
    else:
        exec_txt = (f"A composite research score is not available for {ipo.company.name}: "
                    + "; ".join(f"{m['component']} — {m['reason']}" for m in r["missing_components"]) + ".")
    if synthetic:
        exec_txt += " All figures are SYNTHETIC demonstration data about a fictional company."
    sections.append(_sec("executive_summary", "Executive summary", [exec_txt], refs=[calc]))

    # 2 Company & issue overview
    sections.append(_sec("overview", "Company and issue overview", [
        d.get("description") or "Business description unavailable.",
        f"Business model: {d.get('business_model') or 'unavailable'}",
    ], [
        {"label": "Sector", "value": d["sector"]}, {"label": "Exchange", "value": d["exchange"]},
        {"label": "Issue type", "value": d["issue_type"]}, {"label": "Status", "value": d["status"]},
        {"label": "Price band (₹)", "value": f"{_fmt(d['price_band_low'])} – {_fmt(d['price_band_high'])}"},
        {"label": "Issue size (₹ cr)", "value": _fmt(d["issue_size_cr"])},
        {"label": "Fresh issue / OFS (₹ cr)", "value": f"{_fmt(d['fresh_issue_cr'])} / {_fmt(d['ofs_cr'])}"},
        {"label": "Post-issue promoter holding", "value": _fmt(d["promoter_holding_post_pct"], "%")},
        {"label": "Dilution from fresh issue", "value": _fmt(d["dilution_pct"], "%")},
    ], [src_issue]))

    # 3 Verified financial facts
    fin_facts = []
    if latest:
        for lbl, key in (("Revenue", "revenue"), ("EBITDA", "ebitda"), ("PAT", "pat"), ("Operating cash flow", "operating_cash_flow"),
                         ("Total debt", "total_debt"), ("Total equity", "total_equity")):
            fin_facts.append({"label": f"{lbl} {latest['period_label']} (₹ cr)", "value": _fmt(latest[key]), "status": latest["data_status"]})
    sections.append(_sec("financial_facts", "Financial facts", [
        f"{len(fin)} reporting period(s) stored ({', '.join(x['period_label'] for x in fin) or 'none'}). Values in INR crore, "
        f"status: {', '.join(sorted({x['data_status'] for x in fin})) or 'n/a'}."
    ], fin_facts, fin_refs))

    # 4 Quality
    q_paras = [f"Quality score Q = {_fmt(q['score'])} ({q['status']}). {q['formula']}."]
    for n, c in q["components"].items():
        q_paras.append(f"{n.replace('_', ' ').title()}: {_fmt(c['score'])}" + (f" — {c['reason']}" if c["reason"] else ""))
    sections.append(_sec("quality", "Fundamental quality assessment", q_paras, refs=[calc, *fin_refs]))

    # 5 Valuation
    if v["status"] == "ok":
        v_paras = [f"Valued on {v['multiple_label']}: IPO multiple {_fmt(v['ipo_multiple'])}x at {v['price_basis']} (₹{_fmt(v['price_used'])}), "
                   f"market cap ₹{_fmt(v['market_cap_cr'])} cr. Peer range p{v['low_percentile']}–p{v['high_percentile']}: "
                   f"{_fmt(v['peer_low'])}x – {_fmt(v['peer_high'])}x, median {_fmt(v['peer_median'])}x "
                   f"(premium {_fmt(v['premium_to_median_pct'], '%')}). V = {_fmt(v['score'])}.",
                   "This is relative valuation against listed peers, not an estimate of intrinsic value."]
    else:
        v_paras = [f"Valuation score unavailable: {v.get('reason')}."]
    v_paras += v.get("flags", [])
    sections.append(_sec("valuation", "Valuation analysis", v_paras, refs=[calc, *peer_refs]))

    # 6 Risk
    k_paras = [f"Risk score R = {_fmt(k['score'])} ({k['level'] or k['status']}); higher means riskier."]
    for n, c in k["components"].items():
        k_paras.append(f"{n.replace('_', ' ').title()}: {_fmt(c['score'])}" + (f" — {c['reason']}" if c.get("reason") else ""))
    for x in ipo.disclosures:
        k_paras.append(f"[{x.status.replace('_', ' ')}] {x.title} ({x.severity})")
    if not ipo.risk_disclosures_reviewed and not ipo.disclosures:
        k_paras.append("Risk disclosures have not been reviewed. Absence of recorded issues is not evidence of their absence.")
    sections.append(_sec("risk", "Risk analysis", k_paras, refs=[calc, *disc_refs]))

    # 7 Scenarios
    s_paras = [scen["note"]]
    s_facts = []
    for s in scen.get("scenarios", []):
        if s["status"] == "ok":
            s_facts.append({"label": s["name"].title(), "value": f"₹{_fmt(s['implied_price'])} ({_fmt(s['implied_return_pct'], '%')})",
                            "assumptions": s["assumptions"]})
        else:
            s_facts.append({"label": s["name"].title(), "value": "unavailable", "reasons": s.get("reasons")})
    if scen.get("status") != "ok":
        s_paras.append("Scenario analysis unavailable: " + "; ".join(scen.get("reasons", [])))
    sections.append(_sec("scenarios", "Scenario analysis (hypothetical)", s_paras, s_facts, [scen_ref]))

    # 8 Peers
    sections.append(_sec("peers", "Peer comparison", [v.get("peer_selection") or "No usable peer set."],
                         [{"label": p["name"], "value": f"{_fmt(p['value'])}x" if p["value"] else "n/a",
                           "status": p["data_status"], "used": p["used"], "excluded_reason": p["excluded_reason"]} for p in v.get("peers", [])],
                         peer_refs))

    # 9 Missing / stale
    miss = [f"{m['component']}.{m['metric']}: {m['reason']}" for m in r["unavailable_metrics"]]
    miss += [f"Evidence input '{i['key']}' earns no credit (status {i['status']})" for i in e["items"] if i["credit"] == 0]
    if e["financials_stale"]:
        miss.insert(0, "Latest financial period is stale.")
    sections.append(_sec("missing", "Missing or stale information", miss or ["No missing inputs detected."], refs=[calc]))

    # 10 Sources
    sections.append(_sec("sources", "Source references", [f"{c['id']}: {c['label']}" + (f" — {c['url']}" if c["url"] else "") +
                                                          (f" [{c['data_status']}]" if c["data_status"] else "") for c in citations]))
    # 11 Methodology
    sections.append(_sec("methodology", "Scoring methodology", [
        f"Configuration version {r['config_version']}. {r['composite_formula']}. {q['formula']}. {v['formula']}. {k['formula']}.",
        e["formula"] + ". " + e["note"],
        "Weights and thresholds are educational defaults, not statistically validated coefficients.",
    ], refs=[calc]))
    # 12 Limitations
    sections.append(_sec("limitations", "Limitations and disclaimer", [DISCLAIMER, *r["warnings"]]))

    generator = "deterministic"
    llm_status: dict[str, Any] = {"used": False}
    if use_llm:
        sel = select_provider()
        if sel.provider is None:
            llm_status = {"used": False, "reason": sel.reason}
        else:
            facts = {
                "company": ipo.company.name, "synthetic": synthetic, "status": r["status"], "composite": r["composite"],
                "quality": {n: c["score"] for n, c in q["components"].items()} | {"Q": q["score"]},
                "valuation": {kk: v.get(kk) for kk in ("score", "multiple_label", "ipo_multiple", "peer_median", "premium_to_median_pct", "reason")},
                "risk": {n: c["score"] for n, c in k["components"].items()} | {"R": k["score"], "level": k["level"]},
                "coverage": e["coverage"], "missing": r["missing_components"], "latest_financials": latest,
            }
            try:
                out = sel.provider.chat_json(SYSTEM_REPORT, [{"role": "user", "content": "FACTS:\n" + compact_json(facts, 12000)}], REPORT_SCHEMA)
                allowed = numbers_in_data(facts)
                bad = {key: unsupported_numbers(str(out.get(key, "")), allowed) for key in REPORT_SCHEMA["required"]}
                if any(bad.values()) or not all(isinstance(out.get(x), str) and out.get(x) for x in REPORT_SCHEMA["required"]):
                    llm_status = {"used": False, "reason": "model narrative rejected: unsupported numbers or missing fields",
                                  "unsupported_numbers": {kk: vv for kk, vv in bad.items() if vv}}
                else:
                    by_key = {s["key"]: s for s in sections}
                    by_key["executive_summary"]["narrative"] = out["executive_summary"]
                    by_key["quality"]["narrative"] = out["quality_interpretation"]
                    by_key["valuation"]["narrative"] = out["valuation_interpretation"]
                    by_key["risk"]["narrative"] = out["risk_interpretation"]
                    generator = f"{sel.mode}:{getattr(sel.provider, 'model', '')}"
                    llm_status = {"used": True, "model": getattr(sel.provider, "model", None),
                                  "note": "Narrative paragraphs are model-written from engine facts and number-checked."}
            except ProviderError as exc:
                llm_status = {"used": False, "reason": f"model unavailable: {exc}"}

    return {
        "title": f"{ipo.company.name} — IPO research report",
        "ipo_id": ipo.id,
        "company_name": ipo.company.name,
        "generated_at": utcnow().isoformat(),
        "generator": generator,
        "llm": llm_status,
        "config_version": r["config_version"],
        "scores": {"status": r["status"], "composite": r["composite"], "quality": q["score"], "valuation": v["score"],
                   "risk": k["score"], "risk_level": k["level"], "coverage": e["coverage"]},
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
