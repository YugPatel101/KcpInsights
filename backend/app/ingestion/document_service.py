"""Automatic retrieval and processing of official offer documents.

Two official sources feed the same pipeline:

* **NSE** — each issue page links an RHP archive (``nsearchives.nseindia.com/content/ipo/RHP_<SYM>.zip``).
* **SEBI** — the public-issue filings lists (draft and red herring offer documents) link a filing
  page that embeds the PDF. A SEBI RHP is processed only when no NSE copy could be read (a
  fallback, not a duplicate); a DRHP is processed for issues that have no RHP yet.

Per document: HEAD check (ETag / Last-Modified / size) → download only when new or changed → pick
the prospectus PDF from a zip (size and ratio limits, nothing extracted to disk by archive path) →
content hash (an identical file already stored for the issue is marked a duplicate) → store the
original under ``data/documents`` → extract statements, peers and disclosures (OCR for image-only
pages when Tesseract is installed) → persist with provenance → recompute the IPO's score.

Only allowlisted official hosts are contacted. A failed download or extraction never removes data
stored earlier; it is recorded on the document, retried with exponential backoff and, after the
configured number of attempts, left as a dead letter on the data-pipeline page.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.financials.disclosures import extract_disclosures, parse_peers
from app.financials.industry import classify_industry, lender_kpis
from app.financials.ocr import OcrDocument, image_only_pages, tesseract_available
from app.financials.offer_terms import extract_offer_terms
from app.financials.statement_parser import PARSER_VERSION, ExtractionResult, extract_financials
from app.ingestion import normalizer as nz
from app.ingestion.financial_store import StoreStats, store_classification, store_facts, store_offer_terms, store_peers, store_statements
from app.ingestion.http import PoliteClient, SourceError
from app.ingestion.sources.sebi import SEBI_HOSTS, Filing, SEBIFilingsSource
from app.models import Company, DataMode, DocumentExtraction, IPOIssue, SourceDocument, utcnow

log = logging.getLogger(__name__)

ALLOWED_DOC_HOSTS = {"nsearchives.nseindia.com", "archives.nseindia.com", *SEBI_HOSTS}
DOC_SOURCES = ("nse_rhp", "sebi_rhp", "sebi_drhp")
READ_OK = ("extracted", "partial")
MAX_PAGES = 3000
MAX_ZIP_RATIO = 60  # uncompressed / compressed; PDFs barely compress, so a high ratio signals a zip bomb


class DocumentFetchError(RuntimeError):
    pass


@dataclass
class DocRunStats:
    discovered: int = 0
    checked_unchanged: int = 0
    downloaded: int = 0
    extracted: int = 0
    failed: int = 0
    requests: int = 0
    pruned: int = 0
    duplicates: int = 0
    dead_letters: int = 0
    filings_seen: int = 0
    pipeline_ipos_created: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    processed: list[dict[str, Any]] = field(default_factory=list)


def documents_dir() -> Path:
    d = get_settings().data_dir / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def allowed(url: str | None) -> bool:
    if not url:
        return False
    u = urlparse(url)
    return u.scheme == "https" and (u.hostname or "") in ALLOWED_DOC_HOSTS


# ---------------------------------------------------------------------------- discovery
def discover(db: Session, ipos: list[IPOIssue]) -> int:
    """Create a pending document record for every allowlisted RHP link not seen before."""
    n = 0
    for ipo in ipos:
        url = ipo.offer_document_url
        if not allowed(url):
            continue
        exists = db.execute(select(SourceDocument.id).where(SourceDocument.ipo_id == ipo.id, SourceDocument.archive_url == url).limit(1)).first()
        if exists:
            continue
        db.add(SourceDocument(ipo_id=ipo.id, title=f"{ipo.company.name} — Red Herring Prospectus", doc_type="rhp", source_url=url,
                              archive_url=url, source_key="nse_rhp", sha256="", mime_type="application/zip", page_count=0,
                              data_status="verified", extraction_status="pending", original_retained=False))
        n += 1
    db.commit()
    return n


def match_ipo(db: Session, company_name: str) -> IPOIssue | None:
    """The live (non-demo) issue of a company, matched on its normalised name; the latest one wins."""
    target = nz.normalize_company_name(company_name)
    if not target:
        return None
    best: IPOIssue | None = None
    for ipo in db.execute(select(IPOIssue).join(Company).where(IPOIssue.data_mode != DataMode.demo.value)).scalars():
        if nz.normalize_company_name(ipo.company.name) == target and (best is None or ipo.id > best.id):
            best = ipo
    return best


def discover_sebi(db: Session, source: SEBIFilingsSource, stats: DocRunStats) -> None:
    """Record new SEBI RHP/DRHP filings. A company with no issue on record yet becomes a pipeline issue.

    A pipeline issue has no dates or price: it records that an offer document was filed with SEBI. When NSE
    later announces the issue, NSE discovery matches it by company name and fills in the issue terms.
    """
    for listing in ("rhp", "drhp"):
        res = source.fetch_filings(listing)
        stats.requests += 1
        if res.status != "ok" or res.data is None:
            stats.errors.append({"source": f"sebi_{listing}", "error": res.error})
            continue
        for f in res.data:
            stats.filings_seen += 1
            if db.execute(select(SourceDocument.id).where(SourceDocument.source_url == f.filing_url).limit(1)).first():
                continue
            ipo = match_ipo(db, f.company_name) or _pipeline_ipo(db, f, stats)
            db.add(SourceDocument(ipo_id=ipo.id, title=f"{ipo.company.name} — {'Draft Red Herring' if f.kind == 'drhp' else 'Red Herring'} Prospectus (SEBI)",
                                  doc_type=f.kind, source_url=f.filing_url, archive_url=None, source_key=f"sebi_{f.kind}", sha256="",
                                  mime_type="application/pdf", page_count=0, published_date=f.filed_on, data_status="verified",
                                  extraction_status="pending", original_retained=False))
            stats.discovered += 1
        db.commit()


def _pipeline_ipo(db: Session, f: Filing, stats: DocRunStats) -> IPOIssue:
    company = Company(name=f.company_name, sector="Unclassified", data_status="verified")
    db.add(company)
    db.flush()
    ipo = IPOIssue(company_id=company.id, exchange="Not announced", issue_type="mainboard", data_mode=DataMode.source.value,
                   data_status="verified", risk_disclosures_reviewed=False,
                   research_notes=f"Offer document filed with SEBI on {f.filed_on:%d %b %Y} ({f.title}); issue dates and price not announced.")
    db.add(ipo)
    db.flush()
    db.refresh(ipo)
    stats.pipeline_ipos_created += 1
    return ipo


def _priority(ipo: IPOIssue, today: date) -> tuple[int, Any]:
    from app.services.ipo_service import effective_status

    st = effective_status(ipo, today)
    rank = {"open": 0, "upcoming": 1, "closed": 2, "listed": 3}.get(st, 4)
    return rank, -(ipo.open_date or date.min).toordinal()


def due_documents(db: Session, today: date) -> list[SourceDocument]:
    """Documents to fetch or process now: never read first, then retries that are due, then re-checks of open/upcoming issues.

    NSE copies come first; a SEBI RHP only when the issue has no readable NSE RHP; a DRHP only when the issue has no RHP at all.
    """
    s = get_settings()
    out: list[tuple[tuple[Any, ...], SourceDocument]] = []
    from app.services.ipo_service import effective_status

    now = utcnow()
    docs = list(db.execute(select(SourceDocument).where(SourceDocument.source_key.in_(DOC_SOURCES))).scalars())
    by_ipo: dict[int, list[SourceDocument]] = {}
    for d in docs:
        if d.ipo_id:
            by_ipo.setdefault(d.ipo_id, []).append(d)
    for doc in docs:
        ipo = db.get(IPOIssue, doc.ipo_id) if doc.ipo_id else None
        if ipo is None or doc.extraction_status in ("duplicate", "skipped"):
            continue
        st = effective_status(ipo, today)
        if st == "listed" and ipo.listing_date and (today - ipo.listing_date).days > s.document_window_days:
            continue
        siblings = by_ipo.get(ipo.id, [])
        if doc.source_key == "sebi_rhp" and any(d.source_key == "nse_rhp" and d.extraction_status in READ_OK for d in siblings):
            continue  # the NSE copy was read; the SEBI copy is only a fallback
        if doc.source_key == "sebi_drhp" and any(d.doc_type == "rhp" for d in siblings):
            continue  # an RHP supersedes the draft
        if doc.archive_url and db.execute(select(SourceDocument.id).where(SourceDocument.archive_url == doc.archive_url,
                                                                            SourceDocument.id > doc.id).limit(1)).first():
            continue  # a newer record exists for this file (a revised document)
        source_rank = {"nse_rhp": 0, "sebi_rhp": 1, "sebi_drhp": 2}[doc.source_key or "nse_rhp"]
        if doc.extraction_status == "failed":
            if doc.attempts >= s.document_max_attempts or (doc.next_attempt_at and doc.next_attempt_at > now):
                continue  # dead letter, or backing off
            out.append(((5, source_rank, *_priority(ipo, today)), doc))
        elif doc.extraction_status == "pending" or (doc.parser_version and doc.parser_version != PARSER_VERSION):
            if doc.next_attempt_at and doc.next_attempt_at > now:
                continue  # a download error is backing off
            rank = _priority(ipo, today)
            out.append(((rank[0] + 2 * source_rank, source_rank, *rank), doc))
        elif st in ("open", "upcoming") and doc.archive_url and (doc.last_checked_at is None
                                                                 or now - doc.last_checked_at > timedelta(days=s.document_recheck_days)):
            out.append(((9, source_rank, 0, 0), doc))
    out.sort(key=lambda x: x[0])
    return [d for _, d in out]


def record_failure(doc: SourceDocument, error: str) -> bool:
    """Count a failed attempt and schedule the next one (1 h, 2 h, 4 h, … capped at 7 days). True when it became a dead letter."""
    s = get_settings()
    doc.attempts = (doc.attempts or 0) + 1
    doc.extraction_error = error[:1000]
    doc.last_checked_at = utcnow()
    if doc.attempts >= s.document_max_attempts:
        doc.next_attempt_at = None
        doc.extraction_status = "failed"  # dead letter: shown on the data-pipeline page, no further automatic attempts
        return True
    doc.next_attempt_at = utcnow() + timedelta(hours=min(2 ** (doc.attempts - 1), 168))
    return False


# ---------------------------------------------------------------------------- download
def pick_pdf(archive: bytes, max_bytes: int) -> tuple[str, bytes]:
    """The prospectus PDF inside an NSE archive (the 'GID' general-information document is skipped)."""
    if archive[:5] == b"%PDF-":
        return "document.pdf", archive
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise DocumentFetchError("downloaded file is neither a PDF nor a zip archive") from exc
    with zf:
        pdfs = [i for i in zf.infolist() if i.filename.lower().endswith(".pdf") and not i.is_dir()]
        if not pdfs:
            raise DocumentFetchError("archive contains no PDF")
        for i in pdfs:
            if i.file_size > max_bytes or (i.compress_size and i.file_size / max(i.compress_size, 1) > MAX_ZIP_RATIO):
                raise DocumentFetchError(f"archive member {Path(i.filename).name!r} exceeds the size limits")

        def score(i: zipfile.ZipInfo) -> tuple[int, int]:
            name = Path(i.filename).name.lower()
            named = 2 if re.search(r"\brhp\b|_rhp|rhp_|red herring|prospectus|drhp", name) else 0
            generic = 1 if re.search(r"\bgid\b|_gid|general information|form|abridged|addendum|corrigendum", name) else 0
            return named - generic, i.file_size

        best = max(pdfs, key=score)
        data = zf.read(best)
    if data[:5] != b"%PDF-":
        raise DocumentFetchError("selected archive member is not a PDF")
    return Path(best.filename).name, data


def fetch(client: PoliteClient, db: Session, doc: SourceDocument, stats: DocRunStats) -> SourceDocument | None:
    """Download if new or changed. Returns the document to process, or None when unchanged or a duplicate."""
    s = get_settings()
    if not doc.archive_url and (doc.source_key or "").startswith("sebi_"):
        doc.archive_url = SEBIFilingsSource(client).resolve_pdf(doc.source_url or "")  # one request to the filing page
        stats.requests += 1
        db.commit()
    url = doc.archive_url or ""
    if not allowed(url):
        raise DocumentFetchError("document URL is not on an allowlisted official host")
    head: dict[str, str] = {}
    try:
        head = client.head(url)
        stats.requests += 1
    except SourceError as exc:
        if exc.kind in ("access_denied", "rate_limited"):
            raise
        head = {}  # some servers refuse HEAD; fall back to a GET
    etag, modified = head.get("etag"), head.get("last-modified")
    doc.last_checked_at = utcnow()
    if doc.sha256 and doc.extraction_status != "pending" and (etag or modified) and etag == doc.http_etag and modified == doc.http_last_modified:
        stats.checked_unchanged += 1
        db.commit()
        return None
    body, _, headers = client.request(url, max_bytes=s.ingest_max_offer_document_mb * 1024 * 1024)
    stats.requests += 1
    name, pdf = pick_pdf(body, 4 * s.ingest_max_offer_document_mb * 1024 * 1024)
    sha = hashlib.sha256(pdf).hexdigest()
    if doc.sha256 == sha:  # same content behind new headers
        doc.http_etag, doc.http_last_modified = headers.get("etag"), headers.get("last-modified")
        stats.checked_unchanged += 1
        db.commit()
        return None if doc.extraction_status != "pending" else doc
    twin = db.execute(select(SourceDocument).where(SourceDocument.ipo_id == doc.ipo_id, SourceDocument.sha256 == sha,
                                                   SourceDocument.id != doc.id).limit(1)).scalar_one_or_none()
    if twin is not None:  # the same file is already stored for this issue (e.g. NSE and SEBI copies of one RHP)
        doc.sha256, doc.size_bytes, doc.extraction_status = sha, len(pdf), "duplicate"
        doc.extraction_error = f"identical to document #{twin.id} (same SHA-256); not processed twice"
        doc.http_etag, doc.http_last_modified = headers.get("etag"), headers.get("last-modified")
        db.commit()
        stats.duplicates += 1
        return None
    target = doc
    if doc.sha256:  # a revised document: keep the previous record (and its figures) as history
        target = SourceDocument(ipo_id=doc.ipo_id, title=doc.title, doc_type=doc.doc_type, source_url=url, archive_url=url, source_key=doc.source_key,
                                sha256="", mime_type="application/pdf", data_status="verified", extraction_status="pending")
        db.add(target)
    folder = documents_dir() / str(doc.ipo_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sha}.pdf").write_bytes(pdf)
    target.storage_key = f"documents/{doc.ipo_id}/{sha}.pdf"
    target.sha256 = sha
    target.mime_type = "application/pdf"
    target.size_bytes = len(pdf)
    target.original_filename = name[:300]
    target.http_etag, target.http_last_modified = headers.get("etag"), headers.get("last-modified")
    target.retrieved_at = utcnow()
    target.last_checked_at = utcnow()
    target.original_retained = True
    target.extraction_status = "pending"
    db.commit()
    stats.downloaded += 1
    return target


def document_path(doc: SourceDocument) -> Path | None:
    if not doc.storage_key or not doc.original_retained:
        return None
    p = (get_settings().data_dir / doc.storage_key).resolve()
    return p if p.is_file() and get_settings().data_dir.resolve() in p.parents else None


# ---------------------------------------------------------------------------- processing
def process(db: Session, doc: SourceDocument, *, rescore: bool = True) -> dict[str, Any]:
    """Extract and persist everything the parsers can read from a stored document."""
    import pymupdf

    run = DocumentExtraction(document_id=doc.id, parser_version=PARSER_VERSION, status="failed")
    db.add(run)
    path = document_path(doc)
    ipo = db.get(IPOIssue, doc.ipo_id) if doc.ipo_id else None
    try:
        if path is None or ipo is None:
            raise DocumentFetchError("original document is not stored")
        ocr_note: str | None = None
        ocr_pages: set[int] = set()
        with pymupdf.open(path) as pdf:
            if pdf.page_count > MAX_PAGES:
                raise DocumentFetchError(f"document has {pdf.page_count} pages (limit {MAX_PAGES})")
            doc.page_count = pdf.page_count
            texts = [p.get_text() for p in pdf]
            result = extract_financials(pdf)
            method = "text"
            scanned = image_only_pages(texts)
            if result.status != "extracted" and len(scanned) >= 3:
                result, ocr_pages, ocr_note = _ocr_extract(pdf, scanned, result)
                method = "text+ocr" if ocr_pages else "text"
            peers = parse_peers(pdf, texts, ipo.company.name)
            facts = extract_disclosures(pdf, texts)
            terms = extract_offer_terms(texts)
            industry = classify_industry(texts, ipo.company.name)
            kpis = lender_kpis(pdf, texts) if industry.profile in ("lender", "insurer") else {}
        stats = StoreStats()
        store_statements(db, ipo, doc, result, stats, ocr_pages=ocr_pages)
        store_peers(db, ipo, doc, peers, stats)
        store_facts(db, ipo, doc, facts, stats)
        store_offer_terms(db, ipo, doc, terms, stats)
        store_classification(db, ipo, doc, industry, kpis, stats)
        doc.extraction_method = method
        warnings = list(result.warnings) + (peers.warnings if peers else ["listed-peer comparison table not found"])
        if ocr_note:
            warnings.append(ocr_note)
        run.status = result.status
        run.pages_scanned = result.pages_scanned
        run.statements = result.summary()
        run.checks = [{"period": p.label, "basis": p.basis, "status": p.validation_status, "checks": p.checks} for p in result.periods]
        run.warnings = warnings[:50]
        doc.extraction_status = result.status
        doc.extraction_error = None if result.status != "not_found" else "; ".join(warnings)[:1000]
        doc.extracted_at = utcnow()
        doc.attempts, doc.next_attempt_at = 0, None
        doc.parser_version = PARSER_VERSION
        run.finished_at = utcnow()
        db.commit()
        if rescore:
            from app.services.ipo_service import score_ipo

            score_ipo(db, ipo, persist=True)
        return {"document_id": doc.id, "ipo_id": ipo.id, "status": result.status, **stats.as_dict(), "warnings": warnings[:5]}
    except Exception as exc:  # noqa: BLE001 - a corrupt or unexpected PDF must not stop the job
        db.rollback()
        doc = db.get(SourceDocument, doc.id) or doc
        doc.extraction_status = "failed"
        record_failure(doc, f"{type(exc).__name__}: {str(exc)[:400]}")
        doc.parser_version = PARSER_VERSION
        doc.extracted_at = utcnow()
        db.add(DocumentExtraction(document_id=doc.id, parser_version=PARSER_VERSION, status="failed", finished_at=utcnow(),
                                  error=doc.extraction_error))
        db.commit()
        log.warning("document %s extraction failed: %s", doc.id, doc.extraction_error)
        return {"document_id": doc.id, "status": "failed", "error": doc.extraction_error}


def best_document(db: Session, ipo: IPOIssue) -> SourceDocument | None:
    """The stored offer document to read issue terms from: an RHP before a DRHP, the NSE copy before SEBI's, newest first."""
    docs = db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id, SourceDocument.source_key.in_(DOC_SOURCES),
                                                   SourceDocument.original_retained.is_(True),
                                                   SourceDocument.extraction_status.in_(("extracted", "partial", "not_found")))).scalars().all()
    usable = [d for d in docs if document_path(d) is not None]
    return min(usable, key=lambda d: (DOC_SOURCES.index(d.source_key or "nse_rhp"), -d.id)) if usable else None


