# Data dictionary

Two parts: the **field registry** (what the research page promises for each IPO, where each value comes
from and how it is checked — generated from `backend/app/services/field_registry.py`, also served at
`GET /api/fields`) and the **database tables** behind it (`backend/app/models.py`, migrations in
`backend/alembic/versions`).

## Value statuses

| Status | Meaning | Used in scores |
|---|---|---|
| `verified` | From an official source (exchange, regulator, offer document), parsed, and — for statements — reconciled by accounting checks | yes |
| `extracted` | Read from an official document, but no check could confirm it (incl. everything read by OCR, and lender KPI tables) | no |
| `requires_review` | Read from an official document, but an accounting check failed | no |
| `estimated` | Derived by a stated rule (SEBI T+3 dates, upper-band price, share counts × price) | yes, labelled |
| `imported` | User-imported research with stated provenance | yes |
| `secondary_source` | Non-authoritative public source (discovery or cross-checks only) | no |
| `synthetic` | Demonstration fixture about a fictional company | demo only |
| `unavailable` | No connected source provides it; the reason is shown | — |

Completeness states per field (services/completeness.py): `available`, `not_meaningful` (computed, but
the ratio is undefined, e.g. P/E of a loss-maker), `estimated`, `unverified`, `requires_review`,
`unavailable` (with reason), `not_applicable` (industry profile), `pending` (not expected at this stage).

## Field registry

### IPO information (completeness weight 20%)

| Field | Type · unit | Primary source | Fallback / secondary | Normalisation | Validation | Refresh · stale after | Expected from stage |
|---|---|---|---|---|---|---|---|
| `open_date` Opening date | date | NSE public issue data (official) | SEBI RHP (dates printed on the cover) | ISO date (Asia/Kolkata calendar day) | open ≤ close; later dates must not precede earlier ones | every 6 h while upcoming/open; on listing · 24 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open, upcoming |
| `close_date` Closing date | date | NSE public issue data (official) | SEBI RHP | ISO date | close ≥ open | every 6 h while upcoming/open; on listing · 24 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open, upcoming |
| `price_band` Price band | number · ₹ per share | NSE public issue data (official) | Price-band advertisement / RHP addendum (SEBI) | low and high ₹ per share | low ≤ high; both positive | every 6 h while upcoming/open; on listing · 24 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `final_issue_price` Final issue price | number · ₹ per share | NSE past issues (final price) | Basis of allotment / prospectus | ₹ per share | within or equal to the price band | daily after close · 48 h | listed |
| `lot_size` Lot size | count · shares | NSE public issue data (official) | RHP | integer shares | positive integer | every 6 h while upcoming/open; on listing · 24 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `issue_size_cr` Issue size | number · ₹ crore | NSE public issue data (official) (issue-size sentence) | RHP cover page | rupee amounts as stated; share counts × final price (verified) or × upper band (estimated) | fresh + OFS = total | every 6 h while upcoming/open; on listing · 24 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `fresh_issue_cr` Fresh issue | number · ₹ crore | NSE public issue data (official) | RHP | ₹ crore | ≥ 0 | every 6 h while upcoming/open; on listing · 24 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `pre_issue_shares` Shares before the issue | count · shares | Offer document — restated financial information (official) | SEBI RHP | absolute count | positive; read from the capital-structure section | when the offer document is (re)processed | always |
| `post_issue_shares` Post-issue shares | count · shares | Derived: pre-issue shares + fresh issue ÷ price | valuation multiples unavailable | absolute count | > pre-issue shares when there is a fresh issue | recomputed when price or shares change | always |
| `allotment_date` Allotment date | date | NSE / registrar announcement | SEBI T+3 timeline from the close date (estimated) | ISO date | after close | with issue details | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed |
| `listing_date` Listing date | date | NSE past issues (actual) | SEBI T+3 timeline (expected) | ISO date | an expected date is never shown as actual | every 45 min around listing · 24 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed |
| `listing_price` Listing-day open | number · ₹ per share | NSE bhavcopy of the listing date (OpnPric) | shown as unavailable with the reason; never replaced by zero or an average | ₹ per share | bhavcopy previous close must equal the issue price (±0.5%) | on listing day | listed |
| `subscription` Subscription (consolidated) | ratio · times | NSE consolidated bid details (all exchanges) | shown as unavailable with the reason; never replaced by zero or an average | times subscribed per category with 'as of' timestamp | category totals non-negative | every 20 min while open · 2 h | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `registrar` Registrar | text | NSE public issue data (official) | RHP | as published | non-empty | every 6 h while upcoming/open; on listing | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open, upcoming |
| `offer_document` Offer document (RHP) | url | NSE issue page (RHP archive) | SEBI red herring filings; SEBI draft (DRHP) filings | allowlisted official URL | host allowlist; SHA-256 of the file | hourly document job; re-checked every 3 days while upcoming/open | always |
| `business_overview` Business overview | text | Offer document — 'Our Business' section (quoted) | shown as unavailable; never written by KcpInsights | first descriptive paragraph, whitespace normalised | starts with the company's self-description | when the offer document is processed | always |
| `sector` Sector | text | Offer document (industry classifier) | User import | one of the classifier's sectors, with evidence | clear lead over the runner-up | when the offer document is processed | always |

