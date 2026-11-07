# Financial formulas

Single implementation: `backend/app/services/quant_engine.py` (`FORMULAS` and `compute_metrics`). The
API exposes the same text at `GET /api/methodology` and with every metric (`formula` field).

**Conventions.** Amounts in ₹ crore; per-share figures in ₹; percentages in percent units. *L* is the
latest annual period, *P* the previous one, both on the same reporting basis. "Average" = (opening +
closing) ÷ 2; with no opening balance the closing balance is used and the metric says so.

## Derived line items (from the statements)

| Item | Formula |
|---|---|
| EBIT | PBT + finance costs |
| EBITDA | PBT + finance costs + depreciation & amortisation |
| Total borrowings | current + non-current borrowings (incl. current maturities of long-term debt); lease liabilities excluded |
| Total liabilities | non-current + current liabilities |
| Total equity | the printed "Total equity" (including non-controlling interests in consolidated statements); equity attributable to the owners only when no total is printed; else share capital + other equity |
| Capital expenditure | sum of purchases of property, plant, equipment and intangibles in the cash-flow statement, as a positive amount |

## Statement verification (accounting checks)

A reporting period is **verified** — and only then used in ratios and scores — when at least two of the three core
identities hold to within 0.5% (or ₹0.02 cr) and no hard check fails:

| Check | Identity | Kind |
|---|---|---|
| `balance_sheet_balances` | Total assets = Total equity and liabilities | core, hard |
| `equity_plus_liabilities` | Total assets = Equity + Non-current + Current liabilities | core, hard |
| `pat_reconciles` | PAT = PBT − Tax | core, hard when tax is a printed total |
| `income_adds_up` | Total income = Revenue + Other income | hard |
| `assets_add_up` | Total assets = Current + Non-current assets | soft (printed subtotals can leave out a group, e.g. assets held for sale) |
| `pbt_reconciles`, `equity_adds_up` | PBT = Total income − Total expenses; Total equity = Share capital + Other equity | soft |
| `cash_flow_starts_from_pbt` | Cash-flow PBT = P&L PBT | soft; hard when a statement borrowed its column periods |

Where a P&L prints tax only as its parts, tax = current tax + deferred tax + earlier-year tax as printed (signs
as printed). `pat_reconciles` then counts when it holds; a miss is recorded as soft, because it may only mean a tax
line the parser did not recognise. A period with a failed hard check is stored as *requires review* and never
scored; one with fewer than two core checks stays *extracted* (shown, labelled unverified, never scored).

**Which statement is read.** A prospectus prints the restated statements and summaries of them. Candidates are
ranked by their own reconciliation (no failed hard check, most checks passed), then by completeness; the cash-flow
statement is the one whose profit before tax agrees with the chosen P&L in the most periods.

## Profitability

| Metric | Formula | Not meaningful when |
|---|---|---|
| ROE | PAT ÷ average equity × 100 | average equity ≤ 0 |
| ROCE | EBIT ÷ average capital employed × 100; capital employed = total assets − current liabilities | capital employed ≤ 0 |
| ROA | PAT ÷ average total assets × 100 | average assets ≤ 0 |
| Net profit margin | PAT ÷ revenue from operations × 100 | revenue ≤ 0 |
| EBITDA margin | EBITDA ÷ revenue × 100 | revenue ≤ 0 |
| Operating (EBIT) margin | EBIT ÷ revenue × 100 | revenue ≤ 0 |
| Gross margin (materials basis) | (revenue − cost of materials consumed) ÷ revenue × 100 — purchases of traded goods and inventory changes are not deducted, so compare only within one company | revenue ≤ 0 |

## Growth

| Metric | Formula | Not meaningful when |
|---|---|---|
| Revenue / PAT / EBITDA / EPS CAGR | (ending ÷ beginning)^(1 / years) − 1, years = (end date − start date) ÷ 365.25 | start or end ≤ 0, or fewer than two annual periods |
| YoY growth (revenue, PAT, EBITDA, basic EPS) | value_L ÷ value_P − 1 | previous value ≤ 0 |
| Revenue growth volatility | population standard deviation of YoY revenue growth (percentage points) | fewer than three annual periods |
| Growth consistency | 60 % × share of positive YoY revenue and PAT changes + 40 % × S(volatility) | fewer than three annual periods |