def reread_offer_terms(db: Session, ipo: IPOIssue) -> bool:
    """Re-read share capital and offer terms from the stored offer document (text layer only, no network requests).

    Used when the offer-terms extractor changes, so every IPO with a stored document gets the improvement without
    downloading or re-parsing its financial statements.
    """
    import pymupdf

    doc = best_document(db, ipo)
    path = document_path(doc) if doc is not None else None
    if doc is None or path is None:
        return False
    with pymupdf.open(path) as pdf:
        if pdf.page_count > MAX_PAGES:
            return False
        texts = [p.get_text() for p in pdf]
        facts = extract_disclosures(pdf, texts)
        terms = extract_offer_terms(texts)
    stats = StoreStats()
    store_facts(db, ipo, doc, facts, stats)
    store_offer_terms(db, ipo, doc, terms, stats)
    return True


def _ocr_extract(pdf: Any, scanned: list[int], text_result: ExtractionResult) -> tuple[ExtractionResult, set[int], str]:
    """Re-run extraction with image-only pages read by local OCR. Keeps the text-only result unless OCR adds periods."""
    s = get_settings()
    if not s.ocr_enabled:
        return text_result, set(), f"{len(scanned)} pages have no text layer (scanned images); OCR is disabled (KCP_OCR_ENABLED=false)"
    if not tesseract_available():
        return text_result, set(), f"{len(scanned)} pages have no text layer (scanned images); install Tesseract to read them with local OCR"
    pages = scanned[: s.ocr_max_pages]
    od = OcrDocument(pdf, pages, dpi=s.ocr_dpi, time_budget_s=s.ocr_time_budget_seconds)
    ocr_result = extract_financials(od)

    def filled(r: ExtractionResult) -> int:
        return sum(1 for p in r.periods for _ in p.figures)

    note = (f"{len(scanned)} pages have no text layer (scanned images); {len(od.ocr_pages)} were read with local OCR (Tesseract)"
            + (f"; {len(od.failed)} could not be recognised" if od.failed else "")
            + (f"; {len(scanned) - len(pages)} more beyond the {s.ocr_max_pages}-page limit" if len(scanned) > len(pages) else "")
            + ". Figures read by OCR are shown for reference and are not used in scores.")
    if filled(ocr_result) > filled(text_result):
        return ocr_result, od.ocr_pages, note
    return text_result, set(), note + " OCR found no additional statement figures."