### Financial statements (completeness weight 30%)

| Field | Type · unit | Primary source | Fallback / secondary | Normalisation | Validation | Refresh · stale after | Expected from stage |
|---|---|---|---|---|---|---|---|
| `revenue` Revenue from operations | number · ₹ crore | Offer document — restated financial information (official) | SEBI RHP; SEBI DRHP; User import | ₹ million / lakh / crore → crore | total income = revenue + other income | per document version | always |
| `pat` Profit after tax | number · ₹ crore | Offer document — restated financial information (official) | SEBI RHP; User import | → crore | PAT = PBT − tax | per document version | always |
| `ebitda` EBITDA | number · ₹ crore | Derived: PBT + finance costs + depreciation | shown as unavailable with the reason; never replaced by zero or an average | → crore | inputs from one period and basis | per document version | always |
| `total_assets` Total assets | number · ₹ crore | Offer document — restated financial information (official) | SEBI RHP; User import | → crore | assets = equity + liabilities | per document version | always |
| `total_equity` Total equity | number · ₹ crore | Offer document — restated financial information (official) | SEBI RHP; User import | → crore | equity = share capital + other equity (soft) | per document version | always |
| `total_debt` Borrowings | number · ₹ crore | Derived: current + non-current borrowings | shown as unavailable with the reason; never replaced by zero or an average | lease liabilities excluded | ≥ 0 | per document version | always |
| `cash_and_equivalents` Cash and equivalents | number · ₹ crore | Offer document — restated financial information (official) | shown as unavailable with the reason; never replaced by zero or an average | → crore | ≥ 0 | per document version | always |
| `current_assets` Current assets | number · ₹ crore | Offer document — restated financial information (official) | shown as unavailable with the reason; never replaced by zero or an average | → crore | assets = current + non-current | per document version | always |
| `current_liabilities` Current liabilities | number · ₹ crore | Offer document — restated financial information (official) | shown as unavailable with the reason; never replaced by zero or an average | → crore | equity + non-current + current liabilities = total | per document version | always |
| `operating_cash_flow` Operating cash flow | number · ₹ crore | Offer document — restated financial information (official) | shown as unavailable with the reason; never replaced by zero or an average | → crore | cash-flow PBT = P&L PBT | per document version | always |
| `capex` Capital expenditure | number · ₹ crore | Offer document — restated financial information (official) (cash-flow statement) | shown as unavailable with the reason; never replaced by zero or an average | sum of purchases of PP&E and intangibles, as a positive amount | ≥ 0 | per document version | always |
| `annual_periods` Annual periods (≥ 3) | count · periods | Offer document — restated financial information (official) | shown as unavailable with the reason; never replaced by zero or an average | 12-month periods on one basis | distinct month-end dates in a plausible order | per document version | always |

### Financial ratios (completeness weight 20%)

