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

## Issue-data completeness audit (2 Nov 2026)

Prompted by BLS Polymers showing no face value. Every IPO record was checked field by field against the
sources, with Moneycontrol's IPO page used as the checklist of what an issue page should show (Moneycontrol
itself refuses automated access — HTTP 403 even for `robots.txt` — so it is a reference, not a source).

| # | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| D9 | H | Face value lost whenever NSE wrote the rupee as "Re." | BLS Polymers: NSE `Face Value` = "Re. 10 per Equity Share"; the parser matched only "Rs." (19 mainboard issues) | `normalizer.RUPEE` accepts Rs./Re./₹/INR, anchored so "Re" inside "fresh" or "share" is not a rupee sign |
| D10 | H | Every SME issue without a lot size | NSE titles the field "Bid Lot" on mainboard pages and "Lot Size" on SME pages (33/33 listed SME issues) | detail fields read through title aliases |
| D11 | H | Pre-issue share count often wrong or missing, so post-issue shares, market cap and P/E were wrong or missing | Read from authorised capital (Fusion CX 200,000,000 vs 127,059,295), the post-offer row (R.K. Fashion) or a retail allocation (Papadmalji); a bracketed "(as at the date of this RHP)" defeated the pattern (93 of 140 missing) | capital-structure and offer-summary patterns; checked against the stored values on all 139 stored prospectuses |
| D12 | M | Listed issues never re-checked: a field missing at listing stayed missing | details were fetched only for active issues | issues with any missing NSE field are re-checked weekly (`details_checked_at`) |
| D13 | M | Promoter holding, promoters, listing exchanges, issue type, website and objects of the issue never extracted | registry said "not extracted automatically yet" (0 of 140) | `financials/offer_terms.py`: cover page, shareholding pattern ((A) row accepted only when promoter + public = 100% ±0.6 pt), objects table or list |
| D14 | M | No post-issue promoter holding | — | NSE shareholding pattern filed for listing (official); derived for fresh-issue-only offers until then (RAVITA: derived 53.46% = filed 53.46%) |
| D15 | M | Seven issue-size sentence variants left issue size or the fresh/OFS split empty | "Fresh offer …", "upto N fresh equity shares", OFS count without "Equity Shares", "aggregating up to 3200 million", whole-issue-only sentences | parser extended; whole-issue sentences set the total and leave the split unavailable instead of inventing it |
| D16 | M | ISIN, issue type and fixed-price issue price not stored | NSE publishes them | stored; a fixed-price issue's price is its final price; ISIN and face value also from NSE's equity lists after listing |
| D17 | M | P/E missing for 129 of 140 issues | it needs post-issue shares (D11) and verified statements | D11; issue facts also show P/E from statements that are read but not reconciled, labelled *unverified* and never scored |
| D18 | L | A gap showed "—" with no reason on the overview | — | `issue_facts`: every issue fact has a source and status, or the reason it is empty (pending vs unavailable) |
| D20 | H | 35 closed issues displayed a subscription of 0.00x | NSE's consolidated block for those issues lists bids but 0 shares offered and a "0" multiple (e.g. RAVITA: 3.75 crore shares bid) | a multiple with no shares offered is not stored; the 107 stored rows were removed (backup kept); the page now says NSE published no consolidated figure |
| D19 | L | Two processes writing SQLite gave "database is locked" after 5 s | the gap-filling run collided with the API's scheduler | 30 s busy timeout; network requests never made inside a write transaction; transient locks retried on the next run |

Coverage of the 140 real IPOs (121 announced by NSE, 112 listed), before → after:

