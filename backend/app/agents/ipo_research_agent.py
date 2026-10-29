"""Bounded, auditable IPO research agent.

Workflow
  1. Parse the research objective (intent keywords) and resolve the target IPO(s).
  2. Plan tool calls for the intents and execute them (validated, audited, bounded).
  3. If a local/optional model is healthy, let it request further tools for at most
     ``agent_max_steps`` steps, then produce a structured answer citing evidence ids.
  4. Validate the model answer: unknown evidence ids are removed, points without
     evidence are dropped, numbers that do not appear in tool results are rejected.
     If too much fails validation, the deterministic answer is used instead.
  5. Without a model, a deterministic composer writes the answer from tool outputs.
     It does not pretend to be generative AI.

The model never computes or overrides scores; those come from the scoring engine.
"""
from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.agents.prompts import AGENT_SCHEMA, SYSTEM_AGENT
from app.agents.tools import (
    TOOLS,
    Evidence,
    ToolCallRecord,
    ToolContext,
    execute_tool,
    ipo_index,
    tool_catalog,
)
from app.agents.validation import compact_json, numbers_in_data, numbers_in_text, unsupported_numbers
from app.config import Settings, get_settings
from app.models import User
from app.services.ipo_service import get_active_config, get_ipo, score_ipo, score_summary
from app.services.llm_provider import ProviderError, ProviderSelection, select_provider
from app.services.rag import quote_untrusted

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "compare": ("compare", " vs ", " vs.", "versus", "side by side", "better than"),
    "report": ("report", "write up", "write-up"),
    "missing": ("missing", "what data", "insufficient", "coverage", "provenance", "what is needed", "unavailable", "sources"),
    "scenario": ("scenario", "bull", "bear", "best case", "worst case", "base case", "what if"),
    "valuation": ("valuation", "valued", "peer", "p/e", "pe ratio", "multiple", "expensive", "cheap", "overvalued", "undervalued", "ev/ebitda"),
    "risk": ("risk", "red flag", "litigation", "concern", "governance", "danger"),
    "disclosures": ("disclosure", "offer document", "drhp", "rhp", "prospectus", "objects of", "proceeds", "filing", "document says"),
    "ratios": ("ratio", "margin", "roe", "roce", "debt", "cagr", "metric", "cash flow", "leverage"),
    "historical": ("historical", "past ipo", "previous ipo", "comparable ipo", "listing gain", "listed ipos", "listing return"),
    "explain_score": ("why", "explain", "score", "how is", "breakdown"),
    "fundamentals": ("fundamental", "analy", "financial", "business", "overview", "tell me about", "summar"),
}

PLAN: dict[str, list[str]] = {
    "fundamentals": ["get_ipo_profile", "get_financial_statements", "calculate_financial_metrics", "calculate_quality_score"],
    "explain_score": ["calculate_quality_score", "calculate_valuation_score", "calculate_risk_score", "get_data_provenance"],
    "valuation": ["calculate_valuation_score", "compare_ipo_peers"],
    "risk": ["calculate_risk_score", "get_official_disclosures", "search:risk factors"],
    "disclosures": ["get_official_disclosures", "search:message"],
    "ratios": ["get_financial_statements", "calculate_financial_metrics"],
    "scenario": ["run_scenario_analysis"],
    "report": ["generate_research_report"],
    "missing": ["get_data_provenance"],
    "historical": ["get_historical_comparable_ipos"],
}


