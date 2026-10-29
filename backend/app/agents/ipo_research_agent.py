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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.agents.prompts import AGENT_SCHEMA, SUMMARY_SCHEMA, SYSTEM_AGENT, SYSTEM_SUMMARY
from app.agents.tools import (
    TOOLS,
    Evidence,
    ToolCallRecord,
    ToolContext,
    execute_tool,
    ipo_index,
    tool_catalog,
)
from app.agents.validation import (
    advice_problems,
    compact_json,
    date_problems,
    date_roles,
    dates_in_text,
    label_estimates,
    numbers_in_data,
    numbers_in_text,
    unit_problems,
    unit_values,
    unsupported_numbers,
)
from app.config import Settings, get_settings
from app.models import User
from app.services.ipo_service import get_active_config, get_ipo, score_ipo, score_summary
from app.services.llm_provider import ProviderError, ProviderSelection, select_provider

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "compare": ("compare", " vs ", " vs.", "versus", "side by side", "better than"),
    "report": ("report", "write up", "write-up"),
    "discover": ("which ipo", "what ipo", "list of ipo", "upcoming ipo", "ipos opening", "ipos open", "open ipo", "currently open",
                 "new ipo", "ipos closing", "ipos listing", "ipos this", "ipos next", "any ipo"),
    "schedule": ("when ", "listing date", "list on", "will list", "expected to list", "allotment", "next week", "this week", "tomorrow",
                 "schedule", "calendar", "timeline", "key dates", "closing date", "opening date"),
    "subscription": ("subscri", "oversubscribed", "demand", "qib", " bids", "how many times"),
    "status": ("status", "latest", "changed", "change ", "updated", "current", "right now", "what is known"),
    "source": ("source", "citation", "where did", "evidence", "provenance", " link"),
    "missing": ("missing", "what data", "insufficient", "coverage", "what is needed", "unavailable", "still unknown"),
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
    "schedule": ["get_latest_ipo_status"],
    "subscription": ["get_subscription_data", "get_latest_ipo_status"],
    "status": ["get_latest_ipo_status"],
    "source": ["get_source_provenance", "get_latest_ipo_status"],
    "fundamentals": ["get_latest_ipo_status", "get_ipo_details", "get_verified_financials", "calculate_financial_metrics", "calculate_quality_score"],
    "explain_score": ["get_quantitative_score", "calculate_quality_score", "calculate_valuation_score", "get_risk_breakdown", "get_source_provenance"],
    "valuation": ["calculate_valuation_score", "compare_ipo_peers"],
    "risk": ["get_risk_breakdown", "get_official_disclosures", "search:risk factors"],
    "disclosures": ["get_official_disclosures", "search:message"],
    "ratios": ["get_verified_financials", "calculate_financial_metrics"],
    "scenario": ["run_scenario_analysis"],
    "report": ["generate_research_report"],
    "missing": ["get_source_provenance", "get_latest_ipo_status"],
    "historical": ["get_historical_comparable_ipos"],
}


