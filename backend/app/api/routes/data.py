"""Imports (Mode B), documents/RAG, official source fetching (Mode C) and scoring config."""
from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, audit, require_admin, require_user
from app.config import get_settings
from app.core.errors import ApiError, not_found
from app.core.rate_limit import limiter
from app.db import get_db
from app.models import ImportedDataset, IngestionLog, ScoringConfigVersion, SourceDocument
from app.services import rag
from app.services.import_service import (
    FINANCIALS_CSV_TEMPLATE,
    commit_bundle,
    commit_financial_rows,
    parse_financials_csv,
    validate_bundle,
)
from app.services.ipo_service import get_active_config_row, get_ipo
from app.services.scoring_config import ConfigError, get_default_config, validate_config
from app.services.source_adapters import SourceFetchError, ingest_official_url

router = APIRouter(prefix="/api", tags=["data"])

DOC_TYPES = Literal["drhp", "rhp", "prospectus", "annual_report", "disclosure", "other"]


async def _read_limited(f: UploadFile, allowed_ext: tuple[str, ...]) -> bytes:
    s = get_settings()
    name = (f.filename or "").lower()
    if not name.endswith(allowed_ext):
        raise ApiError(415, "unsupported_file", f"allowed file types: {', '.join(allowed_ext)}")
    limit = s.max_upload_mb * 1024 * 1024
    data = await f.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "file_too_large", f"maximum upload size is {s.max_upload_mb} MB")
    if not data:
        raise ApiError(422, "empty_file", "file is empty")
    return data


# ---------------------------------------------------------------------------- imports
@router.post("/imports/financials")
async def import_financials(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_user),
) -> dict[str, Any]:
    """Import financial statements (CSV) or a full research bundle (JSON). ``dry_run`` validates only."""
    limiter.hit("import", str(ctx.user.id))
    data = await _read_limited(file, (".csv", ".json"))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(422, "encoding", "file must be UTF-8 encoded") from exc
    fname = file.filename or "upload"
    if fname.lower().endswith(".json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(422, "invalid_json", f"invalid JSON: {exc.msg} at line {exc.lineno}") from exc
        bundle, rep = validate_bundle(payload)
        if dry_run or bundle is None or rep.errors:
            return {"kind": "bundle_json", "dry_run": True, "committed": False, "report": rep.as_dict(),
                    "preview": {"ipos": [i.company.name for i in bundle.ipos]} if bundle else None}
        res = commit_bundle(db, bundle, rep, user_id=ctx.user.id, is_admin=ctx.user.is_admin, filename=fname)
        audit(db, request, "import_bundle", ctx.user.id, dataset_id=res["dataset_id"], counts=res["counts"])
        return {"kind": "bundle_json", "dry_run": False, "committed": True, **res}
    rows, rep = parse_financials_csv(db, text)
    if dry_run or rep.errors:
        return {"kind": "financials_csv", "dry_run": True, "committed": False, "report": rep.as_dict(),
                "preview": {"rows": [{k: (str(v) if k == "period_end" else v) for k, v in r.items() if k != "raw"} for r in rows[:50]], "row_count": len(rows)}}
    res = commit_financial_rows(db, rows, rep, user_id=ctx.user.id, is_admin=ctx.user.is_admin, filename=fname)
    audit(db, request, "import_financials", ctx.user.id, dataset_id=res["dataset_id"], counts=res["counts"])
    return {"kind": "financials_csv", "dry_run": False, "committed": True, **res}


@router.get("/imports")
def list_imports(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_user)) -> list[dict[str, Any]]:
    q = select(ImportedDataset).order_by(ImportedDataset.created_at.desc()).limit(100)
    if not ctx.user.is_admin:
        q = q.where(ImportedDataset.user_id == ctx.user.id)
    out = []
    for d in db.execute(q).scalars():
        logs = db.execute(select(IngestionLog).where(IngestionLog.dataset_id == d.id).limit(20)).scalars()
        out.append({"id": d.id, "filename": d.filename, "kind": d.kind, "status": d.status, "record_counts": d.record_counts,
                    "warnings": len(d.validation_report.get("warnings", [])), "created_at": d.created_at.isoformat(),
                    "log_sample": [lg.message for lg in logs]})
    return out


