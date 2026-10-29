# KcpInsights

Educational IPO research platform for Indian mainboard and SME issues: transparent quantitative
scoring, provenance-tracked data, scenario analysis, document retrieval and a tool-using research
agent — **runs entirely on free, open-source software**, offline after setup, with an optional
local AI model.

> KcpInsights is for education. Scores are rule-based summaries of stored inputs, not investment
> advice, not forecasts and not probabilities of listing gains.

## Quick start (macOS / Linux)

Prerequisites: Python 3.11+, Node.js 20+, npm. No API keys, accounts or AI model needed.

```bash
scripts/dev.sh
```

Open http://localhost:3000. The first run creates `backend/.venv`, installs dependencies, migrates
the SQLite database and loads the **synthetic demo fixture** (10 fictional companies, clearly
labelled). API docs: http://127.0.0.1:8000/api/docs.

Port 8000 busy? `KCP_API_PORT=8001 scripts/dev.sh` (`KCP_WEB_PORT` for the web port).
Start without demo data: `KCP_SKIP_DEMO=1 scripts/dev.sh`.

### Manual setup

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m app.cli migrate          # Alembic migrations
.venv/bin/python -m app.cli seed-demo        # optional synthetic demo (--reset refreshes dates)
.venv/bin/python -m app.cli create-admin     # optional first administrator (prompts for password)
.venv/bin/uvicorn app.main:app --port 8000

cd ../frontend
npm install
npm run dev                                  # proxies /api/* to KCP_API_URL (default 127.0.0.1:8000)
```

Other CLI commands: `reset-password <email>`, `ingest <file.pdf> --ipo-id N --url …`,
`train-model [--synthetic]`.

## What's inside

```
backend/                     FastAPI + SQLAlchemy + Alembic (Python)
  app/services/
    scoring_config.py        versioned weights & thresholds (single source of truth)
    normalization.py         bounded linear normalisation, percentiles
    financial_metrics.py     margins, ROE/ROCE, CAGR, cash conversion, leverage (edge-case rules)
    scoring_engine.py        Q, V, R, composite S, evidence coverage C — pure & deterministic
    scenario.py              bear/base/bull equity-value scenarios
    prediction.py            optional listing-outcome baselines + chronological backtests
    import_service.py        validated JSON bundle / CSV import with provenance & versioning
    demo_seed.py             Mode A synthetic fixture (fictional companies)
    rag.py                   PDF/text ingestion, page-cited chunks, embeddings or BM25, injection flags
    llm_provider.py          Ollama (local) / optional OpenAI-compatible / deterministic fallback
    source_adapters.py       Mode C allow-listed official-document fetcher (SSRF-safe, robots.txt)
    report_service.py        12-section source-linked research reports
  app/agents/                bounded tool-using research agent, 13 typed tools, output validation
  app/api/routes/            REST endpoints (OpenAPI at /api/docs)
  alembic/                   migrations
  tests/                     pytest (engine hand-calculations, API, auth, agent, RAG, SSRF, …)
frontend/                    Next.js 16 App Router + React 19 + Tailwind 4 + Recharts + Zod + RHF
  app/(app)/                 dashboard, ipos, ipos/[id], analysis, compare, workspace, reports,
                             watchlist, import, settings
  components/                KcpInsights UI (existing identity preserved), charts, IPO panels
  lib/                       typed API client, auth context, formatters, Zod schemas
  tests/                     vitest