| Field | Type · unit | Primary source | Fallback / secondary | Normalisation | Validation | Refresh · stale after | Expected from stage |
|---|---|---|---|---|---|---|---|
| `roe` ROE | ratio · % | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `roce` ROCE | ratio · % | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `roa` ROA | ratio · % | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `net_margin` Net margin | ratio · % | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `ebitda_margin` EBITDA margin | ratio · % | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `revenue_cagr` Revenue CAGR | ratio · % | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `pat_cagr` PAT CAGR | ratio · % | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `current_ratio` Current ratio | ratio · x | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `debt_to_equity` Debt/Equity | ratio · x | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `interest_coverage` Interest coverage | ratio · x | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `ocf_to_pat` OCF/PAT | ratio · x | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |
| `fcf` Free cash flow | ratio · ₹ cr | Quant engine (formula in FINANCIAL_FORMULAS.md) | shown as unavailable or not meaningful with the reason | — | denominator > 0 | on every input change | always |

### Valuation (completeness weight 15%)

| Field | Type · unit | Primary source | Fallback / secondary | Normalisation | Validation | Refresh · stale after | Expected from stage |
|---|---|---|---|---|---|---|---|
| `market_cap` Market capitalisation | ratio · ₹ cr | Quant engine at the issue price | not meaningful for loss-making or negative-equity companies; reason shown | — | positive earnings / book value | on price or input change | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `pe` P/E | ratio · x | Quant engine at the issue price | not meaningful for loss-making or negative-equity companies; reason shown | — | positive earnings / book value | on price or input change | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `pb` P/B | ratio · x | Quant engine at the issue price | not meaningful for loss-making or negative-equity companies; reason shown | — | positive earnings / book value | on price or input change | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `ev_ebitda` EV/EBITDA | ratio · x | Quant engine at the issue price | not meaningful for loss-making or negative-equity companies; reason shown | — | positive earnings / book value | on price or input change | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `price_to_sales` Price/Sales | ratio · x | Quant engine at the issue price | not meaningful for loss-making or negative-equity companies; reason shown | — | positive earnings / book value | on price or input change | awaiting_allotment, awaiting_listing, closed, listed, listing_unconfirmed, open |
| `peer_median_pe` Peer median P/E | ratio · x | Offer document — Basis for Issue Price (listed peers) | valuation scored on absolute ranges; flagged as insufficient peer coverage | median of peers whose printed P/E = price ÷ diluted EPS (±10%) | ≥ 2 consistent peers | per document version | always |

### Risk information (completeness weight 10%)