@router.get("/imports/templates/{kind}", response_class=PlainTextResponse)
def import_template(kind: Literal["financials_csv", "bundle_json"]) -> PlainTextResponse:
    if kind == "financials_csv":
        return PlainTextResponse(FINANCIALS_CSV_TEMPLATE, media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="kcp_financials_template.csv"'})
    example = {
        "dataset_label": "My research bundle",
        "sources": [{"key": "rhp", "title": "Red Herring Prospectus (Company X), restated financials", "source_type": "document",
                     "url": "https://www.sebi.gov.in/", "publication_date": "2025-06-30", "data_status": "imported"}],
        "ipos": [{
            "company": {"name": "Company X Ltd", "sector": "Specialty Chemicals", "industry": "Intermediates",
                        "description": "What the company does.", "business_model": "How it earns revenue."},
            "issue": {"exchange": "NSE, BSE", "issue_type": "mainboard", "open_date": "2025-07-10", "close_date": "2025-07-14",
                      "listing_date": "2025-07-17", "price_band_low": 300, "price_band_high": 315, "lot_size": 47,
                      "issue_size_cr": 800, "fresh_issue_cr": 500, "ofs_cr": 300, "pre_issue_shares": 120000000,
                      "post_issue_shares": 135873016, "promoter_holding_pre_pct": 85, "promoter_holding_post_pct": 66,
                      "risk_disclosures_reviewed": True, "source_key": "rhp"},
            "unit": "crore",
            "financials": [{"period_label": "FY2025", "period_end": "2025-03-31", "period_months": 12, "revenue": 1200, "ebitda": 210,
                            "ebit": 170, "pat": 115, "operating_cash_flow": 130, "capex": 70, "interest_expense": 14, "total_debt": 260,
                            "cash_and_equivalents": 60, "total_equity": 780, "source_key": "rhp"}],
            "peers": [{"name": "Listed Peer Ltd", "sector": "Specialty Chemicals", "as_of": "2025-07-01", "pe": 34.5, "ev_ebitda": 21.0,
                       "selection_reason": "Same end-market, listed on NSE", "source_key": "rhp"}],
            "disclosures": [{"category": "litigation", "severity": "medium", "status": "confirmed_disclosure", "title": "Tax demand under appeal",
                             "description": "Details from the risk factors section.", "amount_cr": 12.0, "page": 45, "source_key": "rhp"}],
        }],
    }
    return PlainTextResponse(json.dumps(example, indent=2), media_type="application/json",
                             headers={"Content-Disposition": 'attachment; filename="kcp_bundle_template.json"'})


# ---------------------------------------------------------------------------- documents
@router.post("/documents", status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=3, max_length=300),
    doc_type: DOC_TYPES = Form("other"),
    ipo_id: int | None = Form(None),
    source_url: str | None = Form(None, max_length=1000),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_user),
) -> dict[str, Any]:
    limiter.hit("upload", str(ctx.user.id))
    if ipo_id is not None and get_ipo(db, ipo_id) is None:
        raise not_found("IPO")
    if source_url and not source_url.startswith(("https://", "http://")):
        raise ApiError(422, "invalid_url", "source_url must start with http(s)://")
    data = await _read_limited(file, (".pdf", ".txt"))
    try:
        if (file.filename or "").lower().endswith(".pdf"):
            doc = rag.ingest_pdf_document(db, ipo_id=ipo_id, title=title, doc_type=doc_type, data=data, source_url=source_url, user_id=ctx.user.id)
        else:
            doc = rag.ingest_text_document(db, ipo_id=ipo_id, title=title, doc_type=doc_type, text=data.decode("utf-8", errors="replace"),
                                           source_url=source_url, user_id=ctx.user.id)
    except rag.DocumentError as exc:
        raise ApiError(422, "invalid_document", str(exc)) from exc
    audit(db, request, "document_upload", ctx.user.id, document_id=doc.id, ipo_id=ipo_id)
    return _doc_out(doc)


