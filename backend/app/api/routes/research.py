"""Listing calendar, data-quality exceptions and offer-document files/extractions."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, audit, require_admin
from app.core.errors import ApiError, not_found
from app.db import get_db
from app.ingestion.document_service import document_path, process
from app.models import DocumentExtraction, FieldObservation, FinancialStatement, PeerSnapshot, SourceDocument
from app.services.ipo_service import all_ipos, effective_status, include_demo_default, issue_stage

router = APIRouter(prefix="/api", tags=["research"])

EVENT_FIELDS = (("open", "Bidding opens", "open_date"), ("close", "Bidding closes", "close_date"), ("allotment", "Allotment", "allotment_date"),
                ("refund", "Refunds", "refund_date"), ("demat_credit", "Demat credit", "demat_credit_date"), ("listing", "Listing", "listing_date"))


@router.get("/calendar")
def calendar(db: Session = Depends(get_db), start: date | None = None, end: date | None = None, include_demo: bool | None = None,
             issue_type: str | None = Query(None, pattern="^(mainboard|sme)$")) -> dict[str, Any]:
    """Every dated IPO event in a window, each marked confirmed (exchange-published) or estimated."""
    today = date.today()
    start = start or today - timedelta(days=7)
    end = end or today + timedelta(days=45)
    if end < start or (end - start).days > 400:
        raise ApiError(422, "invalid_range", "end must be after start and the window at most 400 days")
    show_demo = include_demo_default(db) if include_demo is None else include_demo
    events = []
    for ipo in all_ipos(db):
        if (not show_demo and ipo.data_mode == "demo") or (issue_type and ipo.issue_type != issue_type):
            continue
        status = effective_status(ipo, today)
        for key, label, attr in EVENT_FIELDS:
            d = getattr(ipo, attr)
            if d is None or not start <= d <= end:
                continue
            if key in ("allotment", "refund", "demat_credit"):
                confirmed = False  # NSE does not publish these: derived from the SEBI T+3 timeline
            elif key == "listing":
                confirmed = ipo.listing_date_status == "actual"
            else:
                confirmed = ipo.data_mode != "demo"
            events.append({"date": d.isoformat(), "event": key, "label": label, "status": "confirmed" if confirmed else "estimated",
                           "ipo_id": ipo.id, "company_name": ipo.company.name, "issue_type": ipo.issue_type, "ipo_status": status,
                           "stage": issue_stage(ipo, status, today), "data_mode": ipo.data_mode,
                           "price_band": [ipo.price_band_low, ipo.price_band_high] if ipo.price_band_high else None})
    events.sort(key=lambda e: (e["date"], [k for k, _, _ in EVENT_FIELDS].index(e["event"]), e["company_name"]))
    return {"start": start.isoformat(), "end": end.isoformat(), "today": today.isoformat(), "events": events,
            "note": ("Opening, closing and actual listing dates are published by NSE. Allotment, refund, demat-credit and "
                     "expected listing dates are estimated from SEBI's T+3 timeline (weekends skipped, exchange holidays not applied).")}


@router.get("/data/exceptions")
def exceptions(db: Session = Depends(get_db)) -> dict[str, Any]:
    """What the pipeline could not resolve automatically: failed extractions, failed checks, conflicts."""
    names = {i.id: i.company.name for i in all_ipos(db)}
    docs = db.execute(select(SourceDocument).where(SourceDocument.source_key.in_(("nse_rhp", "sebi_rhp", "sebi_drhp")),
                                                   SourceDocument.extraction_status.in_(("failed", "not_found", "partial")))).scalars()
    doc_rows = [{"document_id": d.id, "ipo_id": d.ipo_id, "company_name": names.get(d.ipo_id or 0), "status": d.extraction_status,
                 "error": d.extraction_error, "extracted_at": d.extracted_at.isoformat() if d.extracted_at else None,
                 "archive_url": d.archive_url} for d in docs]
    review = db.execute(select(FinancialStatement).where(FinancialStatement.is_current.is_(True),
                                                         FinancialStatement.data_status == "requires_review")).scalars()
    company_ipo = {i.company_id: i for i in all_ipos(db)}
    review_rows = [{"statement_id": s.id, "ipo_id": company_ipo[s.company_id].id if s.company_id in company_ipo else None,
                    "company_name": company_ipo[s.company_id].company.name if s.company_id in company_ipo else None,
                    "period_label": s.period_label, "basis": s.basis,
                    "failed_checks": [c for c in (s.validation or []) if not c.get("passed")]} for s in review]
    conflicts = db.execute(select(FieldObservation).where(FieldObservation.conflict.is_(True)).order_by(FieldObservation.id.desc()).limit(50)).scalars()
    conflict_rows = [{"ipo_id": o.ipo_id, "company_name": names.get(o.ipo_id), "field": o.field, "value": o.value, "source_key": o.source_key,
                      "observed_at": o.observed_at.isoformat()} for o in conflicts]
    peers = db.execute(select(PeerSnapshot).where(PeerSnapshot.data_status == "requires_review")).scalars()
    peer_rows = [{"ipo_id": p.ipo_id, "company_name": names.get(p.ipo_id), "peer": p.name, "note": p.check_note, "page": p.page} for p in peers]
    pending = db.execute(select(func.count(SourceDocument.id)).where(SourceDocument.source_key.in_(("nse_rhp", "sebi_rhp", "sebi_drhp")),
                                                                     SourceDocument.extraction_status == "pending")).scalar_one()
    return {"documents": doc_rows, "statements_requiring_review": review_rows, "field_conflicts": conflict_rows,
            "peer_rows_requiring_review": peer_rows, "documents_pending": pending,
            "note": "Nothing here needs manual action for the pipeline to keep running; these items are excluded from scores until resolved."}


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, db: Session = Depends(get_db)) -> FileResponse:
    """The stored original (official offer document). Served by id only; never by a client-supplied path."""
    doc = db.get(SourceDocument, doc_id)
    if doc is None:
        raise not_found("document")
    path = document_path(doc)
    if path is None or doc.mime_type != "application/pdf":
        raise ApiError(404, "not_retained", "The original file is not stored (pruned to save space); use the source link")
    return FileResponse(path, media_type="application/pdf", filename=(doc.original_filename or f"document-{doc.id}.pdf"),
                        headers={"Content-Disposition": f'inline; filename="document-{doc.id}.pdf"', "X-Content-Type-Options": "nosniff"})


@router.get("/documents/{doc_id}/extractions")
def document_extractions(doc_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if db.get(SourceDocument, doc_id) is None:
        raise not_found("document")
    runs = db.execute(select(DocumentExtraction).where(DocumentExtraction.document_id == doc_id).order_by(DocumentExtraction.id.desc()).limit(20)).scalars()
    return {"document_id": doc_id, "runs": [{"id": r.id, "status": r.status, "parser_version": r.parser_version, "started_at": r.started_at.isoformat(),
                                             "finished_at": r.finished_at.isoformat() if r.finished_at else None, "pages_scanned": r.pages_scanned,
                                             "statements": r.statements, "checks": r.checks, "warnings": r.warnings, "error": r.error} for r in runs]}


@router.post("/admin/documents/{doc_id}/reprocess")
def reprocess(doc_id: int, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    doc = db.get(SourceDocument, doc_id)
    if doc is None:
        raise not_found("document")
    if document_path(doc) is None:
        raise ApiError(409, "not_retained", "The original is not stored; it will be downloaded again by the next documents job")
    res = process(db, doc)
    audit(db, request, "document_reprocess", ctx.user.id, document_id=doc_id, status=res.get("status"))
    return res
