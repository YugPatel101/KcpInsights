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

## Live data (automatic)

The API process runs a scheduler that fetches public exchange data, normalises it, and stores it with
field-level provenance. Browsers and the AI read only the database — polling a page never contacts NSE.

| Source | Status (verified 2026-10-29) | Fields |
|---|---|---|
| NSE public issue JSON (`api/all-upcoming-issues`, `api/ipo-current-issue`, `api/public-past-issues`, `api/ipo-detail`, `api/ipo-active-category`) | ✅ automatic — honest User-Agent, no cookies; robots.txt allows | company, symbol, mainboard/SME, open/close dates, price band, lot size, face value, final issue price, **actual** listing date, registrar, lead managers, RHP & basis-of-price links, issue-size sentence (→ ₹ size), consolidated subscription by category with NSE's "Updated as on" time, industry |
| NSE daily bhavcopy (`nsearchives…/BhavCopy_NSE_CM_…csv.zip`) | ✅ automatic | listing-day **open** (= listing price) and close; cross-checked against the issue price |
| NSE quote API | ❌ "Access Denied" (anti-bot) — not used | — |
| BSE API | ❌ refused/redirected — not used | manual import for BSE-only issues |
| SEBI offer documents, company IR | manual | upload PDFs; import financials (CSV/JSON) |

Not available from any connected source (stay **unavailable**, never estimated): financial statements,
post-issue share count, promoter holding, peers, GMP. Live IPOs therefore show an *incomplete*
research score until you import financials from the offer document.

| Job | Default interval | What it does |
|---|---|---|
| discover | 6 h | upcoming + open + recently listed (≤120 days); upserts by symbol |
| details | 6 h | per-issue details and subscription (≤15 issues/run) |
| subscriptions | 20 min | only while an issue is open; makes **no** request otherwise |
| listings | 45 min | confirms listing dates; fetches one bhavcopy per listing day |
| health | 30 min | source health; BSE probe at most daily |
| documents | daily | opt-in RHP download & indexing |

Requests are serialised per host with ≥2.5 s spacing, bounded retries with exponential backoff
(never retried on 401/403/429), response caching, and a cross-process database lock per source.
Jobs left running by a crashed process are marked *interrupted* and their locks reclaimed at startup.
A failed source never deletes stored data; stale records are flagged instead.

**Provenance & precedence.** Every field change is an observation (source, URL, first seen, last
verified, status, basis). Higher-authority sources win; equal-authority disagreements apply the newest
value and are flagged as conflicts; lower-authority values and estimates never overwrite sourced data.
Date/price/listing changes are kept in a change log shown on the IPO page.

**Dates.** Allotment, refund, demat-credit and listing dates are *estimated* from SEBI's T+3 timeline
(weekends skipped, exchange holidays not applied) and always labelled "expected" until NSE confirms the
actual listing date. An issue never shows as *listed* on an expected date. Listing return =
(listing-day open − final issue price) / final issue price, only when both are verified.

**Statuses.** `verified` (official source, parsed and validated) · `imported` (= user_imported) ·
`estimated` (derived) · `synthetic` (= synthetic_demo) · `secondary_source` · `unavailable`.
Demo IPOs are hidden automatically once real data exists (`?include_demo=true` shows them).

Manual operations:

```bash
cd backend && .venv/bin/python -m app.cli sync            # all jobs now
```
```bash
cd backend && .venv/bin/python -m app.cli sync listings   # one job
```
```bash
cd backend && .venv/bin/python -m app.cli worker          # scheduler only (with KCP_SCHEDULER_ENABLED=false on the API)
```

Verify it end to end: open **Data pipeline** (`/data`) for job history, per-source health, stale
records and the field-change log; an admin can press **Run sync**. On an IPO page, the key-dates panel
marks verified vs estimated dates and shows a *changed* badge when NSE moves a date; the Sources tab
lists field-level provenance. When an expected listing date passes, the listings job confirms it from
NSE and the page switches to the actual date and verified listing price.

Endpoints: `GET /api/market/overview`, `/api/ipos/upcoming`, `/api/ipos/open`, `/api/ipos/recently-listed`,
`/api/ipos/{id}/subscription`, `/api/ipos/{id}/changes`, `/api/ipos/{id}/provenance`, `/api/data/freshness`,
`/api/data/sync-status`, `POST /api/admin/data-sync` (admin). GET responses carry ETags (304 when unchanged).

## Data modes