| Field | Before | After | Remaining gaps and why |
|---|---|---|---|
| Face value | 101 / 140 | **140 / 140** | — |
| Issue type (book built / fixed price) | not stored | **140 / 140** | — |
| Lot size (announced issues) | 88 / 121 | **121 / 121** | 19 pipeline issues: not announced yet |
| Issue size (announced issues) | 114 / 121 | **121 / 121** | 8 still at the upper band until the price is final (labelled estimated) |
| ISIN (listed issues) | not stored | **111 / 112** | 1 not published by NSE |
| Listing exchanges | not stored | **139 / 140** | 1 prospectus could not be downloaded (NSE archive 404, dead letter) |
| Shares before the issue | 47 / 140, several wrong | **138 / 140** | as above; 1 not found in a readable form |
| Shares after the issue | 37 / 140 | **119 / 140** | 38 printed, 79 exact from share counts, 2 estimated at the upper band; 19 pipeline |
| Promoter holding before the issue | 0 / 140 | **125 / 140** | 14 shareholding patterns not in a readable form (image tables, split pages) |
| Promoter holding after the issue | 0 / 140 | **112 / 140** | 108 from NSE filings, 3 derived (fresh issue only), 1 estimated; 25 not listed yet, 3 filing not found yet |
| Promoters | 0 / 140 | **137 / 140** | — |
| Company website | 0 / 140 | **123 / 140** | 16 not on the cover page in a recognisable form |
| Objects of the issue | 0 / 140 | **76 / 140** | utilisation tables that are images or span pages without a recognisable intro |
| P/E used in scores (verified statements) | 11 / 140 | **51 / 140** | needs verified statements and post-issue shares |
| P/E shown on the issue page | 11 / 140 | **66 / 140** (pre-issue EPS), **77 / 140** (market cap ÷ PAT) | 24–28 of these from statements read but not reconciled — labelled *unverified*, never scored; 19 pipeline; the rest lack readable statements or EPS |
| Average completeness | 49.3% (55 fields) | **57.1%** (60 fields) | — |

## Precision and operations round (7 Nov 2026)

| # | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| F7 | H | Summary tables chosen over the restated statements, and a P&L and cash flow taken from different sets | Candidates ranked by row count with ties to the earliest page (the summary); BLS Polymers: balance sheet p88 and cash flow p90 (summary) with the P&L p332 (restated) — their profit before tax disagreed | candidates ranked by their own reconciliation; cash flow paired with the P&L on profit before tax; up to 60 title pages examined (was 20) |
| F8 | H | A sign lost in a summary table was stored as verified | Swastika Infra FY2025 operating cash flow +₹76.5 cr (summary p81) vs −₹76.5 cr in the restated cash flow (p273) and two other pages | the restated statement now wins on reconciliation |
| F9 | M | Common layouts left periods unverified | tax printed only as current + deferred (≈74 statements); "Total Equity & Liability"; "Total non - current assets"; "Total Profit for the year"; "Sub-Total"/bare "TOTAL" sections; "Total (1+2+3+4)"; headings printed after the table in the text stream; "Less:/Add:" prefixes | patterns and section logic in `statement_parser.py` 1.6; tax summed from its printed lines (counts only when PAT reconciles) |
| F11 | H | Consolidated total equity read without non-controlling interests | "Total equity attributable to equity holders of the Holding Company" matched before the "Total equity" line (documents 41, 49, 55, …): equity + liabilities ≠ assets in 8 periods, and 6 verified periods carried equity up to 1.3% low | the plain total wins; the owners' share is used only when no total is printed (parser 1.7: 311 → 324 verified periods on the corpus) |
| F10 | M | Subtotal check failed balance sheets that balance | printed current + non-current assets can leave out a group (assets held for sale) | `assets_add_up` is a soft check |
| D21 | M | Objects of the issue read for 76 of 139 prospectuses, amounts for 60 | "Offer Proceeds" wording, "[ ]" for ●, whole-rupee amounts, bullet lists, multi-year deployment headers, offers for sale (no proceeds) | objects for 125, amounts for 111; offer-for-sale-only issues say the company receives no proceeds |
| D22 | M | Promoter holding read for 125 of 139 | rows without "(A)"/"(B)", public rows longer than the window, "©", split decimals ("70.7 9" read as 70.7), no identifiable promoter | 135 of 139, two-decimal precision |
| O1 | M | No backups, no health signal, no unattended setup | backups were a manual `sqlite3 .backup`; a stopped scheduler was only visible as stale data | scheduled online backups with integrity check and rotation; `app.cli health` and **Attention needed**; opt-in macOS alerts; `scripts/service.sh` launch agents |
| Q1 | M | No browser end-to-end tests; `next build` broke a running dev server | — | Playwright on the installed Chrome (24 checks); `npm run build:check` builds into `.next-check/` |