class _Call(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class _Point(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    evidence: list[str] = Field(default_factory=list, max_length=12)


class _Answer(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    points: list[_Point] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


class _Step(BaseModel):
    action: str
    calls: list[_Call] = Field(default_factory=list, max_length=3)
    answer: _Answer | None = None


@dataclass
class AgentRun:
    message: str
    intents: list[str]
    ipo_ids: list[int]
    calls: list[ToolCallRecord] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    evidence_by_key: dict[tuple, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    report_id: int | None = None

    def add_evidence(self, ev: Evidence) -> str:
        k = ev.key()
        if k not in self.evidence_by_key:
            eid = f"E{len(self.evidence) + 1}"
            self.evidence[eid] = ev
            self.evidence_by_key[k] = eid
        return self.evidence_by_key[k]

    def result(self, name: str, ipo_id: int | None = None) -> dict[str, Any] | None:
        for c in self.calls:
            if c.name == name and c.status == "ok" and c.result and (ipo_id is None or c.arguments.get("ipo_id") == ipo_id):
                return c.result.data
        return None

    def eids(self, name: str, ipo_id: int | None = None) -> list[str]:
        for c in self.calls:
            if c.name == name and c.status == "ok" and c.result and (ipo_id is None or c.arguments.get("ipo_id") == ipo_id):
                return [self.evidence_by_key[e.key()] for e in c.result.evidence if e.key() in self.evidence_by_key]
        return []


def classify(message: str) -> list[str]:
    m = f" {message.lower()} "
    intents = [k for k, kws in INTENT_KEYWORDS.items() if any(kw in m for kw in kws)]
    if "explain_score" in intents and len(intents) > 1 and not re.search(r"\bscore", m):
        intents.remove("explain_score")  # "why" alone attaches to the more specific intent
    return intents or ["fundamentals"]


def resolve_ipos(db: Session, message: str, context_ipo_id: int | None) -> list[int]:
    idx = ipo_index(db)
    m = message.lower()
    found: list[int] = []
    for hit in re.findall(r"(?:ipo|id)\s*#?\s*(\d{1,6})", m):
        if any(i["id"] == int(hit) for i in idx):
            found.append(int(hit))
    tokens = re.findall(r"[a-z][a-z0-9&\-]{2,}", m)
    words = set(tokens)
    by_position: list[tuple[int, int]] = []  # (position in message, ipo id) so the first-named IPO is primary
    for i in idx:
        name = i["name"].lower()
        first = re.sub(r"[^a-z0-9]", "", name.split()[0])
        if first and len(first) >= 4 and first in words:
            by_position.append((m.find(first), i["id"]))
        elif name.replace(" ltd", "").replace(" limited", "") in m:
            by_position.append((m.find(name.replace(" ltd", "").replace(" limited", "")), i["id"]))
        else:
            close = [w for w in tokens if len(w) >= 5 and difflib.SequenceMatcher(None, first, w).ratio() >= 0.88]
            if close:
                by_position.append((m.find(close[0]), i["id"]))
    found += [iid for _, iid in sorted(by_position)]
    ordered = list(dict.fromkeys(found))
    if not ordered and context_ipo_id and any(i["id"] == context_ipo_id for i in idx):
        ordered = [context_ipo_id]
    elif context_ipo_id and context_ipo_id not in ordered and "compare" in classify(message) and len(ordered) == 1:
        ordered = [context_ipo_id, *ordered]
    return ordered[:4]


class IPOResearchAgent:
    def __init__(self, db: Session, user: User | None, settings: Settings | None = None, selection: ProviderSelection | None = None) -> None:
        self.db = db
        self.user = user
        self.s = settings or get_settings()
        self.selection = selection

    # ------------------------------------------------------------------ execution
    def _call(self, run: AgentRun, name: str, args: dict[str, Any], deadline: float) -> ToolCallRecord | None:
        if len(run.calls) >= self.s.agent_max_tool_calls:
            run.warnings.append(f"tool-call limit ({self.s.agent_max_tool_calls}) reached")
            return None
        if time.monotonic() > deadline:
            run.warnings.append("time limit reached before all tools ran")
            return None
        for c in run.calls:  # avoid repeating identical calls
            if c.name == name and c.arguments == args:
                return c
        rec = execute_tool(ToolContext(self.db, self.user), name, args)
        run.calls.append(rec)
        if rec.result:
            for ev in rec.result.evidence:
                run.add_evidence(ev)
            if name == "generate_research_report":
                run.report_id = rec.result.data.get("report_id")
        return rec

    def _plan(self, run: AgentRun) -> list[tuple[str, dict[str, Any]]]:
        calls: list[tuple[str, dict[str, Any]]] = []
        if not run.ipo_ids:
            if any(i in run.intents for i in ("disclosures", "risk")):
                calls.append(("search_local_research_documents", {"query": run.message[:300]}))
            return calls
        primary = run.ipo_ids[0]
        if "compare" in run.intents and len(run.ipo_ids) >= 2:
            calls.append(("compare_ipo_peers", {"ipo_id": primary, "compare_with_ipo_ids": run.ipo_ids[1:]}))
            for i in run.ipo_ids:
                calls.append(("calculate_quality_score", {"ipo_id": i}))
                calls.append(("calculate_risk_score", {"ipo_id": i}))
        for intent in run.intents:
            for step in PLAN.get(intent, []):
                if step == "search:risk factors":
                    calls.append(("search_local_research_documents", {"query": "risk factors dependence litigation", "ipo_id": primary}))
                elif step == "search:message":
                    calls.append(("search_local_research_documents", {"query": run.message[:300], "ipo_id": primary}))
                else:
                    calls.append((step, {"ipo_id": primary}))
        return calls

    # ------------------------------------------------------------------ model loop
    def _tool_digest(self, run: AgentRun) -> str:
        parts = []
        for c in run.calls:
            if c.status != "ok" or not c.result:
                parts.append(f"## {c.name}({c.arguments}) -> {c.status}: {c.summary}")
                continue
            ids = [run.evidence_by_key[e.key()] for e in c.result.evidence if e.key() in run.evidence_by_key]
            data = c.result.data
            if c.name == "search_local_research_documents":
                body = quote_untrusted(data.get("results", [])) or "no passages met the relevance threshold"
            else:
                body = compact_json(data, 3500)
            parts.append(f"## {c.name}({c.arguments}) evidence={ids}\n{body}")
        ev = "\n".join(f"{k}: {v.kind} — {v.label}" + (f" [{v.data_status}]" if v.data_status else "") for k, v in run.evidence.items())
        text = "TOOL RESULTS\n" + "\n".join(parts) + "\n\nEVIDENCE INDEX\n" + ev
        return text[: self.s.agent_max_context_chars]

    def _model_loop(self, run: AgentRun, deadline: float) -> tuple[_Answer | None, str | None]:
        sel = self.selection or select_provider(self.s)
        self.selection = sel
        if sel.provider is None:
            return None, sel.reason
        catalog = compact_json([{"name": t["name"], "description": t["description"]} for t in tool_catalog()], 3000)
        ipos = compact_json(ipo_index(self.db), 2500)
        for step in range(self.s.agent_max_steps):
            remaining = deadline - time.monotonic()
            if remaining <= 2:
                return None, "agent time limit reached"
            user_msg = (f"OBJECTIVE: {run.message}\nTARGET IPO IDS: {run.ipo_ids}\nKNOWN IPOS: {ipos}\nTOOLS: {catalog}\n\n"
                        f"{self._tool_digest(run)}\n\nStep {step + 1} of {self.s.agent_max_steps}. "
                        f"{'Answer now with action=final.' if step == self.s.agent_max_steps - 1 else ''}")
            raw = None
            for _attempt in range(2):  # one bounded retry on invalid output
                try:
                    raw = sel.provider.chat_json(SYSTEM_AGENT, [{"role": "user", "content": user_msg}], AGENT_SCHEMA, timeout=min(remaining, self.s.ollama_timeout_seconds))
                    parsed = _Step.model_validate(raw)
                    break
                except ProviderError as exc:
                    return None, f"model error: {exc}"
                except ValidationError:
                    parsed = None
            if parsed is None:
                return None, "model output failed schema validation twice"
            if parsed.action == "final" and parsed.answer is not None:
                return parsed.answer, None
            if parsed.action == "call_tools" and parsed.calls:
                for c in parsed.calls[:3]:
                    if c.tool not in TOOLS:
                        run.warnings.append(f"model requested unknown tool '{c.tool}' — rejected")
                        run.calls.append(ToolCallRecord(c.tool, {}, "rejected", "unknown tool", 0))
                        continue
                    self._call(run, c.tool, c.args, deadline)
                continue
            return None, "model returned neither tool calls nor an answer"
        return None, "step limit reached without a final answer"

    def _validate_answer(self, run: AgentRun, ans: _Answer) -> tuple[_Answer | None, list[str]]:
        notes: list[str] = []
        allowed = numbers_in_data([c.result.data for c in run.calls if c.result]) | set(numbers_in_text(run.message))
        kept: list[_Point] = []
        for p in ans.points:
            ev = [e for e in p.evidence if e in run.evidence]
            if len(ev) < len(p.evidence):
                notes.append("removed citation(s) to evidence ids that do not exist")
            if not ev:
                notes.append(f"dropped a point without valid evidence: {p.text[:80]!r}")
                continue
            bad = unsupported_numbers(p.text, allowed)
            if bad:
                notes.append(f"dropped a point with numbers not found in tool results {bad[:3]}")
                continue
            kept.append(_Point(text=p.text, evidence=ev))
        bad_summary = unsupported_numbers(ans.summary, allowed)
        if bad_summary or (ans.points and len(kept) < max(1, len(ans.points) // 2)):
            notes.append("model answer failed validation; deterministic answer used")
            return None, notes
        return _Answer(summary=ans.summary, points=kept, limitations=ans.limitations, follow_up_questions=ans.follow_up_questions), notes

    # ------------------------------------------------------------------ deterministic composer
    def _compose(self, run: AgentRun) -> _Answer:
        pts: list[_Point] = []
        lim: list[str] = []

        def add(text: str, eids: list[str]) -> None:
            if eids:
                pts.append(_Point(text=text, evidence=eids[:6]))

        if not run.ipo_ids:
            res = run.result("search_local_research_documents")
            if res and res.get("results"):
                for r in res["results"][:4]:
                    add(f"{r['document_title']} p.{r['page']}: \"{r['text'][:280]}…\"", run.eids("search_local_research_documents"))
                return _Answer(summary="Passages from stored documents that match the question (no IPO was identified).", points=pts,
                               limitations=["Name the IPO to get scores and financial analysis."])
            names = ", ".join(i["name"] for i in ipo_index(self.db)[:12])
            return _Answer(summary="I could not identify which IPO you mean. Mention the company name or open the question from an IPO page.",
                           points=[], limitations=[f"Known IPOs include: {names}"])

        pid = run.ipo_ids[0]
        prof = run.result("get_ipo_profile", pid)
        q = run.result("calculate_quality_score", pid)
        v = run.result("calculate_valuation_score", pid)
        k = run.result("calculate_risk_score", pid)
        name = (prof or {}).get("company_name") or next((i["name"] for i in ipo_index(self.db) if i["id"] == pid), f"IPO {pid}")

        if prof:
            add(f"{name} is a {prof['issue_type']} issue on {prof['exchange']} ({prof['status']}); price band ₹{prof['price_band_low']}–₹{prof['price_band_high']}, "
                f"issue size ₹{prof['issue_size_cr']} cr (fresh ₹{prof['fresh_issue_cr']} cr, OFS ₹{prof['ofs_cr']} cr).", run.eids("get_ipo_profile", pid))
            if prof.get("business_model"):
                add(f"Business model: {prof['business_model']}", run.eids("get_ipo_profile", pid))
            if prof["data_status"] == "synthetic":
                lim.append("This IPO is SYNTHETIC demonstration data about a fictional company.")
        fin = run.result("get_financial_statements", pid)
        if fin and fin["statements"]:
            last = fin["statements"][-1]
            add(f"Latest period {last['period_label']}: revenue ₹{last['revenue']} cr, EBITDA ₹{last['ebitda']} cr, PAT ₹{last['pat']} cr, "
                f"operating cash flow ₹{last['operating_cash_flow']} cr ({last['data_status']}).", run.eids("get_financial_statements", pid))
        met = run.result("calculate_financial_metrics", pid)
        if met:
            m = met["metrics"]
            shown = []
            for key in ("revenue_cagr", "ebitda_margin", "pat_margin", "roe", "debt_to_equity", "ocf_to_pat"):
                x = m.get(key)
                if x and x["status"] == "ok":
                    shown.append(f"{x['label']} {x['value']:.2f}{'%' if x['unit'] == '%' else ('x' if x['unit'] == 'x' else '')}")
                elif x:
                    lim.append(f"{x['label']}: {x['reason']}")
            if shown:
                add("Computed metrics: " + "; ".join(shown) + ".", run.eids("calculate_financial_metrics", pid))
        if q:
            if q["quality"] is not None:
                comps = sorted(((n, c["score"]) for n, c in q["components"].items() if c["score"] is not None), key=lambda x: x[1])
                add(f"Quality score Q = {q['quality']} ({q['formula']}). Weakest component: {comps[0][0].replace('_', ' ')} ({comps[0][1]}); "
                    f"strongest: {comps[-1][0].replace('_', ' ')} ({comps[-1][1]}).", run.eids("calculate_quality_score", pid))
            else:
                miss = [n for n, c in q["components"].items() if c["status"] != "ok"]
                add(f"Quality score unavailable — insufficient data in: {', '.join(miss)}.", run.eids("calculate_quality_score", pid))
        if v:
            if v["score"] is not None:
                add(f"Relative valuation V = {v['score']}: IPO {v['multiple_label']} {v['ipo_multiple']}x vs peer median {v['peer_median']}x "
                    f"(p{v['low_percentile']}–p{v['high_percentile']} range {v['peer_low']}x–{v['peer_high']}x; premium {v['premium_to_median_pct']}%).",
                    run.eids("calculate_valuation_score", pid))
            else:
                add(f"Valuation score unavailable: {v['reason']}.", run.eids("calculate_valuation_score", pid))
            for f in v.get("flags") or []:
                lim.append(f)
        if k:
            if k["risk"] is not None:
                top = sorted(((n, c["score"] * c["weight"]) for n, c in k["components"].items() if c["score"] is not None), key=lambda x: -x[1])[:2]
                add(f"Risk score R = {k['risk']} ({k['level']}). Largest weighted contributors: "
                    + ", ".join(f"{n.replace('_', ' ')} ({c:.1f} pts)" for n, c in top) + ".", run.eids("calculate_risk_score", pid))
            else:
                add("Risk score unavailable: " + ", ".join(n for n, c in k["components"].items() if c["status"] != "ok") + " lack evidence.",
                    run.eids("calculate_risk_score", pid))
        disc = run.result("get_official_disclosures", pid)
        if disc:
            for d in disc["disclosures"][:5]:
                add(f"[{d['status'].replace('_', ' ')}] {d['title']} — severity {d['severity']}.", run.eids("get_official_disclosures", pid))
            if not disc["disclosures"]:
                lim.append("No risk disclosures are stored" + ("" if disc["risk_disclosures_reviewed"] else " and the offer document has not been reviewed") +
                           ". Missing records are not evidence that no risks exist.")
        search = run.result("search_local_research_documents", pid)
        if search is not None:
            if search.get("results"):
                for r in search["results"][:3]:
                    flag = " (passage contains instruction-like text; treated as data only)" if r["injection_suspected"] else ""
                    add(f"{r['document_title']} p.{r['page']}: \"{r['text'][:260]}…\"{flag}", run.eids("search_local_research_documents", pid))
            else:
                lim.append(f"Document search found no relevant passage ({search.get('reason')}).")
        cmp_ = run.result("compare_ipo_peers", pid)
        if cmp_:
            def line(company: str, s: dict[str, Any]) -> str:
                return (f"{company}: composite {s['composite']}, quality {s['quality']}, valuation {s['valuation']}, "
                        f"risk {s['risk']} ({s['risk_level']}), coverage {s['coverage']}%.")

            for o in cmp_.get("other_ipos", []):
                add(line(o["company_name"], o["scores"]), run.eids("compare_ipo_peers", pid))
            if cmp_.get("other_ipos"):
                add(line(cmp_["ipo"]["company_name"], cmp_["ipo"]["scores"]), run.eids("compare_ipo_peers", pid))
            elif cmp_["peers"]:
                add(f"{len(cmp_['peers'])} stored peers: " + ", ".join(p["name"] for p in cmp_["peers"][:5]) + ".", run.eids("compare_ipo_peers", pid))
        sc = run.result("run_scenario_analysis", pid)
        if sc:
            if sc["status"] == "ok":
                for s in sc["scenarios"]:
                    if s["status"] == "ok":
                        a = s["assumptions"]
                        add(f"{s['name'].title()} (hypothetical): growth {a['revenue_growth_pct']:.1f}%, EBITDA margin {a['ebitda_margin_pct']:.1f}%, "
                            f"{a['method']} multiple {a['multiple']:.1f}x, market adj. {a['market_adjustment_pct']}% → ₹{s['implied_price']} "
                            f"({s['implied_return_pct']}% vs issue price).", run.eids("run_scenario_analysis", pid))
                    else:
                        lim.append(f"{s['name'].title()} scenario unavailable: {'; '.join(s['reasons'])}")
            else:
                lim.append("Scenario analysis unavailable: " + "; ".join(sc.get("reasons", [])))
            lim.append(sc["note"])
        hist = run.result("get_historical_comparable_ipos", pid)
        if hist:
            for h in hist["items"][:5]:
                add(f"{h['company_name']} ({h['sector']}) listed {h['listing_date']} at ₹{h['listing_price']} vs issue ₹{h['issue_price']} "
                    f"({h['listing_return_pct']}%, {h['data_status']}).", run.eids("get_historical_comparable_ipos", pid))
            lim.append(hist["note"])
        prov = run.result("get_data_provenance", pid)
        if prov:
            add(f"Evidence coverage C = {prov['evidence_coverage']}% (input completeness {prov['input_completeness']}%).", run.eids("get_data_provenance", pid))
            gaps = [i["key"] for i in prov["evidence_items"] if not i["present"]]
            if gaps:
                add("Inputs missing entirely: " + ", ".join(gaps) + ".", run.eids("get_data_provenance", pid))
            for m in prov["missing_components"]:
                lim.append(f"Composite unavailable — {m['component']}: {m['reason']}")
        rep = run.result("generate_research_report", pid)
        if rep:
            add(f"Generated report '{rep['title']}' ({rep['generator']})" + (f", saved as report #{rep['report_id']}." if rep["report_id"] else f". {rep.get('save_note') or ''}"),
                run.eids("generate_research_report", pid))

        engine = self._cross_check(run, pid)
        if engine and engine.get("composite") is not None:
            w = get_active_config(self.db)["composite"]["weights"]
            summary = (f"{name}: composite research score {engine['composite']} = {w['quality']}×{engine['quality']} + {w['valuation']}×{engine['valuation']} "
                       f"+ {w['risk_inverse']}×(100 − {engine['risk']}). This is an educational summary of stored inputs, not a probability of listing gains.")
        else:
            summary = f"Research findings for {name} from KcpInsights tools (deterministic engine)."
        if any(ev.data_status == "synthetic" for ev in run.evidence.values()):
            lim.insert(0, "Includes SYNTHETIC demonstration data about fictional companies — not real financial facts.")
        lim.append("Educational research only — not investment advice.")
        return _Answer(summary=summary, points=pts, limitations=list(dict.fromkeys(lim)))

    def _cross_check(self, run: AgentRun, pid: int) -> dict[str, Any] | None:
        """Recompute the composite from tool outputs and compare with the engine's own result."""
        q = run.result("calculate_quality_score", pid)
        v = run.result("calculate_valuation_score", pid)
        k = run.result("calculate_risk_score", pid)
        if not (q and v and k):
            return None
        ipo = get_ipo(self.db, pid)
        if ipo is None:
            return None
        engine = score_summary(score_ipo(self.db, ipo, persist=False))
        if None not in (q["quality"], v["score"], k["risk"]) and engine["composite"] is not None:
            w = get_active_config(self.db)["composite"]["weights"]
            recomputed = w["quality"] * q["quality"] + w["valuation"] * v["score"] + w["risk_inverse"] * (100 - k["risk"])
            if abs(recomputed - engine["composite"]) > 0.05:
                run.warnings.append(f"cross-check mismatch: tools imply {recomputed:.2f}, engine reports {engine['composite']}; engine value shown")
        return engine

    # ------------------------------------------------------------------ entry point
    def run(self, message: str, context_ipo_id: int | None = None) -> dict[str, Any]:
        started = time.monotonic()
        deadline = started + self.s.agent_deadline_seconds
        message = message.strip()[:2000]
        run = AgentRun(message=message, intents=classify(message), ipo_ids=resolve_ipos(self.db, message, context_ipo_id))
        for name, args in self._plan(run):
            self._call(run, name, args, deadline)

        model_note: str | None = None
        answer: _Answer | None = None
        validation_notes: list[str] = []
        mode = "deterministic"
        if self.s.ai_provider != "deterministic":
            model_ans, model_note = self._model_loop(run, deadline)
            if model_ans is not None:
                answer, validation_notes = self._validate_answer(run, model_ans)
                if answer is not None and self.selection and self.selection.provider is not None:
                    mode = f"{self.selection.mode}:{getattr(self.selection.provider, 'model', '')}"
        if answer is None:
            answer = self._compose(run)
            if model_note:
                run.warnings.append(f"AI model not used: {model_note}")
        run.warnings.extend(validation_notes)

        used = {e for p in answer.points for e in p.evidence}
        evidence = [{"id": k, "kind": ev.kind, "label": ev.label, "ref_id": ev.ref_id, "url": ev.url, "data_status": ev.data_status,
                     "page": ev.page, "cited": k in used, "detail": ev.detail} for k, ev in run.evidence.items()]
        md = [answer.summary, ""]
        md += [f"- {p.text} [{', '.join(p.evidence)}]" for p in answer.points]
        if answer.limitations:
            md += ["", "Limitations:"] + [f"- {x}" for x in answer.limitations]
        return {
            "answer": answer.model_dump(),
            "answer_text": "\n".join(md),
            "mode": mode,
            "generative": mode != "deterministic",
            "intents": run.intents,
            "ipo_ids": run.ipo_ids,
            "evidence": evidence,
            "tool_calls": [{"tool": c.name, "arguments": c.arguments, "status": c.status, "summary": c.summary, "duration_ms": c.duration_ms} for c in run.calls],
            "warnings": list(dict.fromkeys(run.warnings)),
            "report_id": run.report_id,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
