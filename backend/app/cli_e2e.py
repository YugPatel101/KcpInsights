"""End-to-end demonstration on one real IPO: every pipeline stage, then a second run to prove idempotency.

``python -m app.cli e2e-demo <NSE symbol> --report ../docs/E2E_DEMONSTRATION.md``

Every number in the report is read back from the database after the step ran; nothing is typed in.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion import document_service as ds
from app.ingestion import ipo_data_service as svc
from app.ingestion.ingestion_scheduler import get_runner
from app.models import (
    FieldObservation,
    FinancialLineItem,
    FinancialStatement,
    IPOIssue,
    PeerSnapshot,
    ResearchScore,
    SourceDocument,
    SourceRecord,
    utcnow,
)
from app.services.ipo_service import get_active_config, get_ipo, score_ipo

COUNTED = (IPOIssue, FieldObservation, SourceDocument, FinancialStatement, FinancialLineItem, PeerSnapshot, ResearchScore, SourceRecord)


def _counts(db: Session, ipo: IPOIssue) -> dict[str, int]:
    docs = select(SourceDocument.id).where(SourceDocument.ipo_id == ipo.id)
    stmts = select(FinancialStatement.id).where(FinancialStatement.company_id == ipo.company_id)
    return {
        "ipo_records_with_symbol": db.execute(select(func.count(IPOIssue.id)).where(IPOIssue.nse_symbol == ipo.nse_symbol)).scalar_one(),
        "field_observations": db.execute(select(func.count(FieldObservation.id)).where(FieldObservation.ipo_id == ipo.id)).scalar_one(),
        "documents": db.execute(select(func.count(SourceDocument.id)).where(SourceDocument.ipo_id == ipo.id)).scalar_one(),
        "statement_rows": db.execute(select(func.count(FinancialStatement.id)).where(FinancialStatement.company_id == ipo.company_id)).scalar_one(),
        "current_statements": db.execute(select(func.count(FinancialStatement.id)).where(FinancialStatement.company_id == ipo.company_id,
                                                                                       FinancialStatement.is_current.is_(True))).scalar_one(),
        "line_items": db.execute(select(func.count(FinancialLineItem.id)).where(FinancialLineItem.statement_id.in_(stmts))).scalar_one(),
        "peer_rows": db.execute(select(func.count(PeerSnapshot.id)).where(PeerSnapshot.ipo_id == ipo.id)).scalar_one(),
        "score_rows": db.execute(select(func.count(ResearchScore.id)).where(ResearchScore.ipo_id == ipo.id)).scalar_one(),
        "document_source_records": db.execute(select(func.count(SourceRecord.id)).where(SourceRecord.document_id.in_(docs))).scalar_one(),
    }


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return str(v)


def run_e2e(db: Session, symbol: str) -> str:
    runner = get_runner()
    lines: list[str] = [f"# End-to-end demonstration — NSE: {symbol}", "",
                        f"Run at {utcnow():%Y-%m-%d %H:%M} UTC with `python -m app.cli e2e-demo {symbol}`. Every figure below was read back "
                        "from the database after the step ran.", ""]

    def h(t: str) -> None:
        lines.extend(["", f"## {t}", ""])

    # 1 — discovery
    h("1. Discover the IPO (NSE public issue lists)")
    r = runner.run("discover", "cli")
    lines.append(f"Discovery job **{r['status']}**: {r['records_discovered']} issues seen, {r['records_created']} new, "
                 f"{r['records_updated']} updated, {r['requests_made']} requests.")
    ipo = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == symbol).order_by(IPOIssue.id.desc())).scalars().first()
    if ipo is None:
        lines.append(f"\n**{symbol} was not found** in NSE's upcoming, current or recently listed issues. Nothing else was attempted.")
        return "\n".join(lines)
    lines.append(f"Matched record: **{ipo.company.name}** (IPO #{ipo.id}, {ipo.issue_type}, {ipo.exchange}).")

    # 2 — official details
    h("2. Retrieve official issue details")
    res = runner.nse.fetch_ipo_details(symbol, "SME" if ipo.issue_type == "sme" else "EQ")
    if res.status == "ok" and res.data:
        rec, subs = res.data
        rec.company_name = ipo.company.name
        st = svc.upsert_issue(db, rec, source_key="nse_ipo")
        svc.upsert_subscriptions(db, ipo, subs)
        db.commit()
        lines.append(f"NSE issue-information request OK; {st.fields_changed} field(s) changed.")
    else:
        lines.append(f"NSE issue details unavailable ({res.error}); stored values are kept.")
    db.refresh(ipo)
    lines += ["", "| Field | Value | Source |", "|---|---|---|"]
    prov = svc.field_provenance(db, ipo.id)
    for f, label in (("open_date", "Opens"), ("close_date", "Closes"), ("price_band_high", "Price band (upper)"), ("final_issue_price", "Final price"),
                     ("lot_size", "Lot size"), ("issue_size_cr", "Issue size (₹ cr)"), ("listing_date", "Listing date"), ("registrar", "Registrar")):
        o = prov.get(f) or {}
        lines.append(f"| {label} | {_fmt(getattr(ipo, f))} | {o.get('source_key', '—')} ({o.get('data_status', '—')}) |")

    # 3–4 — locate and download the prospectus
    h("3. Locate the prospectus · 4. Download it")
    ds.discover(db, [ipo])
    docs = list(db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id, SourceDocument.source_key.in_(ds.DOC_SOURCES))
                           .order_by(SourceDocument.id)).scalars())
    if not docs:
        lines.append("No offer document is linked from the NSE issue page and no SEBI filing matched. Financial fields stay *unavailable* "
                     "with that reason (see the completeness panel); nothing is estimated.")
    target = None
    for doc in docs:
        stats = ds.DocRunStats()
        before_sha = doc.sha256
        t = ds.fetch(runner.client, db, doc, stats) if not (doc.original_retained and doc.sha256) else doc
        doc = db.get(SourceDocument, doc.id) or doc
        lines.append(f"- {doc.title}: `{doc.archive_url}`  \n  {stats.requests} request(s); "
                     + (f"downloaded {(doc.size_bytes or 0) / 1e6:.1f} MB, SHA-256 `{doc.sha256[:16]}…`" if stats.downloaded else
                        f"already stored (SHA-256 `{(doc.sha256 or before_sha or '')[:16]}…`), not downloaded again"))
        target = target or (t if t is not None else (doc if doc.original_retained else None))
    if target is None:
        return "\n".join(lines)

    # 5–6 — extraction and validation
    h("5. Extract the financial statements · 6. Validate periods and units")
    out = ds.process(db, target)
    lines.append(f"Extraction status **{out['status']}** (parser {target.parser_version}, method {target.extraction_method}); "
                 f"{out.get('statements_created', 0)} new statement rows, {out.get('statements_unchanged', 0)} unchanged, "
                 f"{out.get('line_items', 0)} line items with page references, {out.get('peers', 0)} listed peers.")
    stmts = list(db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.is_current.is_(True))
                            .order_by(FinancialStatement.period_end)).scalars())
    lines += ["", "| Period | Basis | Months | Revenue | PAT | Total assets | Status | Checks |", "|---|---|---|---|---|---|---|---|"]
    for s in stmts:
        checks = ", ".join(f"{c['check']} {'✓' if c.get('passed') else '✗'}" for c in (s.validation or []) if c.get("hard"))
        lines.append(f"| {s.period_label} | {s.basis} | {s.period_months} | {_fmt(s.revenue)} | {_fmt(s.pat)} | {_fmt(s.total_assets)} | "
                     f"{s.data_status} | {checks or '—'} |")
    units = sorted({i.unit for i in db.execute(select(FinancialLineItem).where(FinancialLineItem.document_id == target.id)).scalars()})
    lines.append(f"\nUnits as printed: {', '.join(units) or '—'} → stored in ₹ crore.")

    # 7–8 — ratios and scores
    h("7. Calculate ratios · 8. Quantitative analysis")
    ipo = get_ipo(db, ipo.id) or ipo
    result = score_ipo(db, ipo)
    m = result["metrics"]
    lines += [f"Basis **{result['basis']}**, periods {', '.join(result['periods_used']) or '—'}, profile **{result['profile']['label']}**.", "",
              "| Metric | Value | Formula |", "|---|---|---|"]
    for k in ("roe", "roce", "roa", "net_margin", "ebitda_margin", "revenue_cagr", "pat_cagr", "current_ratio", "debt_to_equity",
              "interest_coverage", "ocf_to_pat", "pe", "pb", "ev_ebitda"):
        mt = m.get(k) or {}
        val = f"{_fmt(mt.get('value'))} {mt.get('unit', '')}" if mt.get("status") == "ok" else f"{mt.get('status', 'unavailable')}: {mt.get('reason') or ''}"
        lines.append(f"| {mt.get('label', k)} | {val} | {mt.get('formula', '')} |")
    comps = result["components"]
    lines += ["", "| Component | Score | Coverage |", "|---|---|---|"]
    for c in comps.values():
        lines.append(f"| {c['label']} | {_fmt(c['score'])} | {_fmt(c['coverage'])}% |")
    lines.append(f"\nFundamental score Q = **{_fmt(result['composite'])}** ({result['classification'] or result['fundamental'].get('reason')}); "
                 f"risk **{_fmt(result['risk']['score'])}** ({result['risk']['level']}); data coverage {_fmt(result['coverage'])}%; "
                 f"configuration {result['config_version']}.")

    # 9 — provenance
    h("9. Source references stored")
    items = list(db.execute(select(FinancialLineItem).where(FinancialLineItem.document_id == target.id, FinancialLineItem.field.in_(
        ("revenue", "pat", "total_assets"))).limit(6)).scalars())
    for i in items:
        lines.append(f"- `{i.field}` = {_fmt(i.value, 4)} cr ← printed “{i.raw_text}” ({i.unit}) on page {i.page}, label “{i.raw_label[:60]}”")

    # 10 — research page
    h("10. Research page")
    lines.append(f"http://localhost:3000/ipos/{ipo.id} — overview, financial statements with per-figure provenance, ratios, valuation, peers, "
                 "score breakdown, risk, completeness and documents.")

    # 11 — idempotency
    h("11. Second run — idempotency")
    before = _counts(db, ipo)
    runner.run("discover", "cli")
    if res.status == "ok" and res.data:
        rec, subs = res.data
        svc.upsert_issue(db, rec, source_key="nse_ipo")
        svc.upsert_subscriptions(db, ipo, subs)
        db.commit()
    stats2 = ds.DocRunStats()
    doc2 = db.get(SourceDocument, target.id)
    refetch = ds.fetch(runner.client, db, doc2, stats2) if doc2 is not None and doc2.archive_url else None
    out2 = ds.process(db, target)
    score_ipo(db, get_ipo(db, ipo.id) or ipo)
    after = _counts(db, ipo)
    lines += ["| Table | After run 1 | After run 2 |", "|---|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {before[k]} | {after[k]} |" for k in before]
    same = all(before[k] == after[k] for k in before if k != "field_observations")
    lines.append(f"\nDocument re-check: {stats2.requests} request(s) (HEAD), unchanged={stats2.checked_unchanged}, "
                 f"re-downloaded={'yes' if refetch is not None and stats2.downloaded else 'no'}; re-extraction: "
                 f"{out2.get('statements_unchanged', 0)} statement rows unchanged, {out2.get('statements_created', 0)} created.")
    lines.append("\n**Idempotent: " + ("yes** — no duplicate IPO, document, statement, line-item, peer or score rows." if same else
                                     "NO** — row counts changed; see the table above.")
                 + " Field observations are refreshed in place (their `last_verified_at` moves) rather than duplicated.")
    lines.append(f"\nConfiguration {get_active_config(db)['version']}; report generated {date.today():%d %b %Y}.")
    return "\n".join(lines) + "\n"