| Mode | What | Label |
|---|---|---|
| A — Demo | Synthetic fixture, 10 fictional companies with dates relative to today | `SYNTHETIC` / `demo` everywhere; earns 0 % evidence coverage |
| B — Imported | Your JSON bundles / CSV statements from offer documents | `imported` (admins may mark `verified`) |
| C — Source-connected | Automatic NSE ingestion (above) plus admin fetch of single official document URLs | `verified` / `estimated` per field, source URL + retrieval time |

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
ollama serve &                    # or open the Ollama app
ollama pull qwen2.5:3b            # ~1.9 GB download, needs ~4 GB free RAM
ollama pull nomic-embed-text      # ~274 MB, optional: semantic document search
cd backend && .venv/bin/python -m app.cli embed   # add embeddings to documents stored before the model existed
```

Low-memory machines: set `KCP_OLLAMA_USE_SMALL_MODEL=true` in `backend/.env` (`qwen2.5:1.5b`).
Any Ollama instruction model works via `KCP_OLLAMA_MODEL`. Settings → **Re-check providers**
confirms health; the app never claims a model is available until the health check passes and the
model is present.

The agent answers live questions — "Which IPOs open next week?", "When is X expected to list? Has it
changed?", "Latest subscription?", "Show the source for that date" — with tools `search_ipos`,
`get_latest_ipo_status`, `get_listing_schedule`, `get_subscription_data`, `compare_ipos`,
`get_quantitative_score`, `get_source_provenance` and others. If a record it needs is stale it may make
**one** bounded refresh request to NSE before answering. Each point is labelled *source*, *calculated*,
*interpretation* or *hypothetical*, and cites stored evidence with links. Tool calls are audited and
visible under each answer. Token streaming is not used: answers are checked before they are shown.

**What the model does, and why it does so little.** Tested on an 8 GB Mac with `qwen2.5:3b` (Oct 2026),
the model wrote fluent answers but attached real dates to the wrong events (an allotment date as the
opening date), wrote subscription multiples as percentages, invented comparisons ("higher quality
score" when neither score existed), and in reports read a data-quality *risk* of 100 as "a solid
foundation". So the work is split:

* The **engine** writes every cited point, from tool results, with correct labels and units.
* The **model** may request extra tools (≤ 3 planning rounds, ≤ 3 tools each), then writes a 1–3
  sentence summary *from the engine's points*. The summary is rejected — and the engine's summary is
  used — if it contains a number not in the tool results, a date that is not in them or is described as
  the wrong event (e.g. "opens" on an allotment date), a multiple written as a percentage, or advice-like
  wording. Estimated values it states without a qualifier are labelled "(estimated)" / "(expected)".
* In the UI the summary is marked as model-written; the points underneath are the verified record.
* **Report narratives** (model-written interpretive paragraphs) are **off by default**
  (`KCP_AI_REPORT_NARRATIVES=false`): in testing about half of them misread a score scale. Enable them
  only with a larger model and review the output.

In live tests after these changes, typical chat answers took 7–15 s and the summaries matched the data;
a short summary can still word something loosely (once: "2.67x for all categories" for a 2.67x *total*),
which is why it sits above the cited points rather than replacing them. Without a model, everything
uses the **deterministic research engine**. The model never computes scores.

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
cd backend && .venv/bin/python -m pytest      # 93 tests (ingestion uses captured NSE payloads, no network)
cd backend && .venv/bin/ruff check . && .venv/bin/mypy app
cd frontend && npm test && npm run lint && npm run typecheck && npx next build
```

Core tests use mocked providers — no network, no downloaded model. They cover hand-calculated
formulas, normalisation bounds, CAGR edge cases, unit conversion, valuation with negative
earnings and thin peer sets, risk aggregation and double-count rules, coverage, reproducibility,
config validation, scenarios, imports, migrations, auth/CSRF/rate limits, authorization boundaries,
agent tool validation, model timeouts/invalid output/fallback, fabricated numbers and citations,
misattributed dates, wrong units, unlabelled estimates, advice wording, partly embedded document sets,
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
| Backend | Render free web service (Docker: `backend/Dockerfile`) or Hugging Face Spaces (Docker) | Sleeps when idle (cold starts) — **the scheduler does not run while asleep, so data is not continuously updated**; **ephemeral disk — SQLite is wiped on restart/redeploy**; no Ollama (deterministic engine only); NSE may treat cloud IP ranges differently than a home connection |
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
