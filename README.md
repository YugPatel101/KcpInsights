# KcpInsights

**Indian IPO research built from the prospectus up.** KcpInsights discovers NSE mainboard and SME IPOs
(and companies whose offer documents SEBI has just published), downloads each offer document, extracts
and reconciles the restated balance sheet, profit and loss and cash flow statements, computes standard
financial ratios with industry-aware rules, and scores every issue with a published, versioned
methodology. Every figure traces back to its page; every gap says why it is a gap.

No paid services, API keys or AI models; no manual data entry. Runs fully on one machine.

> KcpInsights provides educational financial research and quantitative analysis. Scores are
> methodology-dependent, data may be incomplete or delayed, and the platform does not provide
> personalized investment advice or guarantee IPO performance.

## Features

* **Automatic discovery** — NSE upcoming, open and listed issues (mainboard and SME); SEBI DRHP/RHP
  filings, including companies NSE has not announced yet. Idempotent upserts with field-level
  provenance, source precedence and a change log.
* **Prospectus intelligence** — RHP archives from NSE (SEBI copy as fallback, duplicates detected by
  SHA-256), statement tables rebuilt from PDF word positions, units converted to ₹ crore, periods
  validated, accounting identities checked; local Tesseract OCR for scanned pages. Every figure is
  stored with its page and the text as printed.
* **Quantitative engine** — 40+ ratios (profitability, growth, liquidity, leverage, efficiency, cash
  flow, valuation on post-issue shares), five component scores, a fundamental score Q, a separate risk
  score with a governance sub-score, and **industry profiles** so lenders are not judged on current
  ratios or EBITDA.
* **Peers** — the issuer's own listed peers with quartile benchmarks, price dates, staleness flags and
  the latest official close; similar IPOs on record.
* **Data completeness** — 55 registry fields per IPO, each available / estimated / unverified /
  unavailable (with reason) / not applicable / not yet expected; analysis readiness; pipeline stage.
* **Listing history** — listing-day open, high, low, close from the official bhavcopy; listing gain and
  closing return; sector, type and size summaries; point-in-time score-versus-outcome analysis.
* **Product UI** — market overview, discovery with filters and pagination, research page (overview,
  statements, ratios, valuation, peers, risk, score breakdown, completeness, documents, sources),
  financial-analysis workspace, comparison, calendar with confirmed/estimated dates, methodology and
  system health.

## Technology

| Layer | Stack |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, APScheduler, httpx, PyMuPDF, Tesseract (optional), Argon2 |
| Database | SQLite (WAL) |
| Frontend | Next.js 16 (App Router), React 19, Tailwind CSS 4, Recharts 3, Zod |
| Quality | pytest (89), vitest (14), ruff (incl. bandit rules), mypy, ESLint, TypeScript |

## Architecture

```
 NSE JSON · NSE archives · SEBI filings
            │  polite client (one request per host, ≥2.5 s apart, size caps, no anti-bot bypass)
            ▼
 scheduled jobs ──▶ issue upserts (provenance, precedence) ──▶ document pipeline
                                                               discover → HEAD → download → hash/dedupe
                                                               → extract (+OCR) → validate → store
            ▼
 quant engine (pure, versioned config, industry profiles) ──▶ stored scores · cached completeness
            ▼
 FastAPI (reads the database only) ◀── /api proxy ── Next.js app ◀── browser
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start (macOS / Linux)

Prerequisites: Python 3.11+, Node.js 20+, npm. Optional: `brew install tesseract` (or
`sudo apt install tesseract-ocr`) to read scanned prospectuses.

```bash
scripts/dev.sh
```

Open http://localhost:3000 (API docs: http://127.0.0.1:8000/api/docs). The first run creates
`backend/.venv`, installs dependencies, migrates the database and loads a clearly labelled synthetic
demo, which is hidden automatically once real data arrives. The scheduler starts syncing NSE about 15
seconds after the API starts and reads offer documents from about 5 minutes after.

Manual setup:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && cp .env.example .env && .venv/bin/python -m app.cli migrate
```
```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000
```
```bash
cd frontend && npm install && npm run dev
```

Useful commands (from `backend/`): `python -m app.cli sync`, `process-documents --limit 20`,
`backfill-history --days 365`, `reclassify`, `refresh-scores`, `create-admin`, `e2e-demo BCSSL`.

## Screenshots

Run the app and capture: `/` (landing), `/dashboard`, `/ipos`, `/ipos/<id>` (try the *Peers* and *Data
completeness* tabs), `/history`, `/methodology`, `/data`. The pages render from live data, so
screenshots reflect the current market.

## Tests

```bash
cd backend && .venv/bin/python -m pytest && .venv/bin/ruff check app tests && .venv/bin/mypy app
```
```bash
cd frontend && npm test && npm run lint && npm run typecheck && npx next build
```

What is covered and how the last run went: [docs/TESTING.md](docs/TESTING.md). A full real-IPO run —
discovery, download, extraction, validation, ratios, score, provenance and an idempotent second run —
is recorded in [docs/E2E_DEMONSTRATION.md](docs/E2E_DEMONSTRATION.md).

## Data sources

| Source | Access | Provides |
|---|---|---|
| NSE public issue information | automatic | issue terms, dates, subscription, final price, listing date |
| NSE bhavcopy and equity lists | automatic | listing-day open/high/low/close; peer prices |
| Offer documents (NSE archives) | automatic | restated statements, peers, disclosures, business overview, industry |
| SEBI DRHP/RHP filings | automatic | new filings; fallback prospectus copy |
| BSE | blocked for automated access | manual import |

Full detail, verification dates and request discipline: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
Field-by-field sources and checks: [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).

## Methodology

```
Q = 0.25·Profitability + 0.25·Growth + 0.20·Financial health + 0.15·Cash flow + 0.15·Valuation
```

Each component is a weighted average of ratios normalised to 0–100 between published reference
values; Q is issued only when the required components are computable from verified statements; risk
(0–100, higher = more risk) is separate. Weights are educational judgements, not fitted predictors.
[docs/SCORING_METHODOLOGY.md](docs/SCORING_METHODOLOGY.md) · [docs/FINANCIAL_FORMULAS.md](docs/FINANCIAL_FORMULAS.md) ·
the in-app **Methodology** page renders the active configuration.

## Limitations

* BSE refuses automated requests; BSE-only issues need a manual import.
* Only the first page of SEBI's filing lists is read; litigation and promoter holding are not extracted.
* Prospectuses that defeat both the text layer and OCR stay *unavailable*; OCR figures are never scored.
* Lenders' asset-quality ratios come from unverifiable KPI tables, so a lender's Q stays incomplete.
* The industry classifier is phrase-based and declines close calls; sector names mix NSE's labels with
  the classifier's.
* Listing history covers issues discovered so far (backfill extends it); results are descriptive, not predictive.
* Data is fresh only while the API process runs; free sleeping hosts cannot run the pipeline 24/7.

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Data sources](docs/DATA_SOURCES.md) · [Data dictionary](docs/DATA_DICTIONARY.md) ·
[Scoring methodology](docs/SCORING_METHODOLOGY.md) · [Financial formulas](docs/FINANCIAL_FORMULAS.md) ·
[API](docs/API_DOCUMENTATION.md) · [Deployment](docs/DEPLOYMENT.md) · [Security](docs/SECURITY.md) ·
[Testing](docs/TESTING.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Technical audit](docs/AUDIT.md) ·
[End-to-end demonstration](docs/E2E_DEMONSTRATION.md)