Live database before → after re-processing every stored offer document with parsers 1.6 and 1.7:

| Measure | Before | After |
|---|---|---|
| Verified annual statements (real IPOs) | 209 | **293** |
| Annual statements extracted but not reconciled | 145 | 100 |
| Annual statements requiring review (a check failed) | 24 | 18 |
| IPOs with a verified annual period | 72 | **97** |
| IPOs with two or more verified years (needed for growth and Q) | 69 | **94** |
| Offer documents fully extracted / partial / statements not found | 84 / 35 / 20 | **105 / 24 / 11** (of 140) |
| IPOs with a fundamental score Q | 61 | **80** |
| IPOs with a verified P/E (used in scores) | 51 | **70** |
| Objects of the issue on record (with amounts) | 76 (60) | **127 (111)** of 142 |
| Promoter holding before / after the issue | 125 / 112 | **136 / 114** of 142 |
| Average completeness | 57.1% | **66.1%** |

Example: BLS Polymers — balance sheet and cash flow previously taken from the offer-document summary (no totals to
check, cash-flow PBT different from the restated P&L); now all four periods verified from the restated statements,
fundamental score 74.9, verified P/E 34.5x at the issue price, completeness 85%.

## Calculated and estimated issue facts (7 Nov 2026)

Request: fill every field, by calculation or estimate where no source publishes it. Rule kept: a calculated value
shows its formula, an estimate says *estimated* (or *proposed* for draft-document terms) with its method and base
rate, and none of them enters a score. Fields that cannot exist yet (a price band or ISIN before the company
announces them, a listing price before listing) stay *pending* with the reason.

| Fact | Before | After (calculated / estimated) |
|---|---|---|
| Shares offered to bidders | 8 | **109** (NSE bid data, or total − anchor portion) |
| P/E on pre-issue EPS | 69 | **84** (PAT ÷ shares where no EPS line is printed) |
| Promoter holding after the issue | 114 | **119** (ranges around an offer for sale; 0 with no promoter) |
| Fresh issue / offer for sale | 119 | **137** (proposed terms from draft prospectuses) |
| Issue size · total shares in the issue | 121 · 120 | **127 · 129** |
| Registrar · lead managers | 121 · 121 | **141 · 138** (draft covers matched against known names) |
| Final issue price | 117 | **119** (upper band before listing; 115 of 115 listed book-built issues priced there) |
| Valuation vs listed peers · price at the peer median | — | **20 · 20** (+6 indicative values before a price) |
| Still pending by nature (pipeline: price band, lot, ISIN, market cap) | — | 20 each, with the reason |
| Peer comparison unavailable | — | 114: the prospectus peer table has fewer than two usable P/Es or failed its column check |

## Remaining limitations (not fixed)

* BSE refuses automated requests; BSE-only issues need a manual import.
* SEBI listing pages beyond the first need a form token and are not automated (new filings appear on the first page).
* Litigation tables are not extracted; they stay *unavailable*. Registrar and lead-manager names are not read from draft offer documents (cover tables interleave intermediaries), so pipeline issues show them only once NSE announces the issue.
* Moneycontrol and BSE refuse automated access (checked 2 Nov and 31 Oct 2026); they are not sources.
* OCR results and lender KPI-table figures are shown but never scored.
* The industry classifier is phrase-based; close calls are left Unclassified and NSE's own industry label is kept where published, so sector names mix two taxonomies.
* Rate limiting is in-process; SQLite is single-writer — fine locally, not for several API workers.
* Browser end-to-end tests run against a live app and the installed Chrome; they are not run in CI (there is none).
* Scheduled jobs run only while the API process runs — `scripts/service.sh install` keeps it running on a Mac that is awake (DEPLOYMENT.md).
