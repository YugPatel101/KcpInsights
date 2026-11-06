# API documentation

Interactive OpenAPI: **http://127.0.0.1:8000/api/docs** (schema at `/api/openapi.json`). The browser
reaches the API through the Next.js origin (`/api/*` is proxied), so the session cookie stays
first-party. Every endpoint reads the database; none contacts a public source except the admin sync
and source-fetch endpoints.

## Conventions

* **Errors** always use one envelope, never a stack trace:
  `{"error": {"code": "not_found", "message": "IPO not found", "details": null}}`. Codes include
  `validation_error` (422, with field locations), `unauthorized`, `forbidden`, `not_found`,
  `rate_limited` (429 + `Retry-After`), `origin_rejected`, `timeout` (504), `internal_error`.
* **Caching:** JSON GET responses carry an `ETag`; send `If-None-Match` to get `304 Not Modified`.
* **Auth:** `POST /api/auth/login` sets an HttpOnly session cookie and returns a CSRF token; every
  state-changing request needs `X-CSRF-Token`. Cross-origin state-changing requests are rejected.
* **Pagination:** list endpoints take `page` (≥ 1) and `page_size` (1–200) and return `total`.
* **Amounts:** ₹ crore unless the field says otherwise; per-share values ₹; timestamps naive UTC ISO-8601.
* **Missing values** are `null`, never `0`; responses carry the reason where one exists.

## IPOs

| Method & path | Purpose |
|---|---|
| `GET /api/ipos` | Discovery list. Filters: `q`, `status` (pipeline,upcoming,open,closed,listed,withdrawn), `stage`, `issue_type`, `exchange`, `sector`, `industry`, `profile`, `opening_from`, `opening_to`, `min/max_issue_size`, `min/max_score`, `min_valuation`, `max_risk`, `risk_level`, `scored_only`, `min_completeness`, `data_mode`, `include_demo`; `sort` (`±open_date`, `±composite`, `±risk`, `±issue_size`, `±completeness`, `±coverage`, `±listing_date`, `name`). Scores are the stored ones (no recomputation per request) |
| `GET /api/ipos/meta` | Counts by sector, industry, stage, status, exchange, data mode |
| `GET /api/ipos/{id}` | Research-page payload: issue terms, key dates with status, subscription history, peers, disclosures, document facts, classification, documents, stored score summary, completeness summary, and `issue_facts` — one entry per key issue fact: `{key, label, value, unit, status (verified / estimated / derived / unavailable / pending), source, basis, page, document_id, url, reason}`; a missing value always carries its `reason` |
| `GET /api/ipos/{id}/financials` | Every current statement period, the engine's ratios, ratio history, superseded versions, formulas |
| `GET /api/ipos/{id}/financials/{statement_id}/provenance` | Line items as printed (raw label, text, unit, page) and the accounting checks |
| `GET /api/ipos/{id}/scores` | Full engine result: metrics with inputs and formulas, components, Q, risk (with governance sub-score), applicability, period sources, warnings |
| `GET /api/ipos/{id}/scores/history` | Every stored score row (configuration version, fingerprint) |
| `GET /api/ipos/{id}/completeness` | Field-by-field completeness with source, period, freshness and reason; pipeline stages; sources tried |
| `GET /api/ipos/{id}/peers` | Offer-document peers with quartiles, price dates, staleness, latest close; similar IPOs on record; selection rationale |
| `GET /api/ipos/{id}/valuation-sensitivity` | P/E, P/B, EV/EBITDA, P/S and scores at each end of the band and the final price |
| `GET /api/ipos/{id}/sources`, `/provenance`, `/changes`, `/subscription` | Source records used, field-level provenance, change log, subscription snapshots |
| `POST /api/ipos/compare` | `{"ipo_ids": [..2–4..]}` → side-by-side metrics, components, risk, completeness |
| `POST /api/ipos/{id}/analyze` | Recompute and store now (rate-limited) |
| `PATCH /api/ipos/{id}` | Research notes and description (importer or admin) |
| `POST/DELETE /api/ipos/{id}/watch` | Watchlist (signed in) |
| `GET /api/ipos/upcoming`, `/open`, `/recently-listed`, `GET /api/market/overview` | Convenience lists |

## Research and analytics

| Method & path | Purpose |
|---|---|
| `GET /api/dashboard/summary` | Stage counts, open/upcoming, awaiting, recently closed/listed, pipeline (SEBI filings), calendar (21 days), activity by month, score/risk/sector distributions, data health, sources, recent field changes |
| `GET /api/calendar?start=&end=&issue_type=` | Opening, closing, allotment, refund, demat-credit and listing events, each `confirmed` or `estimated` |
| `GET /api/history?issue_type=&sector=&since=` | Listed IPOs with listing open/high/low/close, listing gain, closing return, subscription, point-in-time score; summaries by sector, type and size; score-vs-outcome pairs with Spearman ρ |
| `GET /api/industries` | Sectors on record with profile and median ratios (benchmarks, with n); industry profiles |
| `GET /api/methodology` | Active configuration, formulas, labels, disclaimer, parser version, configuration history |
| `GET /api/fields` | Field registry (typed response model) |
| `GET /api/scoring/config`, `/api/scoring/configs` | Active and all configuration versions |
| `POST /api/scoring/configs`, `POST /api/scoring/configs/{version}/activate` | Admin: publish/activate an immutable version (validated) |

## Documents

| Method & path | Purpose |
|---|---|
| `GET /api/documents?ipo_id=` | Documents with source, hash, size, extraction status/method, parser version, retries |
| `GET /api/documents/{id}/file` | The stored original PDF, by id only (never by path); 404 when pruned |
| `GET /api/documents/{id}/extractions` | Every extraction run with checks and warnings |
| `POST /api/documents` | Upload a PDF/TXT (signed in, rate-limited, size/page-limited, type-checked) |
| `POST /api/documents/search` | Keyword (BM25) search over document text |
| `POST /api/admin/documents/{id}/reprocess` | Admin: re-run extraction on the stored original |

## Data pipeline and system

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness and database check |
| `GET /api/system/health` | Scheduler, sources, jobs in 24 h, documents by source/status, OCR availability, dead letters, backing-off documents, pipeline funnel, completeness, integrity |
| `GET /api/data/freshness`, `/api/data/sync-status`, `/api/data/exceptions` | Last sync, stale records, job log, extraction failures, statements needing review, source conflicts |
| `POST /api/admin/data-sync` | Admin: `{"job": "all" | "discover" | "details" | "subscriptions" | "listings" | "filings" | "documents" | "peers" | "health"}` → 202, runs in the background |
| `POST /api/sources/fetch` | Admin: fetch one official URL (allowlisted hosts, HTTPS, size-capped) |

## Workspace and auth

`POST /api/auth/register|login|logout`, `GET /api/auth/me`; `GET /api/watchlist`, `PATCH /api/watchlist/{ipo_id}`;
`POST /api/reports/generate`, `GET /api/reports`, `GET/DELETE /api/reports/{id}` (owner only — other users get 404);
`POST /api/imports/financials`, `GET /api/imports`, `GET /api/imports/templates/{kind}`.

## Examples

```bash
curl -s "http://127.0.0.1:8000/api/ipos?stage=open,upcoming&sort=-completeness&page_size=5"
```
```bash
curl -s http://127.0.0.1:8000/api/ipos/11/completeness | python3 -m json.tool | head -40
```
```bash
curl -s "http://127.0.0.1:8000/api/history?issue_type=mainboard" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
```