def prune(db: Session) -> int:
    """Keep stored originals under the configured total size; oldest listed issues go first."""
    s = get_settings()
    docs = [d for d in db.execute(select(SourceDocument).where(SourceDocument.original_retained.is_(True),
                                                                SourceDocument.source_key.in_(DOC_SOURCES))).scalars()]
    total = sum(d.size_bytes or 0 for d in docs)
    limit = s.documents_max_total_mb * 1024 * 1024
    if total <= limit:
        return 0
    ordered = sorted(docs, key=lambda d: d.retrieved_at)
    n = 0
    for d in ordered:
        if total <= limit:
            break
        if d.extraction_status == "pending":
            continue
        p = document_path(d)
        if p is not None:
            p.unlink(missing_ok=True)
        d.original_retained = False
        total -= d.size_bytes or 0
        n += 1
    db.commit()
    return n


def _superseded_fallback(db: Session, doc: SourceDocument) -> bool:
    """A SEBI copy is only a fallback: skip it once the NSE RHP (or, for a DRHP, any RHP) has been read."""
    if doc.source_key not in ("sebi_rhp", "sebi_drhp") or doc.ipo_id is None:
        return False
    wanted = ("nse_rhp",) if doc.source_key == "sebi_rhp" else ("nse_rhp", "sebi_rhp")
    return db.execute(select(SourceDocument.id).where(SourceDocument.ipo_id == doc.ipo_id, SourceDocument.source_key.in_(wanted),
                                                      SourceDocument.extraction_status.in_(READ_OK)).limit(1)).first() is not None


