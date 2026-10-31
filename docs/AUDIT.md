# Technical audit — KcpInsights v2.1 overhaul

Audit of the repository as it stood after the phase-3 work (commit `c76ca7c` plus uncommitted phase-3
changes), followed by the fixes made in this overhaul. Each finding names the evidence that exposed it
and how the fix is verified. Severity: **H** wrong numbers or a security/correctness risk · **M**
missing capability the product claims · **L** maintainability or presentation.

## Summary by category

| Category | Assessment before | After |
|---|---|---|
| Architecture | Clean layering (sources → ingestion → financials → quant engine → API), but lists and the dashboard re-ran the scoring engine for every IPO on every request; dead agent-era code paths remained | Scores and completeness are stored and refreshed on data, configuration or engine change; dead code removed |
| Data | One offer-document source (NSE archive); sector unknown for most issues; scanned prospectuses unreadable; no field-level completeness | Two official document sources (NSE, SEBI) with fallback and de-duplication; sector from the prospectus; local OCR; field registry and completeness engine |
| Backend | Consistent error envelope, ETags, timeouts; a few `assert`-based validations | Explicit validation everywhere; new typed endpoints |
| Database | Normalised, versioned statements, field observations, Alembic | One additive migration (`7c41e2b9d5a3`); up/down/up verified; models match migrations |
| Financial engine | Correct and tested for the core ratios; industry-blind; no ROA, gross margin, P/S, quartiles | 12 more ratios, industry profiles (applicability registry), governance sub-score, engine version in the fingerprint |
| Ingestion | Idempotent, locked, polite; failed documents retried every 24 h forever | Exponential backoff and dead letters; SEBI filings job; peer-price job; same-run fallback guard |
| Frontend | Functional but visually inconsistent; landing page showed an obsolete formula; timestamps 5½ h off | Token-based design system, redesigned pages, new history/methodology/system-health/completeness/peers views; both bugs fixed |
| Security | Strong auth/session/CSRF/SSRF design | Build-time CLI moved out of runtime deps; Next.js advisories assessed (see SECURITY.md) |
| Deployment | Local mode works; Dockerfile carried an obsolete AI variable | Dockerfile fixed (Tesseract, health check); hosting limits documented |
| Testing | 67 backend + 14 frontend tests | 89 backend + 14 frontend tests, including OCR and point-in-time regressions |

## Findings and fixes

### Architecture

| # | Sev | Finding | Evidence | Fix | Verified by |
|---|---|---|---|---|---|
| A1 | H | `GET /api/ipos`, `/api/dashboard/summary`, `/api/ipos/upcoming…` and `/api/watchlist` ran `score_ipo` (engine + statement query) for **every IPO on every request** — an N+1 pattern that grows with history | `routes/ipos.py` list loop called `score_summary(score_ipo(db, ipo))` | `cached_score_summaries()` reads the latest stored score per IPO in one query; scores are refreshed by ingestion jobs, document processing, imports and the 30-min health job | `test_lists_read_stored_scores_instead_of_recomputing` (engine patched to raise during list requests); dashboard now answers in ~40 ms |
| A2 | H | The score fingerprint covered inputs and configuration but not the engine code, so a formula change never refreshed stored scores | `refresh-scores` after a rule change reported `new_scores: 0` | `ENGINE_VERSION` is part of the fingerprint and stored with each result | `test_engine_version_is_part_of_the_fingerprint`; `refresh-scores` then stored 150 new rows |
| A3 | L | Agent-era leftovers: `refresh_single` (on-demand refresh for the removed AI agent), `agent` rate-limit buckets, an AI settings comment, `KCP_AI_PROVIDER` in the Dockerfile, an "agent calls" proxy-timeout comment | grep | Removed or reworded | grep returns nothing; tests pass |
| A4 | M | No single place stated where each field comes from, how it is validated or when it is stale | — | `services/field_registry.py` (55 fields) drives `/api/fields`, the completeness engine and DATA_DICTIONARY.md | `test_new_reference_endpoints` |

### Data

| # | Sev | Finding | Fix | Verified by |
|---|---|---|---|---|
| D1 | M | Offer documents came only from the NSE archive; a missing link or a 404 left the issue without financials | SEBI DRHP/RHP filings adapter (robots.txt allows; first listing page, polled twice a day). A SEBI RHP is read only when the NSE copy could not be; identical files are detected by SHA-256; DRHP filers with no NSE issue yet become *pipeline* issues | `test_sebi_*` (saved SEBI pages); live run: 37 filings, 19 pipeline issues |
| D2 | M | NSE publishes no sector for most issues → "Unclassified", so industry-aware analysis was impossible | Weighted-phrase classifier over the prospectus business sections, with evidence and a minimum lead over the runner-up (close calls stay Unclassified); selects the analysis profile | `test_industry_classifier_reads_evidence_and_declines_close_calls`; 90 IPOs classified from stored documents |
| D3 | M | Prospectuses whose statement pages are scanned images were unreadable | Local Tesseract OCR via PyMuPDF for image-only pages; OCR'd periods pass the same checks but are stored as *extracted* (never scored) | `test_scanned_statements_are_read_by_ocr_but_never_scored`; one real scanned RHP (Vedant Poly Fabs) now yields its P&L |
| D4 | M | Listing-day high/low were not stored | Read from the bhavcopy (`HghPric`, `LwPric`); cached bhavcopies make the back-fill request-free | `test_listing_history_uses_point_in_time_scores_only` |
| D5 | M | Peer multiples only as of the prospectus date, with no staleness signal | Peers matched to NSE symbols via the official equity lists and given the latest bhavcopy close; price age vs the issue opening is flagged | peers endpoint; System health job log |
| D6 | L | Real issues had no business description | First descriptive paragraph of "Our Business", quoted with its page | `test_business_overview_is_quoted_with_its_page` |
| D7 | H | (fixed just before this audit) Re-reading a document kept rows from an older parser run as *verified* (Bonfiglioli showed Q 88 on mislabelled periods) | Same-document re-reads replace the earlier reading | `test_reprocessing_a_document_replaces_its_earlier_reading` |

