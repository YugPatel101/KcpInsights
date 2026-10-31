"""Document ingestion and keyword search over legally obtained offer documents.

* PDF text extraction per page (pypdf), with size/page limits, plus plain-text ingestion.
* Page-referenced chunks searched with BM25, with a relevance threshold and an explicit
  "no evidence" result.
* Document text is untrusted data: it is displayed as quoted text and never executed;
  chunks that contain instruction-like text are flagged.
"""
from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import DocumentChunk, SourceDocument, SourceRecord

CHUNK_CHARS = 900
CHUNK_OVERLAP = 150
MAX_PAGE_CHARS = 30_000
BM25_THRESHOLD = 1.2

INJECTION_PATTERNS = [
    r"ignore (all|any|the)? ?(previous|prior|above) (instructions|prompts?)",
    r"disregard (all|the|any)? ?(previous|prior|system)",
    r"you are now",
    r"system prompt",
    r"\bassistant\s*:",
    r"call (the )?(tool|function)",
    r"\"tool\"\s*:",
    r"execute (this|the following)? ?(code|command|shell)",
    r"(rm -rf|curl\s+http|wget\s+http|os\.system|subprocess)",
    r"(reveal|print|output) (your|the) (instructions|prompt|api key|secret)",
    r"(set|change) (the )?(score|rating) to",
]
_INJ = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

STOPWORDS = set(
    "a an the and or of to in on for with by is are was were be been this that these those it its as at from "
    "what which who whom how why when where does do did has have had not no our we you they their there "
    "about into over under than then so such can could would should will may might".split()
)


class DocumentError(ValueError):
    pass


def looks_like_injection(text: str) -> bool:
    return bool(_INJ.search(text))


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9₹%]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def chunk_page(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            ws = text.rfind(" ", start + CHUNK_CHARS // 2, end)
            end = ws if ws > 0 else end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return [c for c in chunks if c]


def extract_pdf_pages(data: bytes) -> list[str]:
    s = get_settings()
    if not data.startswith(b"%PDF-"):
        raise DocumentError("file is not a PDF")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocumentError("encrypted PDFs are not supported")
        n = len(reader.pages)
    except PdfReadError as exc:
        raise DocumentError(f"unreadable PDF: {exc}") from exc
    if n > s.max_pdf_pages:
        raise DocumentError(f"PDF has {n} pages; limit is {s.max_pdf_pages}")
    pages = []
    for page in reader.pages:
        try:
            pages.append((page.extract_text() or "")[:MAX_PAGE_CHARS])
        except Exception:  # noqa: BLE001 - a malformed page must not abort the document
            pages.append("")
    return pages


def _store_document(db: Session, *, ipo_id: int | None, title: str, doc_type: str, pages: list[str], sha: str, mime: str,
                    source_url: str | None, user_id: int | None, data_status: str, storage_key: str | None) -> SourceDocument:
    doc = SourceDocument(ipo_id=ipo_id, title=title[:300], doc_type=doc_type, source_url=source_url, storage_key=storage_key,
                         sha256=sha, mime_type=mime, page_count=len(pages), uploaded_by=user_id, data_status=data_status)
    db.add(doc)
    db.flush()
    chunks: list[DocumentChunk] = []
    for pno, text in enumerate(pages, start=1):
        for ci, c in enumerate(chunk_page(text)):
            chunks.append(DocumentChunk(document_id=doc.id, page=pno, chunk_index=ci, text=c, injection_suspected=looks_like_injection(c)))
    db.add_all(chunks)
    doc.injection_flags = sum(1 for c in chunks if c.injection_suspected)
    db.add(SourceRecord(source_type="document", title=title[:300], source_url=source_url, document_id=doc.id, data_status=data_status,
                        notes=f"{len(pages)} pages, {len(chunks)} chunks"))
    db.commit()
    return doc


def ingest_text_document(db: Session, *, ipo_id: int | None, title: str, doc_type: str, text: str, source_url: str | None,
                         user_id: int | None, data_status: str = "imported") -> SourceDocument:
    pages = [p for p in text.split("\f")] if "\f" in text else [text]
    sha = hashlib.sha256(text.encode()).hexdigest()
    return _store_document(db, ipo_id=ipo_id, title=title, doc_type=doc_type, pages=pages, sha=sha, mime="text/plain",
                           source_url=source_url, user_id=user_id, data_status=data_status, storage_key=None)


def ingest_pdf_document(db: Session, *, ipo_id: int | None, title: str, doc_type: str, data: bytes, source_url: str | None,
                        user_id: int | None, data_status: str = "imported") -> SourceDocument:
    s = get_settings()
    pages = extract_pdf_pages(data)
    sha = hashlib.sha256(data).hexdigest()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    key = f"{sha}.pdf"
    path = s.upload_dir / key
    if not path.exists():
        path.write_bytes(data)
    return _store_document(db, ipo_id=ipo_id, title=title, doc_type=doc_type, pages=pages, sha=sha, mime="application/pdf",
                           source_url=source_url, user_id=user_id, data_status=data_status, storage_key=key)


def _bm25(query: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    if not n:
        return []
    avgdl = sum(len(d) for d in docs) / n or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for q in set(query):
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(d) / avgdl))
        scores.append(s)
    return scores


def search(db: Session, query: str, *, ipo_id: int | None = None, k: int = 5) -> dict[str, Any]:
    q = select(DocumentChunk).join(DocumentChunk.document).options(selectinload(DocumentChunk.document))
    if ipo_id is not None:
        q = q.where(SourceDocument.ipo_id == ipo_id)
    chunks = list(db.execute(q).scalars())
    if not chunks:
        return {"mode": "none", "results": [], "no_evidence": True, "reason": "no documents ingested for this scope"}
    mode = "keyword"
    qt = tokenize(query)
    if not qt:
        return {"mode": mode, "results": [], "no_evidence": True, "reason": "query has no searchable terms"}
    bm = _bm25(qt, [tokenize(c.text) for c in chunks])
    scored = [(s, c) for s, c in zip(bm, chunks, strict=True) if s >= BM25_THRESHOLD]
    scored.sort(key=lambda x: -x[0])
    results = []
    for s, c in scored[:k]:
        results.append({
            "chunk_id": c.id,
            "document_id": c.document_id,
            "document_title": c.document.title,
            "doc_type": c.document.doc_type,
            "page": c.page,
            "text": c.text[:900],
            "score": round(s, 4),
            "source_url": c.document.source_url,
            "data_status": c.document.data_status,
            "injection_suspected": c.injection_suspected,
        })
    return {
        "mode": mode,
        "threshold": BM25_THRESHOLD,
        "results": results,
        "no_evidence": not results,
        "reason": None if results else "no passage met the relevance threshold",
    }
