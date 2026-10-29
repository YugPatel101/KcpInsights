"""Validated, read-mostly application tools exposed to the research agent.

Each tool has a Pydantic argument schema, typed output, error handling and (where
relevant) permission checks. Tools return *evidence* entries that point at stored
records or reproducible calculations, so every claim can be traced.

The agent cannot reach the filesystem, shell, network or raw SQL: only these tools.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.models import IPOIssue, User
from app.services import rag
from app.services.financial_metrics import compute_quality_metrics
from app.services.ipo_service import (
    all_ipos,
    build_scoring_inputs,
    current_statements,
    get_active_config,
    get_ipo,
    issue_price,
    listing_return_pct,
    score_ipo,
    score_summary,
    serialize_ipo_detail,
    serialize_ipo_summary,
    serialize_statements,
    to_period,
)
from app.services.scenario import run_scenarios


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    db: Session
    user: User | None
    conversation_id: int | None = None


@dataclass
class Evidence:
    kind: str  # source_record | calculation | document_chunk | ipo_record
    label: str
    ref_id: int | str | None = None
    url: str | None = None
    data_status: str | None = None
    page: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.kind, str(self.ref_id), self.label)


@dataclass
class ToolResult:
    data: dict[str, Any]
    evidence: list[Evidence]
    summary: str


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IpoArg(_Args):
    ipo_id: int = Field(ge=1, description="IPO id")


class PeerArgs(IpoArg):
    compare_with_ipo_ids: list[int] = Field(default_factory=list, max_length=3, description="other IPO ids to compare side by side")


class SearchArgs(_Args):
    query: str = Field(min_length=2, max_length=300)
    ipo_id: int | None = Field(default=None, ge=1)
    k: int = Field(default=4, ge=1, le=8)


class ComparableArgs(IpoArg):
    limit: int = Field(default=6, ge=1, le=20)


class ScenarioArgs(IpoArg):
    overrides: dict[str, dict[str, float | str]] = Field(default_factory=dict)


class ReportArgs(IpoArg):
    save: bool = True


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[_Args]
    handler: Callable[[ToolContext, Any], ToolResult]
    writes: bool = False

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.args_model.model_json_schema()}


def _ipo(ctx: ToolContext, ipo_id: int) -> IPOIssue:
    ipo = get_ipo(ctx.db, ipo_id)
    if ipo is None:
        raise ToolError(f"IPO {ipo_id} not found")
    return ipo


def _issue_ev(ipo: IPOIssue) -> Evidence:
    rec = ipo.source_record
    return Evidence("source_record", f"{ipo.company.name}: issue details", rec.id if rec else None,
                    rec.source_url if rec else None, ipo.data_status)


def _calc_ev(ipo: IPOIssue, label: str, detail: dict[str, Any]) -> Evidence:
    return Evidence("calculation", f"{ipo.company.name}: {label}", f"ipo:{ipo.id}:{label}", None, None, None, detail)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def get_ipo_profile(ctx: ToolContext, a: IpoArg) -> ToolResult:
    ipo = _ipo(ctx, a.ipo_id)
    d = serialize_ipo_detail(ipo)
    keep = ("id", "company_name", "sector", "industry", "exchange", "issue_type", "status", "open_date", "close_date", "listing_date",
            "price_band_low", "price_band_high", "final_issue_price", "lot_size", "min_investment_inr", "issue_size_cr", "fresh_issue_cr",
            "ofs_cr", "post_issue_shares", "dilution_pct", "promoter_holding_pre_pct", "promoter_holding_post_pct", "use_of_proceeds",
            "business_model", "description", "revenue_sources", "subscription", "listing_price", "listing_return_pct", "data_mode", "data_status")
    data = {k: d.get(k) for k in keep}
    return ToolResult(data, [_issue_ev(ipo)], f"Profile of {ipo.company.name} ({data['status']}, {data['data_status']})")


def get_financial_statements(ctx: ToolContext, a: IpoArg) -> ToolResult:
    ipo = _ipo(ctx, a.ipo_id)
    stmts = current_statements(ctx.db, ipo.company_id)
    rows = serialize_statements(stmts)
    ev = [Evidence("source_record", f"{ipo.company.name}: financials {s.period_label}", s.source_record_id,
                   s.source_record.source_url if s.source_record else None, s.data_status) for s in stmts]
    return ToolResult({"unit": "INR crore", "statements": rows}, ev, f"{len(rows)} financial period(s) for {ipo.company.name}")


def calculate_financial_metrics(ctx: ToolContext, a: IpoArg) -> ToolResult:
    ipo = _ipo(ctx, a.ipo_id)
    stmts = current_statements(ctx.db, ipo.company_id)
    metrics = {k: m.to_dict() for k, m in compute_quality_metrics([to_period(s) for s in stmts]).items()}
    ok = [k for k, m in metrics.items() if m["status"] == "ok"]
    return ToolResult({"metrics": metrics}, [_calc_ev(ipo, "financial metrics", {"computed": ok})],
                      f"{len(ok)}/{len(metrics)} metrics computable")


def _scores(ctx: ToolContext, ipo_id: int) -> tuple[IPOIssue, dict[str, Any]]:
    ipo = _ipo(ctx, ipo_id)
    return ipo, score_ipo(ctx.db, ipo)


def calculate_quality_score(ctx: ToolContext, a: IpoArg) -> ToolResult:
    ipo, r = _scores(ctx, a.ipo_id)
    q = r["quality"]
    comps = {n: {"score": c["score"], "status": c["status"], "weight": c["weight"], "reason": c["reason"],
                 "metrics": {i["key"]: {"value": i["metric"]["value"], "unit": i["metric"]["unit"], "score": i["score"],
                                        "status": i["metric"]["status"], "reason": i["metric"]["reason"]} for i in c["items"]}}
             for n, c in q["components"].items()}
    data = {"quality": q["score"], "status": q["status"], "formula": q["formula"], "components": comps,
            "periods": q["annual_periods_used"], "config_version": r["config_version"]}
    return ToolResult(data, [_calc_ev(ipo, "quality score", {"score": q["score"], "config": r["config_version"]})],
                      f"Quality {q['score']} ({q['status']})")


def calculate_valuation_score(ctx: ToolContext, a: IpoArg) -> ToolResult:
    ipo, r = _scores(ctx, a.ipo_id)
    v = r["valuation"]
    ev = [_calc_ev(ipo, "valuation score", {"score": v["score"], "multiple": v.get("multiple")})]
    for p in v.get("peers", []):
        if p["source_record_id"]:
            ev.append(Evidence("source_record", f"peer {p['name']} ({p['as_of']})", p["source_record_id"], None, p["data_status"]))
    keep = {k: v.get(k) for k in ("score", "status", "reason", "formula", "kind", "multiple_label", "ipo_multiple", "price_used", "price_basis",
                                   "market_cap_cr", "peer_low", "peer_median", "peer_high", "low_percentile", "high_percentile",
                                   "premium_to_median_pct", "flags", "attempts", "peer_selection", "calculation_inputs")}
    keep["peers"] = [{k: p[k] for k in ("name", "value", "as_of", "used", "excluded_reason", "data_status")} for p in v.get("peers", [])]
    return ToolResult(keep, ev, f"Valuation {v['score']} ({v['status']})")


def calculate_risk_score(ctx: ToolContext, a: IpoArg) -> ToolResult:
    ipo, r = _scores(ctx, a.ipo_id)
    k = r["risk"]
    comps = {n: {"score": c["score"], "status": c["status"], "weight": c["weight"],
                 "items": [{kk: i.get(kk) for kk in ("key", "score", "weight", "evidence", "value", "triggered")} for i in c["items"]]}
             for n, c in k["components"].items()}
    ev = [_calc_ev(ipo, "risk score", {"score": k["score"], "level": k["level"]})]
    for d in ipo.disclosures:
        if d.source_record_id:
            ev.append(Evidence("source_record", f"disclosure: {d.title}", d.source_record_id, None, d.data_status))
    return ToolResult({"risk": k["score"], "level": k["level"], "status": k["status"], "formula": k["formula"], "components": comps},
                      ev, f"Risk {k['score']} ({k['level']})")


def compare_ipo_peers(ctx: ToolContext, a: PeerArgs) -> ToolResult:
    ipo, r = _scores(ctx, a.ipo_id)
    v = r["valuation"]
    data: dict[str, Any] = {
        "ipo": {"company_name": ipo.company.name, "multiple": v.get("multiple_label"), "ipo_multiple": v.get("ipo_multiple"),
                "peer_median": v.get("peer_median"), "premium_to_median_pct": v.get("premium_to_median_pct")},
        "peers": [{"name": p.name, "ticker": p.ticker, "as_of": p.as_of.isoformat(), "pe": p.pe, "ev_ebitda": p.ev_ebitda, "pb": p.pb,
                   "ps": p.ps, "market_cap_cr": p.market_cap_cr, "data_status": p.data_status, "selection_reason": p.selection_reason}
                  for p in ipo.peers],
        "other_ipos": [],
    }
    ev = [_calc_ev(ipo, "peer comparison", {"multiple": v.get("multiple")})]
    ev += [Evidence("source_record", f"peer {p.name}", p.source_record_id, None, p.data_status) for p in ipo.peers if p.source_record_id]
    for oid in a.compare_with_ipo_ids:
        if oid == a.ipo_id:
            continue
        o, ro = _scores(ctx, oid)
        data["other_ipos"].append({"ipo_id": oid, "company_name": o.company.name, "scores": score_summary(ro),
                                   "valuation": {"multiple": ro["valuation"].get("multiple_label"), "ipo_multiple": ro["valuation"].get("ipo_multiple")}})
        ev.append(_calc_ev(o, "research scores", score_summary(ro)))
    data["ipo"]["scores"] = score_summary(r)
    return ToolResult(data, ev, f"{len(ipo.peers)} peers; {len(data['other_ipos'])} IPO(s) compared")


def get_official_disclosures(ctx: ToolContext, a: IpoArg) -> ToolResult:
    from sqlalchemy import select

    from app.models import SourceDocument

    ipo = _ipo(ctx, a.ipo_id)
    docs = list(ctx.db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id)).scalars())
    data = {
        "risk_disclosures_reviewed": ipo.risk_disclosures_reviewed,
        "disclosures": [{"id": d.id, "category": d.category, "severity": d.severity, "status": d.status, "title": d.title,
                         "description": d.description, "amount_cr": d.amount_cr, "data_status": d.data_status} for d in ipo.disclosures],
        "documents": [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "pages": d.page_count, "url": d.source_url,
                       "data_status": d.data_status, "retrieved_at": d.retrieved_at.isoformat()} for d in docs],
        "note": "Only disclosures stored in KcpInsights are listed; live exchange feeds are not queried by the agent.",
    }
    ev = [Evidence("source_record", f"disclosure: {d.title}", d.source_record_id, d.source_record.source_url if d.source_record else None, d.data_status)
          for d in ipo.disclosures]
    ev += [Evidence("ipo_record", f"document: {d.title}", f"doc:{d.id}", d.source_url, d.data_status) for d in docs]
    return ToolResult(data, ev, f"{len(ipo.disclosures)} disclosure(s), {len(docs)} document(s)")


def search_local_research_documents(ctx: ToolContext, a: SearchArgs) -> ToolResult:
    res = rag.search(ctx.db, a.query, ipo_id=a.ipo_id, k=a.k)
    ev = [Evidence("document_chunk", f"{r['document_title']} p.{r['page']}", r["chunk_id"], r["source_url"], r["data_status"], r["page"],
                   {"injection_suspected": r["injection_suspected"]}) for r in res["results"]]
    return ToolResult(res, ev, f"{len(res['results'])} passage(s) via {res['mode']} search" if res["results"] else "no evidence found")


def get_historical_comparable_ipos(ctx: ToolContext, a: ComparableArgs) -> ToolResult:
    target = _ipo(ctx, a.ipo_id)
    cutoff = target.open_date
    rows = []
    for o in all_ipos(ctx.db):
        if o.id == target.id or o.listing_price is None or o.listing_date is None:
            continue
        if cutoff and o.listing_date >= cutoff:
            continue  # no look-ahead: only listings before the target opened
        rows.append((o.company.sector == target.company.sector, o))
    rows.sort(key=lambda x: (not x[0], x[1].listing_date), reverse=False)
    items = []
    for same, o in rows[: a.limit]:
        items.append({"ipo_id": o.id, "company_name": o.company.name, "sector": o.company.sector, "same_sector": same,
                      "listing_date": str(o.listing_date), "issue_price": issue_price(o), "listing_price": o.listing_price,
                      "listing_return_pct": listing_return_pct(o), "data_status": o.listing_data_status or o.data_status, "data_mode": o.data_mode})
    ev = [Evidence("source_record", f"{o.company.name} listing outcome", o.source_record_id, None, o.listing_data_status or o.data_status) for _, o in rows[: a.limit]]
    return ToolResult({"items": items, "cutoff": cutoff.isoformat() if cutoff else None,
                       "note": "Historical listing outcomes do not predict future listings. Synthetic outcomes are fictional."},
                      ev, f"{len(items)} historical listing(s) before {cutoff}")


def run_scenario_analysis(ctx: ToolContext, a: ScenarioArgs) -> ToolResult:
    ipo = _ipo(ctx, a.ipo_id)
    inputs = build_scoring_inputs(ctx.db, ipo)
    res = run_scenarios(inputs, get_active_config(ctx.db), {k: dict(v) for k, v in a.overrides.items()})
    return ToolResult(res, [_calc_ev(ipo, "scenario analysis", {"status": res["status"]})], f"Scenarios: {res['status']}")


def get_data_provenance(ctx: ToolContext, a: IpoArg) -> ToolResult:
    from app.api.routes.ipos import collect_sources

    ipo, r = _scores(ctx, a.ipo_id)
    sources = collect_sources(ctx.db, ipo)
    data = {"sources": sources, "evidence_coverage": r["evidence"]["coverage"], "input_completeness": r["evidence"]["input_completeness"],
            "evidence_items": r["evidence"]["items"], "financials_stale": r["evidence"]["financials_stale"],
            "unavailable_metrics": r["unavailable_metrics"], "missing_components": r["missing_components"]}
    ev = [Evidence("source_record", s["title"], s["id"], s["url"], s["data_status"]) for s in sources]
    return ToolResult(data, ev, f"{len(sources)} source record(s); coverage {r['evidence']['coverage']}")


def generate_research_report(ctx: ToolContext, a: ReportArgs) -> ToolResult:
    from app.services.report_service import build_report, save_report

    ipo = _ipo(ctx, a.ipo_id)
    report = build_report(ctx.db, ipo)
    report_id = None
    if a.save:
        if ctx.user is None:
            report["save_note"] = "Sign in to save reports."
        else:
            report_id = save_report(ctx.db, ctx.user.id, ipo, report).id
    return ToolResult({"report_id": report_id, "title": report["title"], "generator": report["generator"],
                       "sections": [s["key"] for s in report["sections"]], "save_note": report.get("save_note")},
                      [_calc_ev(ipo, "research report", {"report_id": report_id})],
                      f"Report generated{' and saved' if report_id else ''}")


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("get_ipo_profile", "Issue structure, dates, price band, business description and status for one IPO.", IpoArg, get_ipo_profile),
        Tool("get_financial_statements", "Stored financial statements (INR crore) with provenance.", IpoArg, get_financial_statements),
        Tool("calculate_financial_metrics", "Deterministic ratios: margins, ROE, ROCE, CAGR, cash conversion, leverage.", IpoArg, calculate_financial_metrics),
        Tool("calculate_quality_score", "Fundamental quality score Q with component breakdown.", IpoArg, calculate_quality_score),
        Tool("calculate_valuation_score", "Relative valuation score V versus listed peers.", IpoArg, calculate_valuation_score),
        Tool("calculate_risk_score", "Risk score R with component breakdown and evidence.", IpoArg, calculate_risk_score),
        Tool("compare_ipo_peers", "Peer multiples table and optional side-by-side with other IPOs.", PeerArgs, compare_ipo_peers),
        Tool("get_official_disclosures", "Stored risk disclosures and offer documents for an IPO.", IpoArg, get_official_disclosures),
        Tool("search_local_research_documents", "Search ingested offer documents; returns cited passages or no evidence.", SearchArgs, search_local_research_documents),
        Tool("get_historical_comparable_ipos", "Listed IPOs before this issue opened, same sector first.", ComparableArgs, get_historical_comparable_ipos),
        Tool("run_scenario_analysis", "Bear/base/bull hypothetical valuation scenarios.", ScenarioArgs, run_scenario_analysis),
        Tool("get_data_provenance", "Source records, evidence coverage and missing inputs.", IpoArg, get_data_provenance),
        Tool("generate_research_report", "Generate (and for signed-in users save) a structured research report.", ReportArgs, generate_research_report, writes=True),
    ]
}


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    status: str  # ok | error | rejected
    summary: str
    duration_ms: int
    result: ToolResult | None = None


def execute_tool(ctx: ToolContext, name: str, raw_args: Any) -> ToolCallRecord:
    """Validate and run one tool call. Never raises; failures are returned as records."""
    t0 = time.perf_counter()
    tool = TOOLS.get(name)
    if tool is None:
        return ToolCallRecord(name, {}, "rejected", f"unknown tool {name!r}", 0)
    if not isinstance(raw_args, dict):
        return ToolCallRecord(name, {}, "rejected", "arguments must be an object", 0)
    try:
        args = tool.args_model.model_validate(raw_args)
    except ValidationError as exc:
        return ToolCallRecord(name, raw_args, "rejected", f"invalid arguments: {exc.errors()[0]['msg']}", 0)
    try:
        res = tool.handler(ctx, args)
        status, summary = "ok", res.summary
    except ToolError as exc:
        res, status, summary = None, "error", str(exc)
    except Exception as exc:  # noqa: BLE001 - tool failures must not crash the agent
        res, status, summary = None, "error", f"tool failed: {type(exc).__name__}"
    return ToolCallRecord(name, args.model_dump(), status, summary, int((time.perf_counter() - t0) * 1000), res)


def tool_catalog() -> list[dict[str, Any]]:
    return [t.schema() for t in TOOLS.values()]


def ipo_index(db: Session) -> list[dict[str, Any]]:
    return [{"id": i.id, "name": i.company.name, "sector": i.company.sector, "status": serialize_ipo_summary(i)["status"]} for i in all_ipos(db)]
