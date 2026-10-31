# Architecture

```
                    ┌────────────────────────────── backend (FastAPI, one process) ──────────────────────────────┐
 NSE JSON ─┐        │  APScheduler jobs (locks per source, recovery after crash)                                 │
 NSE arch. ─┼─ HTTP ─▶  ingestion/sources/*  ─▶  ipo_data_service (field observations, precedence, change log)  │
 SEBI      ─┘ polite │        │                                                                                    │
            client   │        └▶ document_service: discover → HEAD → download → SHA-256 → (dedupe)                │
                     │              → financials/statement_parser (+ ocr for image-only pages)                     │
                     │              → disclosures · industry classifier → financial_store (versioned, provenance) │
                     │                                     │                                                       │
                     │                                     ▼                                                       │
                     │   services/quant_engine (pure functions, versioned config, industry profiles)               │
                     │        → research_scores (stored, fingerprinted) · completeness (cached per IPO)            │
                     │                                     │                                                       │
                     │   API routes (read the database only) ◀──────────────────────────────────────────────┐   │
                     └──────────────────────────────────────────────────────────────────────────────────────┼───┘
                                                                                                            │ /api/* (proxied)
                     ┌──────── frontend (Next.js 16, React 19, Tailwind 4, Recharts) ─────────┐             │
   Browser ─────────▶│  landing · dashboard · discovery · research page · analysis · compare │─────────────┘
                     │  history · calendar · methodology · system health                       │
                     └─────────────────────────────────────────────────────────────────────────┘
                                         SQLite (WAL) + data/documents (originals, hash-named)
```

## Principles

1. **Browsers never reach a public source.** Jobs fetch, normalise and store; every page reads the database.
2. **One implementation per formula.** `quant_engine` is HTTP-free and deterministic; the API, reports,
   comparisons and the e2e demo all call it.
3. **Nothing is overwritten silently.** Field observations keep every value with its source and time;
   statements are versioned; a verified period is never replaced by an unverified one from another source.
4. **Stored, not recomputed per request.** Scores carry a fingerprint (inputs + configuration + engine
   version); a new row is written only when it changes. Lists and the dashboard read stored rows.
5. **Missing means missing.** No zeros, averages or guesses; every gap carries its reason.

## Backend modules

| Path | Responsibility |
|---|---|
| `app/ingestion/http.py` | Polite client: per-host serialisation and spacing, streamed size limits, bounded retries, HEAD |
| `app/ingestion/sources/nse.py`, `sebi.py`, `bse.py` | Source adapters (parse and validate each source's own format) |
| `app/ingestion/source_registry.py` | Source authority, access mode, health |
| `app/ingestion/ipo_data_service.py` | Upserts with field-level provenance and precedence; expected dates; listing prices |
| `app/ingestion/document_service.py` | Offer-document pipeline (NSE + SEBI), OCR fallback, dedupe, backoff, dead letters, pruning |
| `app/ingestion/financial_store.py` | Persist statements (+ line-item provenance), peers, facts, classification |
| `app/ingestion/ingestion_scheduler.py` | Jobs, cross-process locks, interrupted-job recovery, rescoring after changes |
| `app/financials/pdf_tables.py`, `statement_parser.py` | Rebuild tables from word positions; periods, units, checks |
| `app/financials/ocr.py` | Tesseract via PyMuPDF for image-only pages |
| `app/financials/disclosures.py`, `industry.py` | Peers, facts, business overview; sector classifier and lender KPIs |
| `app/services/quant_engine.py`, `scoring_config.py` | Ratios, scores, risk; versioned configuration and industry profiles |
| `app/services/field_registry.py`, `completeness.py` | Field registry; per-IPO completeness, pipeline stage, sources tried |
| `app/services/ipo_service.py` | Serialisation, engine inputs, stored-score access, refresh |
| `app/api/routes/*` | REST endpoints (OpenAPI at `/api/docs`) |
| `app/cli.py`, `cli_e2e.py` | Administration and the end-to-end demonstration |

## Pipeline stages and where they are observed

| Stage | Code | Observed in |
|---|---|---|
| Discovery | `job_discover`, `job_filings` | `ingestion_jobs`, System health → jobs |
| Source resolution | `discover`, `discover_sebi`, `resolve_pdf` | completeness → *Offer document located*, sources tried |
| Download | `fetch` (HEAD, hash, dedupe) | `source_documents`, System health → documents |
| Extraction | `process` → `extract_financials` (+OCR) | `document_extractions` (every run, warnings) |
| Normalisation & validation | statement parser units, periods, accounting checks | statement `validation`, `financial_line_items` |
| Calculation & scoring | `score_ipo` → `quant_engine.compute` | `research_scores`, Score breakdown tab |
| Persistence & refresh | stored scores, cached completeness, ETags | dashboard polls every 2 min; GET responses 304 when unchanged |

## Data flow for one figure

Printed "7,552.59" (₹ million, p91, "a) Revenue from operations") → `parse_number` → ×0.1 → ₹755.259 cr
→ `financial_line_items` (raw text, unit, page) → `financial_statements.revenue` (FY2024, verified after
checks) → `FinPeriod.revenue` → revenue CAGR 29.51 % → S = 100 · (29.51 + 5) / 30 → growth component →
Q. Every arrow is visible in the UI (statement provenance dialog, Score breakdown).

## Frontend

App Router pages under `app/(app)/` share a layout (sidebar, top bar with last-sync time). Data is fetched
client-side through `/api/*` (proxied to FastAPI, so the session cookie is first-party), with
`useApi` polling where data changes (dashboard 2 min, open issues 1 min, system health 30 s) and ETag
revalidation. Design tokens (`globals.css @theme`) define surfaces, ink, brand and semantic colours;
charts use a validated categorical palette and reserved positive/negative colours.

## Database

SQLite in WAL mode, Alembic migrations (`render_as_batch` for SQLite). The schema is normalised around
companies → issues → documents → statements → line items, with observations and scores as append-only
history. A Postgres URL works through SQLAlchemy (add a driver) but has not been the tested configuration.
