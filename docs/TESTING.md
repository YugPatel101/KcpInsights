# Testing

No test touches a live website. Network calls are mocked with `httpx.MockTransport`, prospectuses are
generated locally (`backend/tests/rhp_builder.py`), and saved NSE and SEBI pages live in
`backend/tests/fixtures`. Every test gets a fresh SQLite database built by the Alembic migrations.

## Commands

```bash
cd backend && .venv/bin/python -m pytest
```
```bash
cd backend && .venv/bin/ruff check app tests && .venv/bin/mypy app
```
```bash
cd frontend && npm test && npm run lint && npm run typecheck
```
```bash
cd frontend && npx next build
```
```bash
cd backend && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic upgrade head && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic downgrade base && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic upgrade head && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic check
```

Stop `scripts/dev.sh` before `next build` — both use `frontend/.next`.

## Results of the last run (31 Oct 2026)

| Check | Result |
|---|---|
| Backend tests (pytest) | **89 passed** |
| Frontend unit tests (vitest) | **14 passed** |
| ruff (incl. bandit `S` rules) · mypy (55 modules) | clean · no issues |
| ESLint · TypeScript `--noEmit` | clean · clean |
| `next build` | success, 18 routes |
| Alembic upgrade → downgrade base → upgrade → `check` | 5 migrations each way; models match |
| End-to-end demonstration on a real IPO | see [E2E_DEMONSTRATION.md](E2E_DEMONSTRATION.md) |

## What the tests cover

| File | Tests | Covers |
|---|---|---|
| `test_quant_engine.py` | 14 | Every core ratio against hand calculations (ROE/ROCE with average balances, margins, CAGR and its not-meaningful cases, YoY, liquidity, leverage incl. zero interest and negative equity, OCF/PAT, FCF, P/E, P/B, EV/EBITDA on post-issue shares); normalisation; component and overall scores; coverage thresholds; renormalisation; basis selection; exclusion of unverified periods; peer medians; risk aggregation; price sensitivity; configuration validation; **risk is not scored from data quality alone** (regression) |
| `test_platform.py` | 22 | New ratios (ROA, gross margin, EBITDA/EPS CAGR, debt/assets, capex intensity, receivable/inventory days, P/S) and their refusal cases; peer quartiles; **lender profile** (not-applicable ratios, excluded components, Q withheld); profiles leave general scores unchanged; bad profile weights rejected; engine version in the fingerprint; industry classifier incl. close calls; business overview; **SEBI** listing parser on saved pages, discovery, pipeline issues, fallback-only download, SHA-256 duplicates; exponential backoff and dead letters; **completeness** (every gap has a reason; pending vs unavailable); lists read stored scores (engine patched to fail); new endpoints; **listing history** with point-in-time exclusion; Spearman; OCR disabled path; **OCR of an image-only prospectus**, stored as unverified |
| `test_extraction.py` | 11 | PDF parsing of a generated prospectus (units, split headers, date ranges, Indian GAAP totals, bracketed negatives, notes columns), unbalanced balance sheet detection, peers and disclosures, archive selection and zip-bomb guard, download → extraction → storage → scoring, no re-download of unchanged documents, revised documents versioned, scanned documents reported not guessed, re-reading replaces the earlier reading (regression) |
| `test_ingestion.py` | 17 | NSE adapters on captured payloads, upsert precedence and conflicts, estimates never overwrite, expected vs actual listing dates, bhavcopy cross-check, locks and dead-process recovery, polite client retries and no retry on 403/429, freshness |
| `test_api.py` | 12 | Filters, sorting, pagination, detail/financials/scores/sources, auth, CSRF, authorization (other users get 404), rate limits, error envelope |
| `test_documents_sources.py` | 8 | Uploads (type, size, page limits), keyword search, SSRF allowlist on source fetch |
| `test_imports.py` | 5 | CSV/JSON validation, unit conversion, versioning, verified-never-overwritten |
| `frontend/tests/lib.test.ts` | 11 | Formatting (missing values never become 0), tones, API client and CSRF header, schemas, **naive API timestamps read as UTC** (regression) |
| `frontend/tests/live.test.ts` | 3 | Freshness and relative-time helpers |

## Regression fixtures from real failures

| Real failure | Test |
|---|---|
| Stale rows from an older parser kept as verified (Bonfiglioli Q 88) | `test_reprocessing_a_document_replaces_its_earlier_reading` |
| "Elevated risk" shown for an IPO with no data | `test_risk_is_not_scored_from_data_quality_alone` |
| Formula change did not refresh stored scores | `test_engine_version_is_part_of_the_fingerprint` |
| Same-run download of a SEBI copy after the NSE copy was read | `test_sebi_rhp_is_downloaded_only_as_a_fallback_and_duplicates_are_detected` |
| Timestamps 5½ h off in IST | `lib.test.ts › reads a naive API timestamp as UTC` |
| Interleaved headers mis-paired, borrowed periods misaligned, notes columns read as figures, OCR junk in headers | `test_period_headers_*`, `test_extraction.py` cases |

## Not automated (manual verification)

There is no browser end-to-end framework in the repository (Playwright would need a ~150 MB browser
download). Pages were verified in the Claude desktop app's built-in browser on 31 Oct 2026:

* every route returned 200 and rendered without console errors (only dev-server HMR socket messages);
* no horizontal page overflow at 375 px on `/`, `/dashboard`, `/ipos`, `/ipos/11`, `/calendar`,
  `/analysis`, `/history`, `/methodology`, `/data`;
* tabs on the research page (overview, statements, ratios, valuation, peers, risk, score breakdown,
  data completeness, documents, sources), dashboard boards, history charts and system-health panels
  were exercised at 1440 × 900.

A quick smoke check you can run while the app is up:

```bash
for p in / /dashboard /ipos /ipos/11 /calendar /analysis /compare /history /methodology /data; do printf "%s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000$p)"; done
```