class _Call(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


POINT_KINDS = ("fact", "calculation", "interpretation", "hypothetical")


class _Point(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    evidence: list[str] = Field(default_factory=list, max_length=12)
    # fact = source-backed value; calculation = engine/derived metric or estimate;
    # interpretation = explanation of facts; hypothetical = scenario output
    kind: Literal["fact", "calculation", "interpretation", "hypothetical"] = "fact"


class _Answer(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    points: list[_Point] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


def _cap_limitations(lim: list[str]) -> list[str]:
    """Deduplicate and fit the answer's limit, folding the overflow into one line; the last (general) caveat is kept."""
    lim = list(dict.fromkeys(lim))
    cap = _Answer.model_fields["limitations"].metadata[0].max_length
    if len(lim) <= cap:
        return lim
    return lim[: cap - 2] + [f"{len(lim) - cap + 1} further data gaps are listed in the score breakdown."] + lim[-1:]


class _Step(BaseModel):
    action: str
    calls: list[_Call] = Field(default_factory=list, max_length=3)


class _Summary(BaseModel):
    summary: str = Field(min_length=1, max_length=1500)


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


def parse_date_range(message: str, today: date) -> tuple[date, date, str] | None:
    """Relative date phrases used in research questions -> (from, to, label)."""
    m = message.lower()
    monday = today - timedelta(days=today.weekday())
    if "next week" in m:
        return monday + timedelta(days=7), monday + timedelta(days=13), "next week"
    if "this week" in m:
        return today, monday + timedelta(days=6), "this week"
    if "tomorrow" in m:
        return today + timedelta(days=1), today + timedelta(days=1), "tomorrow"
    if "today" in m:
        return today, today, "today"
    if "next month" in m:
        first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1), "next month"
    if "this month" in m:
        return today, (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1), "this month"
    n = re.search(r"next (\d{1,3}) days", m)
    if n:
        return today, today + timedelta(days=int(n.group(1))), f"next {n.group(1)} days"
    return None


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
    def __init__(self, db: Session, user: User | None, settings: Settings | None = None, selection: ProviderSelection | None = None,
                 refresher: Callable[[int], dict[str, Any]] | None = None, today: date | None = None) -> None:
        self.db = db
        self.user = user
        self.s = settings or get_settings()
        self.selection = selection
        self.refresher = refresher
        self.today = today or date.today()

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
        rec = execute_tool(ToolContext(self.db, self.user, refresher=self.refresher), name, args)
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
            m = run.message.lower()
            rng = parse_date_range(run.message, self.today)
            if any(i in run.intents for i in ("discover", "schedule", "status", "subscription")):
                frm, to = (rng[0], rng[1]) if rng else (self.today, self.today + timedelta(days=14))
                if any(w in m for w in ("list", "allot")) and "listed" not in m:
                    calls.append(("get_listing_schedule", {"date_from": frm.isoformat(), "date_to": to.isoformat()}))
                elif "listed" in m:
                    calls.append(("search_ipos", {"status": ["listed"], "limit": 15}))
                elif "open" in m and "opening" not in m and rng is None:
                    calls.append(("search_ipos", {"status": ["open"], "limit": 20}))
                else:
                    calls.append(("search_ipos", {"status": ["upcoming", "open"], "opening_from": frm.isoformat(), "opening_to": to.isoformat(), "limit": 20}))
            if any(i in run.intents for i in ("disclosures", "risk")):
                calls.append(("search_offer_documents", {"query": run.message[:300]}))
            return calls
        primary = run.ipo_ids[0]
        if "compare" in run.intents and len(run.ipo_ids) >= 2:
            calls.append(("compare_ipos", {"ipo_ids": run.ipo_ids}))
            calls.append(("compare_ipo_peers", {"ipo_id": primary, "compare_with_ipo_ids": run.ipo_ids[1:]}))
            for i in run.ipo_ids:
                calls.append(("calculate_quality_score", {"ipo_id": i}))
                calls.append(("get_risk_breakdown", {"ipo_id": i}))
        for intent in run.intents:
            for step in PLAN.get(intent, []):
                if step == "search:risk factors":
                    calls.append(("search_offer_documents", {"query": "risk factors dependence litigation", "ipo_id": primary}))
                elif step == "search:message":
                    calls.append(("search_offer_documents", {"query": run.message[:300], "ipo_id": primary}))
                else:
                    calls.append((step, {"ipo_id": primary}))
        return calls

    # ------------------------------------------------------------------ model: tool planning
    def _model_plan(self, run: AgentRun, deadline: float) -> tuple[str | None, bool]:
        """Let the model request extra tools. Returns (note, fatal); fatal means the model is unusable for this run."""
        sel = self.selection or select_provider(self.s)
        self.selection = sel
        if sel.provider is None:
            return sel.reason, True
        catalog = compact_json([{"name": t["name"], "description": t["description"]} for t in tool_catalog()], 3000)
        ipos = compact_json(ipo_index(self.db), 2500)
        for step in range(self.s.agent_max_steps):
            remaining = deadline - time.monotonic()
            if remaining <= 2:
                return "agent time limit reached", True
            done = "\n".join(f"- {c.name}({compact_json(c.arguments, 200)}) -> {c.status}: {c.summary}" for c in run.calls) or "none"
            user_msg = (f"OBJECTIVE: {run.message}\nTARGET IPO IDS: {run.ipo_ids}\nKNOWN IPOS: {ipos}\nTOOLS: {catalog}\n\n"
                        f"ALREADY RUN:\n{done}\n\nStep {step + 1} of {self.s.agent_max_steps}.")
            parsed = None
            for _attempt in range(2):  # one bounded retry on invalid output
                try:
                    raw = sel.provider.chat_json(SYSTEM_AGENT, [{"role": "user", "content": user_msg}], AGENT_SCHEMA,
                                                 timeout=min(remaining, self.s.ollama_timeout_seconds))
                    parsed = _Step.model_validate(raw)
                    break
                except ProviderError as exc:
                    return f"model error: {exc}", True
                except ValidationError:
                    parsed = None
            if parsed is None:
                return "model output failed schema validation twice", True
            if parsed.action == "final" or not parsed.calls:
                return None, False
            for c in parsed.calls[:3]:
                if c.tool not in TOOLS:
                    run.warnings.append(f"model requested unknown tool '{c.tool}' — rejected")
                    run.calls.append(ToolCallRecord(c.tool, {}, "rejected", "unknown tool", 0))
                    continue
                self._call(run, c.tool, c.args, deadline)
        return "step limit reached while planning", False

    # ------------------------------------------------------------------ model: grounded summary
    def _model_summary(self, run: AgentRun, ans: _Answer, deadline: float) -> tuple[str | None, list[str]]:
        """Ask the model for a short direct answer written only from the verified points, then check it."""
        assert self.selection is not None and self.selection.provider is not None
        remaining = deadline - time.monotonic()
        if remaining <= 2:
            return None, ["agent time limit reached before the AI summary"]
        if not ans.points:
            return None, []
        pts = "\n".join(f"P{i} [{p.kind}] {p.text}" for i, p in enumerate(ans.points, 1))
        lim = "\n".join(f"- {x}" for x in ans.limitations) or "none"
        msg = f"QUESTION: {run.message}\n\nVERIFIED POINTS:\n{pts}\n\nLIMITATIONS:\n{lim}"
        summary = None
        for _attempt in range(2):
            try:
                raw = self.selection.provider.chat_json(SYSTEM_SUMMARY, [{"role": "user", "content": msg}], SUMMARY_SCHEMA,
                                                        timeout=min(remaining, self.s.ollama_timeout_seconds))
                summary = _Summary.model_validate(raw).summary.strip()
                break
            except ProviderError as exc:
                return None, [f"model error: {exc}"]
            except ValidationError:
                summary = None
        if not summary:
            return None, ["AI summary failed schema validation twice"]
        return self._check_summary(run, ans, summary)

    def _check_summary(self, run: AgentRun, ans: _Answer, summary: str) -> tuple[str | None, list[str]]:
        data = [c.result.data for c in run.calls if c.result]
        allowed = numbers_in_data(data) | numbers_in_data([p.text for p in ans.points]) | set(numbers_in_text(run.message))
        roles = date_roles(data)
        for d in [self.today, *(d for d, _a, _b in dates_in_text(run.message, self.today.year))]:
            roles.setdefault(d, set())
        multiples, percents = unit_values(data + [{"subscription": c.result.data.get("latest")} for c in run.calls
                                                  if c.result and c.name == "get_subscription_data"])
        problems = [f"numbers not found in tool results {n}" for n in unsupported_numbers(summary, allowed)[:3]]
        problems += date_problems(summary, roles, self.today.year) + unit_problems(summary, multiples, percents)
        problems += advice_problems(summary)
        if problems:
            return None, [f"AI summary rejected ({problems[0]}); engine summary used"]
        if any(ev.data_status == "synthetic" for ev in run.evidence.values()) and not re.search(r"synthetic|fictional|demo", summary, re.I):
            summary += " (This uses SYNTHETIC demonstration data about a fictional company.)"
        nums, dates = self._estimates(run)
        summary, labelled = label_estimates(summary, nums, dates)
        return summary, ([f"labelled {labelled} estimated value(s) the model stated without a qualifier"] if labelled else [])

    @staticmethod
    def _estimates(run: AgentRun) -> tuple[set[float], set[date]]:
        """Estimated numbers and dates in tool results. A date that is also a confirmed date elsewhere is left out,
        since a bare mention of it cannot be attributed."""
        nums: set[float] = set()
        dates: set[date] = set()
        certain: set[date] = set()

        def as_date(v: Any) -> date | None:
            try:
                return date.fromisoformat(v[:10]) if isinstance(v, str) else None
            except ValueError:
                return None

        def walk(x: Any) -> None:
            if isinstance(x, dict):
                for f in (x.get("estimated_fields") or {}).values():
                    v = f.get("value")
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        nums.add(float(v))
                    elif (d := as_date(v)) is not None:
                        dates.add(d)
                if (d := as_date(x.get("date"))) is not None:
                    (dates if "estimated" in (x.get("date_status"), x.get("status")) else certain).add(d)
                for k in ("open_date", "close_date"):
                    if (d := as_date(x.get(k))) is not None:
                        certain.add(d)
                if x.get("listing_date_status") == "actual" and (d := as_date(x.get("listing_date"))) is not None:
                    certain.add(d)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        for c in run.calls:
            if c.result:
                walk(c.result.data)
        return nums, dates - certain

    # ------------------------------------------------------------------ deterministic composer
    def _compose(self, run: AgentRun) -> _Answer:
        pts: list[_Point] = []
        lim: list[str] = []

        calc_prefixes = ("Quality score", "Relative valuation", "Valuation score", "Risk score", "Evidence coverage", "Computed metrics", "Quality score unavailable")

        max_points = _Answer.model_fields["points"].metadata[0].max_length
        overflow: list[str] = []

        def add(text: str, eids: list[str], kind: str = "fact") -> None:
            if not eids:
                return
            if len(pts) >= max_points:
                overflow.append(text)
                if len(overflow) == 1:
                    lim.append("More results matched than fit in one answer; narrow the question (e.g. a shorter date range) to see the rest.")
                return
            if kind == "fact" and text.startswith(calc_prefixes):
                kind = "calculation"  # engine outputs are calculations, not sourced facts
            elif kind == "fact" and "(hypothetical)" in text:
                kind = "hypothetical"
            pts.append(_Point(text=text, evidence=eids[:6], kind=kind))  # type: ignore[arg-type]

        def ipo_eids(tool: str, ipo_name: str) -> list[str]:
            # evidence entries of a multi-IPO tool that belong to one company
            return [k for k, ev in run.evidence.items() if ev.label.startswith(f"{ipo_name}:") and k in run.eids(tool)] or run.eids(tool)

        if not run.ipo_ids:
            found = run.result("search_ipos")
            sched = run.result("get_listing_schedule")
            if found is not None or sched is not None:
                if found is not None:
                    for it in found["items"]:
                        band = f"₹{it['price_band_low']:g}–{it['price_band_high']:g}" if it["price_band_low"] and it["price_band_high"] else "price band not yet published"
                        lst = f"; listing {it['listing_date']} ({'expected' if it['listing_date_status'] == 'expected' else 'confirmed'})" if it["listing_date"] else ""
                        add(f"{it['company_name']} ({it['issue_type']}, {it['status']}): bidding {it['open_date'] or '—'} to {it['close_date'] or '—'}, {band}"
                            f"{', lot ' + str(it['lot_size']) if it['lot_size'] else ''}{lst}.", ipo_eids("search_ipos", it["company_name"]))
                    if not found["items"]:
                        lim.append("No stored IPO matches that window. Coverage is limited to issues published on NSE plus your imports.")
                    if found.get("demo_included"):
                        lim.append("Only SYNTHETIC demo data is loaded — run a live sync to see real IPOs.")
                if sched is not None:
                    by_day: dict[str, list[dict[str, Any]]] = {}
                    for e in sched["events"]:
                        by_day.setdefault(e["date"], []).append(e)
                    for day, evs in by_day.items():  # one point per date keeps busy weeks within the answer size
                        est = any(e["date_status"] == "estimated" for e in evs)
                        parts = [f"{e['company_name']} {e['event']}" + (" (expected)" if e["date_status"] == "estimated" else "") for e in evs]
                        add(f"{day}: {'; '.join(parts)}" + (" — expected dates are estimated from SEBI T+3, holidays not applied." if est else "."),
                            list(dict.fromkeys(k for e in evs for k in ipo_eids("get_listing_schedule", e["company_name"])))[:6],
                            "calculation" if est else "fact")
                    if not sched["events"]:
                        lim.append(f"No openings, closings, allotments or listings stored between {sched['from']} and {sched['to']}.")
                f = (found or {}).get("filters", {})
                window = f" between {f.get('opening_from')} and {f.get('opening_to')}" if f.get("opening_from") else ""
                summary = (f"{found['total_matches']} IPO(s) found{window} in the KcpInsights database." if found is not None
                           else f"IPO calendar from {sched['from']} to {sched['to']}.")  # type: ignore[index]
                lim.append("Dates and prices come from NSE's public issue pages as last synced; check the cited source before acting.")
                return _Answer(summary=summary, points=pts, limitations=_cap_limitations(lim))
            res = run.result("search_offer_documents")
            if res and res.get("results"):
                for r in res["results"][:4]:
                    add(f"{r['document_title']} p.{r['page']}: \"{r['text'][:280]}…\"", run.eids("search_offer_documents"))
                return _Answer(summary="Passages from stored documents that match the question (no IPO was identified).", points=pts,
                               limitations=["Name the IPO to get scores and financial analysis."])
            names = ", ".join(i["name"] for i in ipo_index(self.db)[:12])
            return _Answer(summary="I could not identify which IPO you mean. Mention the company name or open the question from an IPO page.",
                           points=[], limitations=[f"Known IPOs include: {names}"])

        pid = run.ipo_ids[0]
        prof = run.result("get_ipo_details", pid)
        q = run.result("calculate_quality_score", pid)
        v = run.result("calculate_valuation_score", pid)
        k = run.result("get_risk_breakdown", pid)
        name = (prof or {}).get("company_name") or next((i["name"] for i in ipo_index(self.db) if i["id"] == pid), f"IPO {pid}")

        live = run.result("get_latest_ipo_status", pid)
        if live:
            le = run.eids("get_latest_ipo_status", pid)
            add(f"{name} is currently {live['status']} (record {'live from NSE' if live['nse_symbol'] else live['data_mode']}, status {live['data_status']}).", le)
            for kd in live["key_dates"]:
                if kd["date"]:
                    add(f"{kd['label']}: {kd['date']}" + (" — estimated from SEBI's T+3 timeline (exchange holidays not applied)" if kd["status"] == "estimated" else "") + ".",
                        le, "calculation" if kd["status"] == "estimated" else "fact")
            if live["listing_price"] is not None:
                add(f"Listing-day open ₹{live['listing_price']} vs final issue price ₹{live['final_issue_price']}"
                    + (f" → listing return {live['listing_return_pct']}%." if live["listing_return_pct"] is not None else "."), le, "calculation")
            sub_ = live.get("subscription")
            if sub_:
                cats = ", ".join(f"{c.upper() if c in ('qib', 'nii') else c} {v:.2f}x" for c, v in sub_["categories"].items())
                add(f"Subscription as of {sub_['as_of']} {sub_.get('timezone') or ''} ({sub_['basis']}): {cats}.", le)
            if not live.get("recent_changes") and re.search(r"chang|moved|postpon|revis", run.message.lower()):
                add("No change to this issue's dates or price band has been recorded since KcpInsights began tracking it.", le)
            for ch in live.get("recent_changes", [])[:5]:
                add(f"{ch['field'].replace('_', ' ')} changed from {ch['old_value']} to {ch['new_value']} (recorded {ch['changed_at'][:16]} from {ch['source_key']}).", le)
            if live.get("refresh"):
                rf = live["refresh"]
                run.warnings.append("live refresh: " + ("done" if rf.get("refreshed") else rf.get("reason", "not performed")))
            if live["freshness"]["is_stale"]:
                lim.append("Stale data: " + "; ".join(live["freshness"]["stale_reasons"]))
            for issue in live.get("consistency_issues", []):
                lim.append(f"Date consistency check failed: {issue}")
            if live["freshness"]["missing_critical"]:
                lim.append("Not yet available from sources: " + ", ".join(live["freshness"]["missing_critical"]) + ".")
        subd = run.result("get_subscription_data", pid)
        if subd and not (live and live.get("subscription")):
            if subd["latest"]:
                add(f"Subscription as of {subd['latest_as_of']} {subd['timezone'] or ''}: " + ", ".join(f"{k} {v:.2f}x" for k, v in subd["latest"].items()) + ".",
                    run.eids("get_subscription_data", pid))
            else:
                lim.append(subd["note"])
        cmp2 = run.result("compare_ipos")
        if cmp2:
            def val(v: Any, fmt: str = "{:g}", unit: str = "") -> str:
                return "unavailable" if v is None else fmt.format(v) + unit

            for it in cmp2["items"]:
                s_ = it["scores"]
                risk_txt = val(s_["risk"]) + (f" ({s_['risk_level']})" if s_["risk"] is not None and s_.get("risk_level") else "")
                add(f"{it['company_name']} ({it['status']}): composite {val(s_['composite'])}, quality {val(s_['quality'])}, valuation {val(s_['valuation'])}, "
                    f"risk {risk_txt}, coverage {val(s_['coverage'], unit='%')}; subscription {val(it['subscription_total'], '{:.2f}', 'x')}; "
                    f"listing return {val(it['listing_return_pct'], '{:.2f}', '%')}.", ipo_eids("compare_ipos", it["company_name"]), "calculation")
        if prof:
            size_est = (prof.get("estimated_fields") or {}).get("issue_size_cr")
            size = (f"issue size ₹{prof['issue_size_cr']} cr" + (f" (estimated: {size_est['basis']})" if size_est else "")
                    + f" (fresh ₹{prof['fresh_issue_cr']} cr, OFS ₹{prof['ofs_cr']} cr)")
            add(f"{name} is a {prof['issue_type']} issue on {prof['exchange']} ({prof['status']}); price band ₹{prof['price_band_low']}–₹{prof['price_band_high']}, "
                f"{size}.", run.eids("get_ipo_details", pid), "calculation" if size_est else "fact")
            if prof.get("business_model"):
                add(f"Business model: {prof['business_model']}", run.eids("get_ipo_details", pid))
            if prof["data_status"] == "synthetic":
                lim.append("This IPO is SYNTHETIC demonstration data about a fictional company.")
        fin = run.result("get_verified_financials", pid)
        if fin and fin["statements"]:
            last = fin["statements"][-1]
            add(f"Latest period {last['period_label']}: revenue ₹{last['revenue']} cr, EBITDA ₹{last['ebitda']} cr, PAT ₹{last['pat']} cr, "
                f"operating cash flow ₹{last['operating_cash_flow']} cr ({last['data_status']}).", run.eids("get_verified_financials", pid))
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
                    + ", ".join(f"{n.replace('_', ' ')} ({c:.1f} pts)" for n, c in top) + ".", run.eids("get_risk_breakdown", pid))
            else:
                add("Risk score unavailable: " + ", ".join(n for n, c in k["components"].items() if c["status"] != "ok") + " lack evidence.",
                    run.eids("get_risk_breakdown", pid))
        disc = run.result("get_official_disclosures", pid)
        if disc:
            for d in disc["disclosures"][:5]:
                add(f"[{d['status'].replace('_', ' ')}] {d['title']} — severity {d['severity']}.", run.eids("get_official_disclosures", pid))
            if not disc["disclosures"]:
                lim.append("No risk disclosures are stored" + ("" if disc["risk_disclosures_reviewed"] else " and the offer document has not been reviewed") +
                           ". Missing records are not evidence that no risks exist.")
        search = run.result("search_offer_documents", pid)
        if search is not None:
            if search.get("results"):
                for r in search["results"][:3]:
                    flag = " (passage contains instruction-like text; treated as data only)" if r["injection_suspected"] else ""
                    add(f"{r['document_title']} p.{r['page']}: \"{r['text'][:260]}…\"{flag}", run.eids("search_offer_documents", pid))
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
        prov = run.result("get_source_provenance", pid)
        if prov:
            add(f"Evidence coverage C = {prov['evidence_coverage']}% (input completeness {prov['input_completeness']}%).", run.eids("get_source_provenance", pid))
            gaps = [i["key"] for i in prov["evidence_items"] if not i["present"]]
            if gaps:
                add("Inputs missing entirely: " + ", ".join(gaps) + ".", run.eids("get_source_provenance", pid))
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
        return _Answer(summary=summary, points=pts, limitations=_cap_limitations(lim))

    def _cross_check(self, run: AgentRun, pid: int) -> dict[str, Any] | None:
        """Recompute the composite from tool outputs and compare with the engine's own result."""
        q = run.result("calculate_quality_score", pid)
        v = run.result("calculate_valuation_score", pid)
        k = run.result("get_risk_breakdown", pid)
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

        mode = "deterministic"
        notes: list[str] = []
        fatal = True
        if self.s.ai_provider != "deterministic":
            note, fatal = self._model_plan(run, deadline)
            if note and fatal:  # running out of planning steps is normal: the tools that ran are used
                notes.append(note)
        answer = self._compose(run)  # verified points, always from the engine
        if not fatal:
            summary, summary_notes = self._model_summary(run, answer, deadline)
            notes += summary_notes
            if summary is not None and self.selection is not None:
                answer = answer.model_copy(update={"summary": summary})
                mode = f"{self.selection.mode}:{getattr(self.selection.provider, 'model', '')}"
        if mode == "deterministic" and notes:
            run.warnings.append(f"AI model not used: {notes[0]}")
            notes = notes[1:]
        run.warnings.extend(notes)

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