## Liquidity and leverage

| Metric | Formula | Not meaningful when |
|---|---|---|
| Current ratio | current assets ÷ current liabilities | CL ≤ 0 |
| Quick ratio | (current assets − inventories) ÷ current liabilities | CL ≤ 0 |
| Cash ratio | cash and equivalents ÷ current liabilities | CL ≤ 0 |
| Debt/Equity | total borrowings ÷ total equity | equity ≤ 0 |
| Debt/Assets | total borrowings ÷ total assets | assets ≤ 0 |
| Interest coverage | EBIT ÷ finance costs; finance costs = 0 → "unlimited" (scored 100) | finance costs < 0 |
| Debt/EBITDA | total borrowings ÷ EBITDA | EBITDA ≤ 0 |

## Efficiency

| Metric | Formula |
|---|---|
| Receivable days | closing trade receivables ÷ revenue × 365 |
| Inventory days | closing inventories ÷ revenue × 365 (sales basis — cost of goods sold is not reported consistently) |
| Capex intensity | capital expenditure ÷ revenue × 100 |

## Cash flow

| Metric | Formula |
|---|---|
| OCF/PAT | net cash from operating activities ÷ PAT (PAT ≤ 0 → not meaningful) |
| Free cash flow | operating cash flow − capital expenditure |
| FCF margin | FCF ÷ revenue × 100 |
| Cash conversion | OCF ÷ EBITDA × 100 |
| Cash-flow consistency | share of annual observations with positive OCF and positive FCF (needs ≥ 2 observations) |

## Valuation (at the issue price, post-issue)

| Metric | Formula |
|---|---|
| Price | final issue price, else upper end of the price band (*estimated*) |
| Post-issue shares | shares before the issue + fresh-issue amount × 10⁷ ÷ price |
| Market capitalisation | price × post-issue shares ÷ 10⁷ |
| Post-issue EPS | latest PAT × 10⁷ ÷ post-issue shares |
| P/E | price ÷ post-issue EPS (PAT ≤ 0 → not meaningful; loss-makers are never forced onto P/E) |
| Post-issue book value per share | (latest equity + fresh-issue proceeds) × 10⁷ ÷ post-issue shares |
| P/B | price ÷ post-issue BVPS (book ≤ 0 → not meaningful) |
| Enterprise value | market cap + borrowings − cash − fresh-issue proceeds (the proceeds are cash on completion) |
| EV/EBITDA | EV ÷ latest EBITDA (EBITDA ≤ 0 → not meaningful) |
| Price/Sales | market cap ÷ latest revenue |

## Peers

| Metric | Formula |
|---|---|
| Peer P/B | closing price ÷ NAV per share, as printed in the offer document |
| Peer P/E consistency | a peer row is used only if printed P/E is within 10 % of closing price ÷ diluted EPS |
| Benchmarks | median and quartiles (inclusive method, as spreadsheet QUARTILE.INC) of verified peers with a positive multiple; at least 2 peers |
| Premium to median | (IPO multiple ÷ peer median − 1) × 100 |
| P/E at latest close | latest NSE bhavcopy close ÷ diluted EPS printed in the offer document (shows the price move, not new earnings) |

## Listing outcomes

| Metric | Formula |
|---|---|
| Listing gain | (listing-day open − final issue price) ÷ final issue price × 100 |
| Listing-day closing return | (listing-day close − final issue price) ÷ final issue price × 100 |
| Listing-day high / low return | (high or low − final issue price) ÷ final issue price × 100 |
| Score vs outcome | Spearman rank correlation (average ranks for ties) between point-in-time scores and listing gains |

Never computed from a price band; the bhavcopy's previous close on listing day must equal the issue
price within 0.5 %, otherwise the listing price is not applied.

## Normalisation and scores

See [SCORING_METHODOLOGY.md](SCORING_METHODOLOGY.md) §2–§6.

## Tests

Every formula above has a hand-calculated test in `backend/tests/test_quant_engine.py` or
`backend/tests/test_platform.py` (e.g. ROA = 100 ÷ ((1,200 + 1,000) ÷ 2) = 9.09 %; receivable days =
200 ÷ 1,000 × 365 = 73; P/S = ₹100 cr ÷ ₹1,000 cr = 0.1; quartiles of 10, 20, 30, 40 = 17.5 / 25 / 32.5).