### Backend and API

| # | Sev | Finding | Fix |
|---|---|---|---|
| B1 | M | `POST /api/admin/data-sync` validated the job with `assert` (a 500 error; skipped under `python -O`) | 422 `unknown_job`; the request model lists every job |
| B2 | L | The statement parser used an `assert` for control flow | Explicit guard; `ruff --select S` clean |
| B3 | L | List page size capped at 100 while the IPO picker needs every IPO (150+) | Cap raised to 200 |
| B4 | H | A risk score was issued from the data-quality component alone, labelling an IPO with no data "Elevated risk" | Risk is withheld unless at least one substantive component exists (`test_risk_is_not_scored_from_data_quality_alone`) |
| B5 | L | In one documents run, a SEBI fallback could still be downloaded after the NSE copy had just been read | Re-checked before each download (`test_sebi_rhp_is_downloaded_only_as_a_fallback…`) |

### Financial engine

| # | Sev | Finding | Fix |
|---|---|---|---|
| F1 | M | Missing ratios: ROA, gross margin, EBITDA and EPS CAGR, debt/assets, capex intensity, receivable and inventory days, price/sales; no peer quartiles | Added, each with a hand-calculated test (`test_new_ratios_match_hand_calculations`, `test_peer_quartiles_inclusive_method`) |
| F2 | H | Industry-blind scoring penalised lenders on current ratio, D/E, interest coverage and EBITDA margin | Profiles in the versioned configuration (v2.1.0): not-applicable ratios are shown but never scored or counted as missing; lenders use ROE/ROA/net margin and GNPA/NNPA/CRAR, whose unverified KPI-table values keep Q incomplete rather than wrong |
| F3 | L | Governance and disclosure risk was not visible on its own | Sub-score from the disclosure-based risk components |

### Ingestion

| # | Sev | Finding | Fix |
|---|---|---|---|
| I1 | M | Failed documents were retried every 24 h indefinitely; no dead letters | Exponential backoff (1, 2, 4, 8 h … 7 days); dead letter after 5 attempts; shown on System health (`test_failed_documents_back_off_exponentially…`) |
| I2 | L | No job for SEBI filings or peer prices | `filings` (12 h) and `peers` (daily) jobs with their own locks and source health |

### Frontend

| # | Sev | Finding | Fix |
|---|---|---|---|
| U1 | H | The landing page advertised an obsolete v1 formula (S = 0.45·Q + 0.30·V + 0.25·(100 − R)) the engine no longer uses | New landing page built from live API data; the formula is rendered from the active configuration |
| U2 | H | Absolute timestamps (naive UTC from the API) were parsed as local time — shown 5½ h off in India | `parseApiTime` reads zone-less timestamps as UTC (regression test in `tests/lib.test.ts`) |
| U3 | M | Inconsistent visuals: animated gradient "aurora" backgrounds, glass panels, mixed palettes; the synthetic-data colour reused for listing events | Design tokens (surfaces, ink, brand, semantic pos/neg/warn, demo) in `globals.css`; every component swept onto them; animations removed; reduced-motion respected |
| U4 | M | No listing-history, methodology or system-health views; no completeness or peer views on the research page | `/history`, `/methodology`, `/data` (system health), *Peers* and *Data completeness* tabs |
| U5 | L | A token named `accent` collided with shadcn's theme and rendered grey | Renamed to `brand` |

### Security

| # | Sev | Finding | Fix |
|---|---|---|---|
| S1 | M | The `shadcn` CLI (bundling an MCP server, Express and Hono with open advisories) was a runtime dependency although only its CSS is used at build time | Moved to devDependencies |
| S2 | M | Next.js 16.2.9 has advisories fixed in 16.4.x (middleware bypass, Server Actions DoS/SSRF, bundled postcss/sharp) | Not exploitable as configured — no middleware/proxy file, no Server Actions, no `next/image`. Upgrade documented in SECURITY.md (16.4.3 was 8 days old at audit time) |

## Remaining limitations (not fixed)

* BSE refuses automated requests; BSE-only issues need a manual import.
* SEBI listing pages beyond the first need a form token and are not automated (new filings appear on the first page).
* Litigation tables and promoter holding are not extracted; they stay *unavailable*.
* OCR results and lender KPI-table figures are shown but never scored.
* The industry classifier is phrase-based; close calls are left Unclassified and NSE's own industry label is kept where published, so sector names mix two taxonomies.
* Rate limiting is in-process; SQLite is single-writer — fine locally, not for several API workers.
* No browser end-to-end framework is installed; pages were verified with the in-app browser and HTTP smoke checks (TESTING.md).
* Scheduled jobs run only while the API process runs (DEPLOYMENT.md).
