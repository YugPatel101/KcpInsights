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
cd frontend && npm run build:check
```
```bash
cd frontend && npm run test:e2e
```

`build:check` builds into `.next-check/`, so it runs beside `scripts/dev.sh`. `test:e2e` drives the installed Google
Chrome (Playwright, no browser download) against the running app (`KCP_E2E_URL`, default http://localhost:3000).
```bash
cd backend && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic upgrade head && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic downgrade base && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic upgrade head && KCP_DATABASE_URL=sqlite:////tmp/kcp-mig.db .venv/bin/alembic check
```

## Results of the last run (7 Nov 2026)

| Check | Result |
|---|---|
| Backend tests (pytest) | **136 passed** |
| Frontend unit tests (vitest) | **14 passed** |
| ruff (incl. bandit `S` rules) · mypy (58 modules) | clean · no issues |
| ESLint · TypeScript `--noEmit` | clean · clean |
| Production build (`npm run build:check`) | success, 18 routes |
| Browser end-to-end (Playwright, Chrome) | **24 passed** (12 checks × desktop 1440 px and Pixel 7) |
| Alembic upgrade → downgrade base → upgrade → `check` | 6 migrations each way; models match |
| End-to-end demonstration on a real IPO | see [E2E_DEMONSTRATION.md](E2E_DEMONSTRATION.md) |

## What the tests cover

| File | Tests | Covers |
|---|---|---|
| `test_quant_engine.py` | 14 | Every core ratio against hand calculations (ROE/ROCE with average balances, margins, CAGR and its not-meaningful cases, YoY, liquidity, leverage incl. zero interest and negative equity, OCF/PAT, FCF, P/E, P/B, EV/EBITDA on post-issue shares); normalisation; component and overall scores; coverage thresholds; renormalisation; basis selection; exclusion of unverified periods; peer medians; risk aggregation; price sensitivity; configuration validation; **risk is not scored from data quality alone** (regression) |
| `test_platform.py` | 22 | New ratios (ROA, gross margin, EBITDA/EPS CAGR, debt/assets, capex intensity, receivable/inventory days, P/S) and their refusal cases; peer quartiles; **lender profile** (not-applicable ratios, excluded components, Q withheld); profiles leave general scores unchanged; bad profile weights rejected; engine version in the fingerprint; industry classifier incl. close calls; business overview; **SEBI** listing parser on saved pages, discovery, pipeline issues, fallback-only download, SHA-256 duplicates; exponential backoff and dead letters; **completeness** (every gap has a reason; pending vs unavailable); lists read stored scores (engine patched to fail); new endpoints; **listing history** with point-in-time exclusion; Spearman; OCR disabled path; **OCR of an image-only prospectus**, stored as unverified |
| `test_issue_data.py` | 32 | NSE detail-page variants (**`Re.` face values**, **SME `Lot Size` title**, fixed-price final price); seven real issue-size sentence variants, incl. "Re" inside "fresh" not read as a rupee sign; whole-issue sizes without an invented fresh/OFS split; shareholding-pattern and equity-list parsers; offer terms from the cover, capital structure (pre-issue shares, not authorised capital), shareholding pattern (split words, wrapped digits, A1/A2 rows, rows that don't add up refused) and objects (table and numbered list); ambiguous face values refused; objects-table variants ("Offer Proceeds", "[ ]", header text before the first object) and offer-for-sale-only chapters; shareholding-pattern variants (no bracket markers, split decimals, long public rows) and companies without a promoter; storage with NSE precedence and conflicts; post-issue shares and promoter holding derived only for fresh-issue-only offers; the NSE filing replaces the derivation; weekly gap re-checks of listed issues; equity-list and shareholding fallbacks; `issue_facts` never blank without a reason; P/E labelled unverified from unreconciled statements and withheld after a failed check |
| `test_statement_layouts.py` | 7 | Statement layouts that used to stay unverified: total equity including non-controlling interests; "Sub-Total"/bare "TOTAL" sections, "Total (1+2+3+4)" side totals, two equal bare totals, a heading printed after the table, tax printed only as current + deferred ("Less:"/"Add:"), P&L/cash-flow pairing by profit before tax |
| `test_calculated_facts.py` | 7 | Fields filled by calculation or labelled estimate: reserved portions in NSE's sentence; proposed offer on draft covers (parts must add up); intermediaries matched by known names (generic and nested names excluded); final-price estimate with its base rate; bidder shares from bid details or total − anchor; EPS from PAT ÷ shares; promoter-holding range around an offer for sale; comparison with listed peers; pipeline issues never blank without a reason |
| `test_operations.py` | 4 | Online backup is consistent, integrity-checked and rotated; health problems from stored state (overdue jobs, dead letters, backups); alerts only on change and only when enabled; `health` exit codes |
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
| BLS Polymers' face value lost ("Re. 10 per Equity Share") | `test_rupee_prefixes_issue_method_and_short_years`, `test_detail_page_variants_mainboard_and_sme` |
| Every SME issue missing its lot size (NSE titles it "Lot Size") | `test_detail_page_variants_mainboard_and_sme` |
| Pre-issue shares read from authorised capital / the post-offer row (wrong P/E inputs) | `test_offer_terms_from_cover_capital_structure_and_objects` |
| Seven issue-size sentences left unparsed | `test_issue_size_sentence_variants` |
| 35 closed issues showing "0.00x" subscription (NSE published bids but no shares offered) | `test_unpublished_subscription_multiple_is_not_stored_as_zero` |
| Interleaved headers mis-paired, borrowed periods misaligned, notes columns read as figures, OCR junk in headers | `test_period_headers_*`, `test_extraction.py` cases |

| `frontend/e2e/*.spec.ts` | 12 (×2 viewports) | Every route renders its heading with no console errors and no horizontal overflow; a listed IPO's issue details show a value or a reason for every fact; research-page tabs; discovery → research navigation; API error envelope without internals |

## Corpus checks (real prospectuses)

Parser changes are measured on every stored offer document before release (139 documents): the number of
reporting periods that pass the accounting checks, and any period that was verified before and is not now, or
whose values changed. Statement parsers 1.6–1.7: 228 → 324 verified periods, no regressions. Values changed in
seven verified periods, all corrections: a sign the old reading had lost (Swastika Infra's FY2025 operating cash
flow, −₹76.5 cr as printed in the restated cash flow, not +₹76.5 cr from a summary table), and six consolidated
total-equity figures that now include non-controlling interests (at most 1.3% higher).

## Manual verification

Pages were also checked in the Claude desktop app's built-in browser on 31 Oct 2026:

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