def run_documents(db: Session, client: PoliteClient, ipos: list[IPOIssue], today: date, *, sebi: bool = False) -> DocRunStats:
    s = get_settings()
    stats = DocRunStats()
    stats.discovered = discover(db, ipos)
    if sebi and s.ingest_sebi_filings:
        discover_sebi(db, SEBIFilingsSource(client), stats)
    for doc in due_documents(db, today)[: s.ingest_max_documents_per_run]:
        if _superseded_fallback(db, doc):
            continue  # an earlier document in this run already provided the statements
        try:
            stored = doc.original_retained and doc.sha256 and doc.extraction_status in ("pending", "failed")
            target = doc if stored or (doc.original_retained and doc.parser_version != PARSER_VERSION) else fetch(client, db, doc, stats)
            if target is None:
                continue
            res = process(db, target)
            stats.processed.append(res)
            if res["status"] == "failed":
                stats.failed += 1
            else:
                stats.extracted += 1
        except SourceError as exc:
            db.rollback()
            stats.errors.append({"document_id": doc.id, "error": str(exc)[:300], "kind": exc.kind})
            if record_failure(doc, f"download failed: {exc}"):
                stats.dead_letters += 1
            db.commit()
            if exc.kind in ("access_denied", "rate_limited"):
                break
        except DocumentFetchError as exc:
            db.rollback()
            doc.extraction_status = "failed"
            if record_failure(doc, str(exc)):
                stats.dead_letters += 1
            db.commit()
            stats.failed += 1
            stats.errors.append({"document_id": doc.id, "error": str(exc)[:300]})
    stats.pruned = prune(db)
    return stats