def _doc_out(d: SourceDocument) -> dict[str, Any]:
    return {"id": d.id, "ipo_id": d.ipo_id, "title": d.title, "doc_type": d.doc_type, "page_count": d.page_count,
            "chunks": len(d.chunks), "source_url": d.source_url, "data_status": d.data_status,
            "embedding_model": d.embedding_model, "retrieval_mode": "embedding" if d.embedding_model else "keyword",
            "injection_flags": d.injection_flags, "retrieved_at": d.retrieved_at.isoformat()}


@router.get("/documents")
def list_documents(ipo_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(SourceDocument).order_by(SourceDocument.retrieved_at.desc()).limit(200)
    if ipo_id is not None:
        q = q.where(SourceDocument.ipo_id == ipo_id)
    return [_doc_out(d) for d in db.execute(q).scalars()]


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    ipo_id: int | None = None
    k: int = Field(5, ge=1, le=10)


@router.post("/documents/search")
def search_documents(body: SearchIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    return rag.search(db, body.query, ipo_id=body.ipo_id, k=body.k)


class FetchIn(BaseModel):
    url: str = Field(min_length=10, max_length=1000)
    title: str = Field(min_length=3, max_length=300)
    doc_type: DOC_TYPES = "disclosure"
    ipo_id: int | None = None


@router.post("/sources/fetch", status_code=201)
def fetch_official_source(body: FetchIn, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    limiter.hit("source_fetch", str(ctx.user.id))
    if body.ipo_id is not None and get_ipo(db, body.ipo_id) is None:
        raise not_found("IPO")
    try:
        doc, fetched = ingest_official_url(db, url=body.url, ipo_id=body.ipo_id, title=body.title, doc_type=body.doc_type, user_id=ctx.user.id)
    except (SourceFetchError, rag.DocumentError) as exc:
        audit(db, request, "source_fetch_failed", ctx.user.id, url=body.url, reason=str(exc))
        raise ApiError(422, "source_fetch_failed", str(exc)) from exc
    audit(db, request, "source_fetch", ctx.user.id, url=fetched.url, document_id=doc.id, cached=fetched.from_cache)
    return {**_doc_out(doc), "from_cache": fetched.from_cache}


# ---------------------------------------------------------------------------- scoring config
@router.get("/scoring/config")
def active_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    row = get_active_config_row(db)
    return {"version": row.version, "description": row.description, "config": row.config, "created_at": row.created_at.isoformat()}


@router.get("/scoring/configs")
def list_configs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    get_active_config_row(db)
    return [{"version": r.version, "description": r.description, "is_active": r.is_active, "created_at": r.created_at.isoformat()}
            for r in db.execute(select(ScoringConfigVersion).order_by(ScoringConfigVersion.id.desc())).scalars()]


class ConfigIn(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(min_length=5, max_length=1000)
    config: dict[str, Any]
    activate: bool = True


@router.post("/scoring/configs", status_code=201)
def create_config(body: ConfigIn, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    if db.execute(select(ScoringConfigVersion).where(ScoringConfigVersion.version == body.version)).scalar_one_or_none():
        raise ApiError(409, "version_exists", "configuration versions are immutable; choose a new version number")
    cfg = {**get_default_config(), **body.config, "version": body.version, "description": body.description}
    try:
        validate_config(cfg)
    except ConfigError as exc:
        raise ApiError(422, "invalid_config", str(exc)) from exc
    if body.activate:
        for r in db.execute(select(ScoringConfigVersion).where(ScoringConfigVersion.is_active.is_(True))).scalars():
            r.is_active = False
    row = ScoringConfigVersion(version=body.version, description=body.description, config=cfg, is_active=body.activate, created_by=ctx.user.id)
    db.add(row)
    db.commit()
    audit(db, request, "scoring_config_create", ctx.user.id, version=body.version, activate=body.activate)
    return {"version": row.version, "is_active": row.is_active}


@router.post("/scoring/configs/{version}/activate")
def activate_config(version: str, request: Request, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    row = db.execute(select(ScoringConfigVersion).where(ScoringConfigVersion.version == version)).scalar_one_or_none()
    if row is None:
        raise not_found("configuration version")
    for r in db.execute(select(ScoringConfigVersion).where(ScoringConfigVersion.is_active.is_(True))).scalars():
        r.is_active = False
    row.is_active = True
    db.commit()
    audit(db, request, "scoring_config_activate", ctx.user.id, version=version)
    return {"version": version, "is_active": True}
