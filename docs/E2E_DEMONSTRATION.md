# End-to-end demonstration — NSE: BCSSL

> **How this was produced.** The command ran against a *fresh, empty* SQLite database and data directory
> (`KCP_DATABASE_URL`, `KCP_DATA_DIR` pointed at a scratch folder) so that discovery, download and
> extraction genuinely started from nothing; the live development database was not touched. In that
> scratch database the issue is IPO #1 — in the live database the same issue is IPO #11
> (http://localhost:3000/ipos/11). Reproduce with:
>
> ```bash
> cd backend && KCP_DATABASE_URL=sqlite:////tmp/kcp-e2e.db KCP_DATA_DIR=/tmp/kcp-e2e python -m app.cli migrate
> cd backend && KCP_DATABASE_URL=sqlite:////tmp/kcp-e2e.db KCP_DATA_DIR=/tmp/kcp-e2e python -m app.cli e2e-demo BCSSL --report ../docs/E2E_DEMONSTRATION.md
> ```
>
> Not demonstrated by this issue (it has none): a scanned prospectus (covered by
> `test_scanned_statements_are_read_by_ocr_but_never_scored`) and the missing-data path — for that, see
> any issue whose *Data completeness* tab lists unavailable fields with reasons (e.g. an SME issue
> whose prospectus is scanned, or a SEBI pipeline issue with no dates).

Run at 2026-10-31 16:14 UTC with `python -m app.cli e2e-demo BCSSL`. Every figure below was read back from the database after the step ran.


## 1. Discover the IPO (NSE public issue lists)

Discovery job **success**: 117 issues seen, 117 new, 0 updated, 3 requests.
Matched record: **Bombay Coated and Special Steels Limited** (IPO #1, mainboard, NSE).

## 2. Retrieve official issue details

NSE issue-information request OK; 10 field(s) changed.

| Field | Value | Source |
|---|---|---|
| Opens | 2026-10-29 | nse_ipo (verified) |
| Closes | 2026-11-02 | nse_ipo (verified) |
| Price band (upper) | 82.00 | nse_ipo (verified) |
| Final price | — | — (—) |
| Lot size | 182 | nse_ipo (verified) |
| Issue size (₹ cr) | 183.06 | nse_ipo (verified) |
| Listing date | 2026-11-05 | nse_ipo:derived (estimated) |
| Registrar | KFin Technologies Limited | nse_ipo (verified) |

## 3. Locate the prospectus · 4. Download it

- Bombay Coated and Special Steels Limited — Red Herring Prospectus: `https://nsearchives.nseindia.com/content/ipo/RHP_BCSSL.zip`  
  1 request(s); downloaded 10.2 MB, SHA-256 `c96fa6fe5d27f018…`

## 5. Extract the financial statements · 6. Validate periods and units

Extraction status **extracted** (parser 1.5, method text); 4 new statement rows, 0 unchanged, 152 line items with page references, 3 listed peers.

| Period | Basis | Months | Revenue | PAT | Total assets | Status | Checks |
|---|---|---|---|---|---|---|---|
| FY2024 | unknown | 12 | 755.26 | 21.14 | 350.21 | verified | balance_sheet_balances ✓, equity_plus_liabilities ✓, assets_add_up ✓, pat_reconciles ✓, income_adds_up ✓ |
| FY2025 | unknown | 12 | 1,055.71 | 28.67 | 458.20 | verified | balance_sheet_balances ✓, equity_plus_liabilities ✓, assets_add_up ✓, pat_reconciles ✓, income_adds_up ✓ |
| FY2026 | unknown | 12 | 1,266.82 | 30.54 | 571.47 | verified | balance_sheet_balances ✓, equity_plus_liabilities ✓, assets_add_up ✓, pat_reconciles ✓, income_adds_up ✓ |
| 3M Jun-2026 | unknown | 3 | 397.08 | 15.07 | 526.11 | verified | balance_sheet_balances ✓, equity_plus_liabilities ✓, assets_add_up ✓, pat_reconciles ✓, income_adds_up ✓ |

Units as printed: INR crore, INR per share, million → stored in ₹ crore.

## 7. Calculate ratios · 8. Quantitative analysis

Basis **unknown**, periods FY2024, FY2025, FY2026, profile **Manufacturing**.

| Metric | Value | Formula |
|---|---|---|
| Return on equity | 29.85 % | ROE = PAT ÷ average shareholders' equity × 100 |
| Return on capital employed | 45.95 % | ROCE = EBIT ÷ average capital employed × 100; capital employed = total assets − current liabilities |
| Return on assets | 5.93 % | ROA = PAT ÷ average total assets × 100 |
| Net profit margin | 2.41 % | Net profit margin = PAT ÷ revenue from operations × 100 |
| EBITDA margin | 7.03 % | EBITDA margin = EBITDA ÷ revenue × 100; EBITDA = PBT + finance costs + depreciation & amortisation |
| Revenue CAGR | 29.51 % | Revenue CAGR = (ending ÷ beginning)^(1/years) − 1 |
| PAT CAGR | 20.20 % | PAT CAGR = (ending ÷ beginning)^(1/years) − 1, only when both are positive |
| Current ratio | 1.02 x | Current ratio = current assets ÷ current liabilities |
| Debt/Equity | 2.78 x | Debt/Equity = total borrowings (current + non-current, excluding lease liabilities) ÷ total equity |
| Interest coverage | 2.14 x | Interest coverage = EBIT ÷ finance costs |
| OCF/PAT | 0.33 x | OCF/PAT = net cash from operating activities ÷ PAT |
| P/E | 16.87 x | P/E = issue price ÷ post-issue EPS |
| P/B | 1.69 x | P/B = issue price ÷ post-issue book value per share |
| EV/EBITDA | 7.40 x | EV/EBITDA = enterprise value ÷ latest EBITDA |

| Component | Score | Coverage |
|---|---|---|
| Profitability | 68.84 | 100.00% |
| Growth | 89.47 | 100.00% |
| Financial health | 27.80 | 100.00% |
| Cash flow | 37.22 | 100.00% |
| Valuation | 98.25 | 100.00% |

Fundamental score Q = **65.46** (Relatively positive financial characteristics); risk **34.32** (moderate); data coverage 100.00%; configuration 2.1.0.

## 9. Source references stored

- `total_assets` = 350.2080 cr ← printed “3502.08” (million) on page 90, label “Total Assets (I+II)”
- `revenue` = 755.2590 cr ← printed “7,552.59” (million) on page 91, label “a) Revenue from operations”
- `pat` = 21.1380 cr ← printed “211.38” (million) on page 91, label “Profit for the period/year E=(C-D)”
- `total_assets` = 458.2050 cr ← printed “4582.05” (million) on page 90, label “Total Assets (I+II)”
- `revenue` = 1,055.7070 cr ← printed “10,557.07” (million) on page 91, label “a) Revenue from operations”
- `pat` = 28.6720 cr ← printed “286.72” (million) on page 91, label “Profit for the period/year E=(C-D)”

