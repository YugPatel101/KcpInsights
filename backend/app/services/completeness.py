"""Data completeness: which fields an IPO has, which it lacks, and why.

For every field in the registry (``services.field_registry``) the IPO gets a state — available,
estimated, unverified, requires review, unavailable, not applicable, or pending (not expected yet
at this stage of the issue) — with its value, source, reporting period, freshness and, when
missing, the reason. Group percentages and an overall analysis-readiness percentage summarise it.

Completeness measures how much of the expected information is on record. It is not a confidence
level and says nothing about the probability of any return. Missing values are never filled with
zeros, averages or estimates.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.ipo_data_service import field_provenance
from app.models import FinancialStatement, IPOIssue, SourceDocument, utcnow
from app.services.field_registry import FIELDS, GROUP_WEIGHTS, GROUPS, FieldSpec, FieldState

COUNTED_AS = {"available": 1.0, "not_meaningful": 1.0, "estimated": 0.5, "unverified": 0.5, "requires_review": 0.25, "unavailable": 0.0}
SOURCE_LABEL = {"nse_ipo": "NSE", "nse_ipo:derived": "Derived from NSE data", "nse_bhavcopy": "NSE bhavcopy", "nse_rhp": "NSE RHP",
                "nse_rhp:derived": "Derived from RHP", "sebi_rhp": "SEBI RHP", "sebi_drhp": "SEBI DRHP", "user_import": "User import",
                "demo": "Synthetic demo", "manual_verified": "Manual (verified)", "nse_equity_list": "NSE listed-equity list",
                "nse_shareholding": "NSE shareholding pattern"}
DOC_SOURCE = {"nse_rhp": "NSE RHP archive", "sebi_rhp": "SEBI red herring filing", "sebi_drhp": "SEBI draft (DRHP) filing"}


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def documents_for(db: Session, ipo_id: int) -> list[SourceDocument]:
    return list(db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo_id).order_by(SourceDocument.id)).scalars())


def sources_tried(ipo: IPOIssue, docs: list[SourceDocument]) -> list[dict[str, Any]]:
    """Every offer-document source that was looked at for this issue, and what came of it."""
    out = []
    keys = {d.source_key for d in docs}
    for d in docs:
        if d.source_key not in DOC_SOURCE:
            continue
        out.append({"source": DOC_SOURCE[d.source_key], "document_id": d.id, "status": d.extraction_status,
                    "detail": d.extraction_error, "url": d.archive_url or d.source_url})
    if "nse_rhp" not in keys and ipo.nse_symbol:
        out.append({"source": DOC_SOURCE["nse_rhp"], "status": "not_published",
                    "detail": "the NSE issue page does not link an offer document yet" if not ipo.offer_document_url
                    else "the linked file is not on an allowlisted official host"})
    if ipo.issue_type != "sme" and "sebi_rhp" not in keys and "sebi_drhp" not in keys:
        out.append({"source": "SEBI offer-document filings", "status": "no_match",
                    "detail": "no matching filing among the recent SEBI listings (polled twice a day)"})
    if ipo.issue_type == "sme" and "nse_rhp" not in keys:
        out.append({"source": "SEBI offer-document filings", "status": "not_applicable",
                    "detail": "SME offer documents are filed with the exchange, not SEBI"})
    return out


def _financial_gap_reason(docs: list[SourceDocument], stmts: list[FinancialStatement], usable: set[str]) -> str:
    annual = [s for s in stmts if s.period_months == 12]
    if annual and not any(s.data_status in usable for s in annual):
        if any(s.data_status == "requires_review" for s in annual):
            return "figures were read from the offer document but failed accounting checks (see the data-pipeline exceptions)"
        return "figures were read but no accounting check confirmed them, so they are shown and not used"
    readable = [d for d in docs if d.source_key in DOC_SOURCE and d.extraction_status not in ("duplicate", "skipped")]
    if not readable:
        return "no offer document has been found yet (NSE issue page and SEBI filings checked)"
    st = {d.extraction_status for d in readable}
    if "pending" in st:
        return "the offer document is queued for download and extraction"
    failed = [d for d in readable if d.extraction_status == "failed"]
    if failed and not st & {"extracted", "partial"}:
        d = failed[-1]
        when = f"; next attempt after {d.next_attempt_at:%d %b %H:%M} UTC" if d.next_attempt_at else f"; gave up after {d.attempts} attempts"
        return f"processing failed ({(d.extraction_error or 'unknown error')[:140]}){when}"
    nf = [d for d in readable if d.extraction_status == "not_found"]
    if nf and not st & {"extracted", "partial"}:
        return f"the statements could not be read from the offer document ({(nf[-1].extraction_error or '')[:160]})"
    return "this line is not reported separately in the extracted statements"


def _latest_annual(stmts: list[FinancialStatement], result: dict[str, Any]) -> FinancialStatement | None:
    annual = [s for s in stmts if s.period_months == 12]
    if not annual:
        return None
    basis, label = result.get("basis"), result.get("latest_period")
    for s in sorted(annual, key=lambda s: s.period_end, reverse=True):
        if s.basis == basis and s.period_label == label:
            return s
    return max(annual, key=lambda s: s.period_end)


def compute_completeness(db: Session, ipo: IPOIssue, result: dict[str, Any], cfg: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    from app.services.ipo_service import current_statements, effective_status, issue_stage, latest_subscription

    today = today or date.today()
    status = effective_status(ipo, today)
    stage = issue_stage(ipo, status, today)
    prov = field_provenance(db, ipo.id)
    docs = documents_for(db, ipo.id)
    stmts = current_statements(db, ipo.company_id)
    usable = set(cfg["usable_statuses"])
    latest = _latest_annual(stmts, result)
    fin_reason = _financial_gap_reason(docs, stmts, usable)
    demo = ipo.data_mode == "demo"
    # until an offer document has been read, every document-sourced gap has the same, more useful reason
    doc_read = any(d.extraction_status in ("extracted", "partial", "not_found") for d in docs if d.source_key in DOC_SOURCE)
    doc_reason = None if doc_read or demo or ipo.data_mode == "imported" else fin_reason
    metrics = result.get("metrics") or {}
    facts = ipo.document_facts or {}
    now = utcnow()

    def pending(spec: FieldSpec) -> FieldState | None:
        if spec.stages and stage not in spec.stages and not (stage == "closed" and "listed" in spec.stages and status == "listed"):
            why = {"pipeline": "not announced yet: only an offer document has been filed",
                   "upcoming": "expected once bidding opens or the issue is priced"}.get(stage, "not expected at this stage of the issue")
            return FieldState(spec.key, spec.label, spec.group, "pending", unit=spec.unit, reason=why)
        return None

    def from_obs(spec: FieldSpec, value: Any, obs_key: str | None = None) -> FieldState:
        o = prov.get(obs_key or spec.key)
        if value is None or value == "":
            from_document = spec.primary.startswith(("Offer document", "Derived: pre-issue"))
            return FieldState(spec.key, spec.label, spec.group, "unavailable", unit=spec.unit,
                              reason=(doc_reason if from_document and doc_reason else
                                      f"not published by {spec.primary}" + (f"; fallback: {spec.fallback}" if spec.fallback else "")))
        st = (o or {}).get("data_status") or ("synthetic" if demo else ipo.data_status)
        stale = bool(o and spec.stale_after_hours and status in ("upcoming", "open")
                     and now - datetime.fromisoformat(o["last_verified_at"]) > timedelta(hours=spec.stale_after_hours))
        return FieldState(spec.key, spec.label, spec.group, "estimated" if st == "estimated" else "available", value=_iso(value), unit=spec.unit,
                          source=SOURCE_LABEL.get((o or {}).get("source_key", ""), (o or {}).get("source_key")) or ("Synthetic demo" if demo else "Import"),
                          as_of=(o or {}).get("last_verified_at"), data_status=st, stale=stale,
                          reason=(o or {}).get("basis") if st == "estimated" else None,
                          extra={"conflicts": o.get("conflicts", 0)} if o and o.get("conflicts") else {})

    states: list[FieldState] = []
    for spec in FIELDS:
        p = pending(spec)
        if p is not None:
            states.append(p)
            continue
        k = spec.key
        if spec.group == "issue":
            if k == "price_band":
                v = f"{ipo.price_band_low:g}–{ipo.price_band_high:g}" if ipo.price_band_low and ipo.price_band_high else None
                states.append(from_obs(spec, v, "price_band_high"))
            elif k == "subscription":
                sub = latest_subscription(ipo)
                if sub is None:
                    states.append(FieldState(k, spec.label, "issue", "unavailable", unit=spec.unit,
                                             reason="NSE published no consolidated bid figures for this issue"
                                             + (" (subscription is collected only while bidding is open)" if status != "open" else "")))
                else:
                    states.append(FieldState(k, spec.label, "issue", "available", value=sub.get("total"), unit="times", source="NSE",
                                             as_of=sub.get("as_of"), data_status=",".join(sub.get("data_status") or []) or None))
            elif k == "offer_document":
                good = [d for d in docs if d.source_key in DOC_SOURCE and d.extraction_status != "duplicate"]
                if good:
                    d = good[-1]
                    states.append(FieldState(k, spec.label, "issue", "available", value=d.title, source=DOC_SOURCE[d.source_key or ""],
                                             as_of=_iso(d.retrieved_at) if d.sha256 else None, data_status=d.extraction_status,
                                             extra={"document_id": d.id, "url": d.archive_url or d.source_url}))
                elif ipo.offer_document_url:
                    states.append(FieldState(k, spec.label, "issue", "available", value=ipo.offer_document_url, source="NSE issue page",
                                             reason="linked; not on an allowlisted host for automatic download"))
                else:
                    states.append(FieldState(k, spec.label, "issue", "unavailable", reason="no offer document linked by NSE and no SEBI filing matched"))
            elif k == "sector":
                c = ipo.company.classification or {}
                if ipo.company.sector and ipo.company.sector != "Unclassified":
                    states.append(FieldState(k, spec.label, "issue", "available", value=ipo.company.sector,
                                             source="Offer document (classifier)" if c.get("method") else ("Synthetic demo" if demo else "Import"),
                                             data_status=c.get("status") or ipo.company.data_status,
                                             extra={"profile": ipo.company.industry_profile or "general"}))
                else:
                    states.append(FieldState(k, spec.label, "issue", "unavailable",
                                             reason=c.get("note") or doc_reason or "NSE publishes no sector; the offer document has not been classified yet"))
            elif k == "listing_price":
                states.append(from_obs(spec, ipo.listing_price))
            elif k in ("promoters", "objects_of_issue"):
                f = facts.get(k) or {}
                items: list[Any] | None = f.get("value") if k == "promoters" else (f.get("value") or ipo.use_of_proceeds)
                ok = items is not None and (items != [] or k == "promoters")
                shown = (", ".join(items or []) or "no identifiable promoter") if k == "promoters" else len(items or [])
                states.append(FieldState(k, spec.label, "issue", "available" if ok else "unavailable", value=shown if ok else None,
                                         unit="objects" if k == "objects_of_issue" and ok else None,
                                         source=f"Offer document p{f['page']}" if ok and f.get("page") else ("Import" if ok else None),
                                         reason=None if ok else (doc_reason or "not found in a readable form in the offer document")))
            elif k == "business_overview":
                bo = facts.get("business_overview") or {}
                text = bo.get("value") or ipo.company.description
                states.append(FieldState(k, spec.label, "issue", "available" if text else "unavailable", value=(text or "")[:80] + "…" if text else None,
                                         source=f"Offer document p{bo['page']}" if bo else ("Import" if text else None),
                                         reason=None if text else (doc_reason or "the offer document's 'Our Business' overview could not be located automatically")))
            else:
                states.append(from_obs(spec, getattr(ipo, k, None)))
        elif spec.group == "financials":
            if k == "annual_periods":
                n = len(result.get("periods_used") or [])
                st = "available" if n >= 3 else ("estimated" if n == 2 else "unavailable")
                states.append(FieldState(k, spec.label, "financials", "available" if n >= 3 else ("unverified" if n == 2 else "unavailable"),
                                         value=n, unit="periods", source=spec.primary if n else None,
                                         reason=None if st == "available" else (f"only {n} usable annual period(s)" if n else fin_reason)))
                continue
            v = getattr(latest, spec.statement_field or k) if latest is not None else None
            if v is None or latest is None:
                states.append(FieldState(k, spec.label, "financials", "unavailable", unit=spec.unit,
                                         reason=fin_reason if latest is None or latest.data_status not in usable
                                         else "this line is not reported separately in the extracted statements"))
                continue
            ds = latest.data_status
            fs = "available" if ds in usable else ("requires_review" if ds == "requires_review" else "unverified")
            states.append(FieldState(k, spec.label, "financials", fs, value=round(v, 2), unit=spec.unit,
                                     source=(latest.source_record.title if latest.source_record else spec.primary), period=latest.period_label,
                                     as_of=_iso(latest.created_at), data_status=ds,
                                     extra={"statement_id": latest.id, "basis": latest.basis, "document_id": latest.document_id}))
        elif spec.group in ("ratios", "valuation") and spec.metric:
            mt = metrics.get(spec.metric)
            if mt is None:
                states.append(FieldState(k, spec.label, spec.group, "unavailable", unit=spec.unit,
                                         reason=fin_reason if not result.get("periods_used") else "inputs unavailable"))
                continue
            stt = mt.get("status")
            if stt == "ok":
                fs = "estimated" if spec.group == "valuation" and (result.get("price") or {}).get("price_status") == "estimated" else "available"
                states.append(FieldState(k, spec.label, spec.group, fs, value=mt.get("value"), unit=mt.get("unit"), source="Quant engine",
                                         period=mt.get("period"), data_status=fs, reason=mt.get("note")))
            elif stt == "not_applicable":
                states.append(FieldState(k, spec.label, spec.group, "not_applicable", unit=mt.get("unit"), reason=mt.get("reason")))
            elif stt == "not_meaningful":
                states.append(FieldState(k, spec.label, spec.group, "not_meaningful", unit=mt.get("unit"), period=mt.get("period"), reason=mt.get("reason")))
            else:
                states.append(FieldState(k, spec.label, spec.group, "unavailable", unit=mt.get("unit"),
                                         reason=mt.get("reason") if result.get("periods_used") else fin_reason))
        elif k == "peer_median_pe":
            pr = result.get("peers") or {}
            if pr.get("median_pe") is not None:
                states.append(FieldState(k, spec.label, "valuation", "available", value=pr["median_pe"], unit="x",
                                         source="Offer document — listed peers", period=", ".join(pr.get("periods") or []) or None,
                                         extra={"peers": pr.get("with_pe")}))
            else:
                states.append(FieldState(k, spec.label, "valuation", "unavailable", unit="x",
                                         reason=doc_reason or pr.get("note") or ("no listed-peer table read from the offer document" if not ipo.peers
                                                                                 else "insufficient comparable companies")))
        elif spec.group == "risk":
            if k == "customer_concentration":
                cc = ipo.company.customer_concentration_pct
                states.append(FieldState(k, spec.label, "risk", "available" if cc is not None else "unavailable", value=cc, unit="%",
                                         source=spec.primary if cc is not None else None, period=ipo.company.customer_concentration_basis,
                                         reason=None if cc is not None else (doc_reason or "no top-customer share found in the offer document's risk factors")))
            elif k in ("contingent_liabilities", "auditor_qualifications"):
                f = facts.get("contingent_liabilities_cr" if k == "contingent_liabilities" else k) or {}
                ok = f.get("value") is not None
                states.append(FieldState(k, spec.label, "risk", "available" if ok else "unavailable", value=f.get("value"), unit=spec.unit,
                                         source=f"Offer document p{f.get('page')}" if ok else None, period=f.get("basis"),
                                         reason=None if ok else (doc_reason or "not found in a readable form in the offer document")))
            elif k == "promoter_holding":
                post = ipo.promoter_holding_post_pct is not None
                ph = ipo.promoter_holding_post_pct if post else ipo.promoter_holding_pre_pct
                o = prov.get("promoter_holding_post_pct" if post else "promoter_holding_pre_pct") or {}
                states.append(FieldState(k, spec.label, "risk", ("estimated" if o.get("data_status") == "estimated" else "available") if ph is not None
                                         else "unavailable", value=ph, unit="%", period="after the issue" if post else "before the issue" if ph is not None else None,
                                         source=SOURCE_LABEL.get(o.get("source_key", ""), o.get("source_key")) if ph is not None else None,
                                         data_status=o.get("data_status"),
                                         reason=None if ph is not None else (doc_reason or "no shareholding pattern found in a readable form in the offer "
                                                                             "document; after listing it comes from the pattern filed with NSE")))
            else:
                states.append(FieldState(k, spec.label, "risk", "unavailable", reason=spec.fallback))
        elif spec.group == "verification":
            if k == "statements_verified":
                annual = [s for s in stmts if s.period_months == 12]
                ver = [s for s in annual if s.data_status in ("verified", "synthetic", "imported")]
                if not annual:
                    states.append(FieldState(k, spec.label, "verification", "unavailable", reason=fin_reason))
                else:
                    fs = "available" if len(ver) == len(annual) else ("requires_review" if any(s.data_status == "requires_review" for s in annual)
                                                                      else "unverified")
                    states.append(FieldState(k, spec.label, "verification", fs, value=f"{len(ver)}/{len(annual)} annual periods",
                                             source="Accounting checks"))
            elif k == "issue_data_official":
                official = [o for o in prov.values() if (o.get("source_key") or "").split(":")[0] in ("nse_ipo", "nse_bhavcopy", "nse_rhp", "sebi_rhp")]
                conflicts = sum(o.get("conflicts", 0) for o in prov.values())
                if demo:
                    states.append(FieldState(k, spec.label, "verification", "unavailable", reason="synthetic demonstration record"))
                elif official:
                    states.append(FieldState(k, spec.label, "verification", "available", value=f"{len(official)} fields from official sources",
                                             source="NSE / offer document", extra={"conflicts": conflicts}))
                else:
                    states.append(FieldState(k, spec.label, "verification", "unavailable", reason="no field confirmed by an official source"))
            elif k == "document_hash":
                hashed = [d for d in docs if d.sha256]
                states.append(FieldState(k, spec.label, "verification", "available" if hashed else "unavailable",
                                         value=hashed[-1].sha256[:16] + "…" if hashed else None,
                                         reason=None if hashed else "no offer document downloaded yet"))

    groups = []
    overall_num = overall_den = 0.0
    for g, label in GROUPS.items():
        rows = [s for s in states if s.group == g]
        counted = [s for s in rows if s.status in COUNTED_AS]
        pct = sum(COUNTED_AS[s.status] for s in counted) / len(counted) * 100 if counted else None
        groups.append({"key": g, "label": label, "pct": round(pct, 1) if pct is not None else None,
                       "available": sum(1 for s in rows if s.status in ("available", "not_meaningful")),
                       "partial": sum(1 for s in rows if s.status in ("estimated", "unverified", "requires_review")),
                       "missing": sum(1 for s in rows if s.status == "unavailable"),
                       "not_applicable": sum(1 for s in rows if s.status == "not_applicable"),
                       "pending": sum(1 for s in rows if s.status == "pending"),
                       "fields": [s.as_dict() for s in rows]})
        if pct is not None:
            overall_num += GROUP_WEIGHTS[g] * pct
            overall_den += GROUP_WEIGHTS[g]
    overall = round(overall_num / overall_den, 1) if overall_den else 0.0
    rs = result.get("status")
    readiness = ({"level": "ready", "label": "Analysis ready", "reason": "every applicable score component is computable"} if rs == "complete" else
                 {"level": "partial", "label": "Partially ready", "reason": (result.get("fundamental") or {}).get("note")} if rs == "partial" else
                 {"level": "insufficient", "label": "Insufficient data", "reason": (result.get("fundamental") or {}).get("reason") or fin_reason})
    return {"ipo_id": ipo.id, "stage": stage, "overall_pct": overall, "readiness": readiness, "groups": groups,
            "pipeline": pipeline_stages(ipo, docs, stmts, result, usable), "sources_tried": sources_tried(ipo, docs),
            "missing_important": [s.as_dict() for s in states if s.status == "unavailable" and s.group in ("financials", "valuation")][:12],
            "computed_at": now.isoformat(), "note": "Completeness measures how much expected information is on record; it is not a confidence level."}


def pipeline_stages(ipo: IPOIssue, docs: list[SourceDocument], stmts: list[FinancialStatement], result: dict[str, Any], usable: set[str]) -> list[dict[str, Any]]:
    """Where this IPO stands in Discovery → Document → Extraction → Validation → Calculation → Scoring."""
    offer = [d for d in docs if d.source_key in DOC_SOURCE]
    out: list[dict[str, Any]] = [{"stage": "discovered", "label": "Discovered", "status": "done",
            "detail": "NSE public issues" if ipo.nse_symbol else ("SEBI filing" if any(d.source_key in ("sebi_rhp", "sebi_drhp") for d in offer)
                                                                 else ("synthetic demo" if ipo.data_mode == "demo" else "user import"))}]
    if offer or ipo.offer_document_url:
        found = ", ".join(sorted({DOC_SOURCE[d.source_key or ""] for d in offer})) or "NSE link"
        out.append({"stage": "located", "label": "Offer document located", "status": "done", "detail": found})
    else:
        out.append({"stage": "located", "label": "Offer document located", "status": "pending", "detail": "not published yet"})
    if any(d.sha256 for d in offer):
        out.append({"stage": "downloaded", "label": "Downloaded & hashed", "status": "done", "detail": f"{sum(1 for d in offer if d.sha256)} file(s)"})
    elif any(d.extraction_status == "failed" for d in offer):
        out.append({"stage": "downloaded", "label": "Downloaded & hashed", "status": "failed", "detail": next((d.extraction_error for d in offer if d.extraction_error), None)})
    else:
        out.append({"stage": "downloaded", "label": "Downloaded & hashed", "status": "pending", "detail": "queued" if offer else None})
    ext = [d for d in offer if d.extraction_status in ("extracted", "partial")]
    if ext:
        out.append({"stage": "extracted", "label": "Statements extracted", "status": "done",
                    "detail": f"{ext[-1].extraction_status} (parser {ext[-1].parser_version}, {ext[-1].extraction_method or 'text'})"})
    elif any(d.extraction_status in ("not_found", "failed") for d in offer):
        out.append({"stage": "extracted", "label": "Statements extracted", "status": "failed",
                    "detail": next((d.extraction_error for d in reversed(offer) if d.extraction_error), None)})
    else:
        out.append({"stage": "extracted", "label": "Statements extracted", "status": "pending", "detail": None})
    annual = [s for s in stmts if s.period_months == 12]
    if any(s.data_status in usable for s in annual):
        out.append({"stage": "validated", "label": "Accounting checks", "status": "done",
                    "detail": f"{sum(1 for s in annual if s.data_status in usable)}/{len(annual)} annual periods usable"})
    elif annual:
        out.append({"stage": "validated", "label": "Accounting checks", "status": "failed", "detail": "no annual period passed the checks"})
    else:
        out.append({"stage": "validated", "label": "Accounting checks", "status": "pending", "detail": None})
    out.append({"stage": "calculated", "label": "Ratios calculated", "status": "done" if result.get("periods_used") else "pending",
                "detail": f"{len(result.get('periods_used') or [])} periods, {result.get('basis') or '—'} basis" if result.get("periods_used") else None})
    q = result.get("composite")
    out.append({"stage": "scored", "label": "Scored", "status": "done" if q is not None else ("failed" if result.get("periods_used") else "pending"),
                "detail": f"Q {q:g} ({result.get('status')})" if q is not None else (result.get("fundamental") or {}).get("reason")})
    return out


def summary_of(c: dict[str, Any]) -> dict[str, Any]:
    """Compact form cached on the IPO row (lists, dashboard)."""
    return {"overall_pct": c["overall_pct"], "readiness": c["readiness"]["level"], "readiness_label": c["readiness"]["label"],
            "groups": {g["key"]: g["pct"] for g in c["groups"]}, "missing": [f["label"] for f in c["missing_important"]][:6],
            "pipeline": {p["stage"]: p["status"] for p in c["pipeline"]}}


def refresh_completeness(db: Session, ipo: IPOIssue, result: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Recompute and cache; the row is written only when the summary changed (reads stay idempotent)."""
    c = compute_completeness(db, ipo, result, cfg)
    summary = summary_of(c)
    if ipo.completeness_pct != c["overall_pct"] or ipo.completeness_summary != summary:
        ipo.completeness_pct = c["overall_pct"]
        ipo.completeness_summary = summary
        ipo.completeness_at = utcnow()
    return c
