# Deployment

## Guaranteed baseline: local full mode (free)

Everything — API, scheduler, SQLite database, stored prospectuses, OCR and the web app — runs on one
machine with no accounts, keys or paid services.

```bash
scripts/dev.sh
```

Prerequisites: Python 3.11+, Node.js 20+, npm; optional **Tesseract** for scanned prospectuses
(`brew install tesseract` on macOS, `sudo apt install tesseract-ocr` on Debian/Ubuntu). Without it the
pipeline still runs and reports scanned pages instead of reading them.

The scheduler lives in the API process: data stays current **only while the machine is on and the
process is running**. On a computer that sleeps, jobs resume (and catch up) when it wakes; nothing needs
manual attention.

### Production-like local run

```bash
cd backend && .venv/bin/python -m app.cli migrate && KCP_ENVIRONMENT=production .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```
```bash
cd frontend && npx next build && KCP_API_URL=http://127.0.0.1:8000 npx next start --port 3000
```

Keep it running with your OS service manager (launchd, systemd) or `tmux`. Separate the scheduler from
the API if you run several API workers: set `KCP_SCHEDULER_ENABLED=false` on the API and run one
`python -m app.cli worker`.

## Free hosting — what works and what does not

| Piece | Free option | Limits that matter here |
|---|---|---|
| Web app | Vercel Hobby, Netlify free | Non-commercial (Vercel Hobby). Set `KCP_API_URL` to the backend URL |
| API + scheduler | Render free web service or Hugging Face Spaces (Docker, `backend/Dockerfile`) | **Sleeps when idle — the scheduler does not run while asleep**, so data is not refreshed continuously; **ephemeral disk** — SQLite and prospectuses are lost on restart or redeploy; NSE may treat cloud IP ranges differently from a home connection |
| Database | Neon or Supabase free Postgres (`KCP_DATABASE_URL`, add `psycopg[binary]`) | Storage and compute caps; Postgres is not the tested configuration |

**Honest summary:** a free, sleeping host can serve the web app and a read-only snapshot, but it
**cannot** run the 24/7 pipeline. For unattended operation use an always-on machine you control (an old
laptop, a Raspberry Pi 4/5 with 4 GB+, a home server) running the local mode above. Hosts that require
a credit card are not recommended here. Free-tier terms change; check each provider.

### Docker (API)

```bash
cd backend && docker build -t kcpinsights-api . && docker run -p 8000:8000 -v kcp-data:/app/data kcpinsights-api
```

The image includes Tesseract, migrates on start, loads the labelled demo only into an empty database,
and has a health check on `/api/health`. Mount `/app/data` on a persistent volume.

## Configuration (environment variables, prefix `KCP_`)

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | development | `production` enables Secure cookies and HSTS |
| `DATABASE_URL` | `sqlite:///backend/data/kcpinsights.db` | SQLAlchemy URL |
| `DATA_DIR` | `backend/data` | documents, cache, uploads |
| `CORS_ORIGINS` | localhost:3000 | allowed browser origins (comma-separated) |
| `SCHEDULER_ENABLED` / `INGEST_ENABLED` | true / true | run jobs in the API process / allow upstream requests at all |
| `INGEST_MIN_REQUEST_INTERVAL_SECONDS` | 2.5 | spacing per host |
| `INGEST_*_MINUTES` | see DATA_SOURCES.md | job intervals |
| `INGEST_MAX_DOCUMENTS_PER_RUN` | 3 | documents processed per hourly run |
| `INGEST_SEBI_FILINGS` | true | SEBI DRHP/RHP discovery |
| `DOCUMENTS_MAX_TOTAL_MB` | 1500 | originals beyond this are pruned (extracted data kept) |
| `DOCUMENT_MAX_ATTEMPTS` | 5 | retries before a document becomes a dead letter |
| `DETAILS_RECHECK_DAYS` | 7 | how often an issue still missing an NSE-published field is re-checked |
| `INGEST_ENRICHMENT_MINUTES` | 360 | gap-filling job: equity lists, shareholding filings, offer-term re-reads |
| `INGEST_MAX_SHAREHOLDING_PER_RUN`, `INGEST_MAX_OFFER_TERM_REREADS_PER_RUN` | 15, 10 | per-run limits of that job |
| `OCR_ENABLED`, `OCR_MAX_PAGES`, `OCR_DPI`, `OCR_TIME_BUDGET_SECONDS` | true, 150, 300, 600 | local OCR limits |
| `MAX_UPLOAD_MB`, `MAX_PDF_PAGES` | 20, 600 | upload limits |
| `LOG_FORMAT` | text | `json` writes one JSON object per log line (time, level, logger, message), redaction unchanged |

Frontend: `KCP_API_URL` (where `/api/*` is proxied).

## Operations

| Task | Command (from `backend/`) |
|---|---|
| Migrate | `.venv/bin/python -m app.cli migrate` |
| First administrator | `.venv/bin/python -m app.cli create-admin` |
| Sync everything now | `.venv/bin/python -m app.cli sync` |
| Catch up on queued prospectuses | `.venv/bin/python -m app.cli process-documents --limit 20` |
| Import a year of listed issues and listing prices | `.venv/bin/python -m app.cli backfill-history --days 365` |
| Re-run the industry classifier | `.venv/bin/python -m app.cli reclassify` |
| Fill every missing issue field now (NSE details, offer terms, equity lists, shareholding filings) | `.venv/bin/python -m app.cli fill-gaps` |
| Recompute stored scores | `.venv/bin/python -m app.cli refresh-scores` |
| End-to-end demonstration | `.venv/bin/python -m app.cli e2e-demo BCSSL --report ../docs/E2E_DEMONSTRATION.md` |
| Backup | `sqlite3 data/kcpinsights.db ".backup data/backup.db"` (never copy the live file) |