## 10. Research page

http://localhost:3000/ipos/1 — overview, financial statements with per-figure provenance, ratios, valuation, peers, score breakdown, risk, completeness and documents.

## 11. Second run — idempotency

| Table | After run 1 | After run 2 |
|---|---|---|
| ipo records with symbol | 1 | 1 |
| field observations | 21 | 21 |
| documents | 1 | 1 |
| statement rows | 4 | 4 |
| current statements | 4 | 4 |
| line items | 152 | 152 |
| peer rows | 3 | 3 |
| score rows | 2 | 2 |
| document source records | 4 | 4 |

Document re-check: 1 request(s) (HEAD), unchanged=1, re-downloaded=no; re-extraction: 4 statement rows unchanged, 0 created.

**Idempotent: yes** — no duplicate IPO, document, statement, line-item, peer or score rows. Field observations are refreshed in place (their `last_verified_at` moves) rather than duplicated.

Configuration 2.1.0; report generated 31 Oct 2026.

## Missing-data workflow (live database)

The same pipeline, for an issue the official sources describe only partly: **Carlsberg India Limited**
(IPO #134), discovered from SEBI's draft offer-document filings on 31 Oct 2026, with no NSE issue yet.
Read from `GET /api/ipos/134/completeness`:

| Stage | Status | Detail |
|---|---|---|
| Discovered | done | SEBI filing |
| Offer document located | done | SEBI draft (DRHP) filing |
| Downloaded & hashed | pending | queued (the documents job processes up to 3 per hour; NSE copies first) |
| Statements extracted → checks → ratios → score | pending | Q withheld: "required component(s) unavailable: Profitability, Growth, Financial health" |

| Field | State | Reason shown to the reader |
|---|---|---|
| Opening/closing date, price band, lot size, issue size | not expected yet | not announced yet: only an offer document has been filed |
| Revenue, PAT, total assets, … (all statement fields) | unavailable | the offer document is queued for download and extraction |
| Shares before the issue, sector, business overview, customer concentration | unavailable | the offer document is queued for download and extraction |
| Promoter holding | unavailable | not extracted automatically yet; shown as unavailable |
| Outstanding litigation | unavailable | not extracted automatically; never treated as "no litigation" |

Overall data completeness: 3 % · readiness: *Insufficient data*. No value is estimated or set to zero,
and the risk score is withheld (data quality alone is not scored). When the DRHP is processed the same
fields fill in with their page references, and when NSE announces the issue its dates and price band
attach to this record by company name.