| Field | Type · unit | Primary source | Fallback / secondary | Normalisation | Validation | Refresh · stale after | Expected from stage |
|---|---|---|---|---|---|---|---|
| `customer_concentration` Customer concentration | number · % of revenue | Offer document — restated financial information (official) (risk factors) | shown as unavailable with the reason; never replaced by zero or an average | percentage of revenue from top customers | 0–100% | per document version | always |
| `contingent_liabilities` Contingent liabilities | number · ₹ crore | Offer document — restated financial information (official) (restated notes) | shown as unavailable with the reason; never replaced by zero or an average | → crore | ≥ 0 | per document version | always |
| `auditor_qualifications` Auditor qualifications | status | Offer document — restated financial information (official) (auditor's examination report) | shown as unavailable with the reason; never replaced by zero or an average | none | disclosed | explicit statement required | per document version | always |
| `promoter_holding` Promoter holding (pre/post) | number · % | Offer document — restated financial information (official) (capital structure) | Exchange shareholding pattern after listing | % of shares | 0–100% | per document version | always |
| `litigation` Outstanding litigation | count · cases | Offer document — restated financial information (official) (outstanding litigation section) | not extracted automatically (tables vary too much to read reliably); never treated as 'no litigation' | counts and amounts by category | — | per document version | always |

### Source verification (completeness weight 5%)

| Field | Type · unit | Primary source | Fallback / secondary | Normalisation | Validation | Refresh · stale after | Expected from stage |
|---|---|---|---|---|---|---|---|
| `statements_verified` Statements reconciled | status | Accounting checks on extracted statements | shown as unavailable with the reason; never replaced by zero or an average | share of annual periods with status verified | assets = equity + liabilities, PAT = PBT − tax, … | per document version | always |
| `issue_data_official` Issue data from an official source | status | NSE public issue data (official) | shown as unavailable with the reason; never replaced by zero or an average | field observations from official sources | conflicts between sources flagged | every 6 h while upcoming/open; on listing | always |
| `document_hash` Offer document stored with hash | status | Document pipeline | shown as unavailable with the reason; never replaced by zero or an average | SHA-256 of the PDF | identical files deduplicated | per download | always |

**Source precedence is per field**, not global: e.g. dates and price band come from NSE first (an RHP
addendum second); the final issue price from NSE past issues; statements from the offer document (NSE
copy, then SEBI RHP, then SEBI DRHP, then a user import). Between sources of equal authority the newest
observation wins and the disagreement is recorded as a conflict; a lower-authority value or an estimate
never overwrites a sourced value (`ingestion/ipo_data_service.set_field`).

## Database tables

Amounts are ₹ crore after unit conversion; per-share values ₹; timestamps naive UTC.

| Table | Purpose | Key columns |
|---|---|---|
| `companies` | Issuer | `name`, `sector` (NSE label or offer-document classification), `industry_profile` (general · manufacturing · technology · infrastructure · real_estate · lender · insurer), `classification` (JSON: method, evidence phrases with counts and pages, runner-up, status), `customer_concentration_pct` |
| `ipo_issues` | One issue | `nse_symbol`, `issue_type` (mainboard/sme), dates (`open_date` … `listing_date` with `listing_date_status` actual/expected), `price_band_low/high`, `final_issue_price`, `lot_size`, `issue_size_cr`, `fresh_issue_cr`, `ofs_cr`, `pre/post_issue_shares`, `listing_price` (open), `listing_high_price`, `listing_low_price`, `listing_close_price`, `offer_document_url`, `document_facts` (JSON: value, page, quoted text, document id per fact), `completeness_pct` + `completeness_summary` (cached), `data_mode` (demo/imported/source) |
| `field_observations` | Every observed value of an issue field: source key and URL, first seen, last verified, status, basis, `applied`, `conflict` — the immutable history behind the current value | (ipo_id, field, observed_at) |
| `field_changes` | Change log of important fields (old → new, source, time) | |
| `source_documents` | Offer documents and uploads | `source_key` (nse_rhp · sebi_rhp · sebi_drhp · upload), `archive_url`, `sha256`, `size_bytes`, `http_etag`, `http_last_modified`, `published_date`, `extraction_status` (pending · extracted · partial · not_found · failed · duplicate), `extraction_method` (text · text+ocr), `parser_version`, `attempts`, `next_attempt_at`, `original_retained` |
| `document_extractions` | One row per extraction run: pages scanned, statements found, every accounting check, warnings, error | |
| `financial_statements` | One reporting period on one basis, versioned (`is_current`, `supersedes_id`) | 36 line items (revenue … capex), `basis`, `period_end`, `period_months`, `validation_status`, `validation` (checks JSON), `data_status`, `document_id` |
| `financial_line_items` | Provenance of every extracted figure: raw label, text as printed, unit as printed, normalised value, page | (statement_id, field) |
| `peer_snapshots` | Listed peers from the offer document's "Basis for Issue Price" table | printed price, EPS, NAV, P/E, RoNW, basis, period, page, consistency note, `nse_symbol`, `latest_price`, `latest_price_date` |
| `subscription_snapshots` | Consolidated subscription by category with NSE's "as of" time | |
| `research_scores` | Every stored score: components, Q, risk, classification, coverage, configuration version, input fingerprint, full breakdown (incl. engine version and period sources) | |
| `scoring_config_versions` | Immutable configuration versions; one active | |
| `data_sources`, `ingestion_jobs`, `job_locks` | Source registry and health; job runs (counts, requests, errors, detail); cross-process locks | |
| `source_records` | Provenance records referenced by statements, peers, subscriptions and issue fields | |
| `users`, `user_sessions`, `audit_logs`, `watchlist_items`, `research_reports`, `imported_datasets`, `ingestion_logs`, `document_chunks` | Accounts, sessions (hashed tokens), audit trail, workspace, imports, keyword search index | |