docs/METHODOLOGY.md          every formula, weight, threshold and edge rule
scripts/dev.sh               one-command local launcher
```

The browser only talks to the Next.js origin; `/api/*` is proxied to FastAPI, so the session
cookie is first-party (HttpOnly, SameSite=Lax, Secure in production).

## Data modes

| Mode | What | Label |
|---|---|---|
| A — Demo | Synthetic fixture, 10 fictional companies with dates relative to today | `SYNTHETIC` / `demo` everywhere; earns 0 % evidence coverage |
| B — Imported | Your JSON bundles / CSV statements from offer documents | `imported` (admins may mark `verified`) |
| C — Source-connected | Admin fetches an official SEBI/NSE/BSE URL; ingested as a document | source URL + retrieval time |

### Importing real research (Mode B)

1. Sign in → **Import data** → download the JSON bundle or CSV template.
2. Fill it from the RHP/DRHP (restated financials, issue structure, peers, risk factors), giving
   each record a `source_key` with a title and URL.
3. Upload → **Validate (dry run)** → review errors/warnings (missing fields, invalid dates, unit
   problems, duplicates, accounting checks) → **Commit**.

Units (`crore`, `lakh`, `million`, `billion`, `thousand`, `rupees`) are converted to INR crore with
the raw values preserved. Missing fields stay missing. A verified period is never overwritten by
unverified data; changed values create a new version. Upload offer-document PDFs on the IPO page
(Documents tab) to enable cited retrieval.

NSE frequently blocks automated requests; KcpInsights never bypasses CAPTCHAs, logins or
anti-bot controls — download manually and upload instead.

## Optional local AI (free)

```bash
# install Ollama from https://ollama.com, then:
ollama pull qwen2.5:3b            # ~2 GB, needs ~4 GB free RAM
ollama pull nomic-embed-text      # optional: semantic document search
```

Low-memory machines: set `KCP_OLLAMA_USE_SMALL_MODEL=true` in `backend/.env` (`qwen2.5:1.5b`).
Any Ollama instruction model works via `KCP_OLLAMA_MODEL`. Settings → **Re-check providers**
confirms health; the app never claims a model is available until the health check passes and the
model is present.

Without a model, the agent and reports use the **deterministic research engine** (templated from
the same tools; labelled as non-generative). With a model, the agent may request extra tools for
≤ 6 steps; its answers are validated — citations must resolve to tool evidence, numbers must
appear in tool results, otherwise points are dropped or the deterministic answer is used. The
model never computes scores.

## How scoring works

```
Q = 0.25·Profitability + 0.20·Growth + 0.20·Cash flow + 0.20·Balance sheet + 0.15·Stability
V = 100 · clip((p75 − IPO multiple) / (p75 − p25))       vs. a stated, dated peer set
R = 0.25·Financial + 0.20·Valuation + 0.20·Governance + 0.20·Market + 0.15·Data quality
S = 0.45·Q + 0.30·V + 0.25·(100 − R)                     not calculated if any part is missing
C = 100 · Σ wᵢIᵢ / Σ wᵢ                                   admissible-evidence coverage
```

Each metric is normalised with documented thresholds; zero/negative earnings, negative equity,
missing periods and stale data are handled by explicit rules. Full detail:
[docs/METHODOLOGY.md](docs/METHODOLOGY.md). Every score breakdown in the UI (Quant scores tab,
Quant analysis page) shows value → formula → thresholds → periods → source.

## Tests and checks

```bash
cd backend && .venv/bin/python -m pytest      # 66 tests
cd backend && .venv/bin/ruff check . && .venv/bin/mypy app
cd frontend && npm test && npm run lint && npm run typecheck && npx next build
```

Core tests use mocked providers — no network, no downloaded model. They cover hand-calculated
formulas, normalisation bounds, CAGR edge cases, unit conversion, valuation with negative
earnings and thin peer sets, risk aggregation and double-count rules, coverage, reproducibility,
config validation, scenarios, imports, migrations, auth/CSRF/rate limits, authorization boundaries,
agent tool validation, model timeouts/invalid output/fallback, fabricated numbers and citations,
prompt injection via documents, retrieval thresholds, look-ahead-free features, and SSRF.

## Security

Argon2id password hashing; opaque session tokens stored as SHA-256; HttpOnly SameSite=Lax cookies
(Secure in production); idle + absolute expiry; CSRF token on every state-changing request plus an
Origin check; per-user authorization on reports, conversations and watchlists (other users get
404); rate limits on login, registration, agent, reports, imports and uploads; upload size/type
limits and PDF page caps; SQLAlchemy ORM only (no raw SQL from input); model output rendered as
text, never HTML; SSRF-safe allow-listed fetching; secrets only from environment; sensitive values
redacted from logs; audit log for auth, imports, reports, edits, config changes and every agent
tool call. The agent has no filesystem, shell, network or SQL access.

**Known limitations:** rate limiting is in-process (single worker); no e-mail verification or
self-service password reset (use `app.cli reset-password`); no MFA; SQLite suits single-user/local
use; `pip-audit` / `npm audit` are not wired into CI; PDF parsing uses pypdf without a sandbox.

## Free deployment options

Honest summary: **the best fully-free setup is local** (`scripts/dev.sh`), which includes free local AI.

| Piece | Free option | Restrictions (verify current terms) |
|---|---|---|
| Frontend | Vercel Hobby or Netlify free | Non-commercial (Vercel Hobby); set `KCP_API_URL` to the backend URL |
| Backend | Render free web service (Docker: `backend/Dockerfile`) or Hugging Face Spaces (Docker) | Sleeps when idle (cold starts); **ephemeral disk — SQLite is wiped on restart/redeploy**; no Ollama (deterministic engine only) |
| Database | Neon or Supabase free Postgres (`KCP_DATABASE_URL`) | Storage/compute caps; add a Postgres driver (`psycopg[binary]`) |

For a cloud deployment set `KCP_ENVIRONMENT=production` and add the frontend origin to
`KCP_CORS_ORIGINS`. Hosts that require a credit card (e.g. Oracle Cloud, Fly.io) are not
recommended here. Free-tier terms change; check each provider before relying on it.

## Troubleshooting

* **"Cannot reach the KcpInsights API"** — backend not running or on another port; start
  `scripts/dev.sh` or set `KCP_API_URL`.
* **Port already in use** — `KCP_API_PORT=8001 scripts/dev.sh`.
* **AI shows "deterministic"** — Ollama not running (`ollama serve`) or model not pulled; Settings
  shows the exact reason.
* **Demo dates look old** — `backend/.venv/bin/python -m app.cli seed-demo --reset` (in `backend/`).
* **Valuation "unavailable"** — fewer than 3 dated peers with a positive multiple, or earnings not
  positive; the Quant scores tab lists each attempt and reason.
* **Import rejected** — run a dry run and read the validation report; dates must be `YYYY-MM-DD`.
