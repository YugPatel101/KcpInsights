# Scoring methodology (configuration v2.1.0 · engine 2.1.1)

Everything here is implemented once, in `backend/app/services/quant_engine.py`. Weights, reference
ranges, thresholds and industry profiles live in `backend/app/services/scoring_config.py` and are
stored as versioned rows in `scoring_config_versions`; the **Methodology** page renders them from the
active row, so it cannot drift from the code. Formula definitions: [FINANCIAL_FORMULAS.md](FINANCIAL_FORMULAS.md).

The defaults are **educational starting points**: chosen to be explainable, not fitted to data, and
not validated predictors of listing gains or returns.

## 1. Inputs and data rules

* **Statements** are the restated financials in the offer document (RHP, or SEBI DRHP/RHP as a
  fallback), extracted automatically ([DATA_SOURCES.md](DATA_SOURCES.md)), or optional user imports.
  Amounts in ₹ crore; per-share figures in ₹.
* **One basis per calculation.** The basis with the most usable annual periods is used (ties:
  consolidated > standalone > unknown). Consolidated and standalone figures are never combined.
* **Annual periods only.** Ratios use 12-month periods. Interim stubs ("3M Jun-2026") are shown but
  never annualised.
* **Statuses used in scores:** `verified`, `imported`, `estimated`, `synthetic` (demo only).
  `extracted` (read but not confirmed by an accounting check — including everything read by OCR)
  and `requires_review` (a check failed) are displayed and never scored.
* **Issue price:** final issue price when NSE publishes it; otherwise the upper end of the price band,
  labelled *estimated*. **Post-issue shares** = shares before the issue (from the offer document) +
  fresh-issue amount ÷ price.
* Nothing missing is replaced by zero. A ratio with a zero or negative denominator, or a CAGR whose
  start or end is not positive, is *not meaningful*, with the reason.

## 2. Normalisation (metric → 0–100, higher = better characteristic)

* `linear`: S = 100 · clip((x − zero) / (full − zero), 0, 1). When `zero > full`, lower values score
  higher (debt/equity, multiples).
* `band`: 100 inside [lo, hi]; linear to 0 at `zero_low` below and `zero_high` above.

| Input | Range (general profile) |
|---|---|
| ROE | 0 % → 0, 25 % → 100 |
| ROCE | 0 % → 0, 30 % → 100 |
| ROA (display; scored for lenders) | 0 % → 0, 12 % → 100 |
| Net margin | 0 % → 0, 15 % → 100 |
| EBITDA margin | 0 % → 0, 25 % → 100 |
| Revenue growth (CAGR, else YoY) | −5 % → 0, 25 % → 100 |
| PAT growth (CAGR, else YoY) | −10 % → 0, 30 % → 100 |
| Growth volatility (pp) | 30 → 0, 5 → 100 |
| Current ratio | 100 within 1.2–3.0; 0 at 0.5 and at 6.0 |
| Debt/Equity | 2.0 → 0, 0 → 100 |
| Interest coverage | 1x → 0, 8x → 100 (no finance costs → 100) |
| OCF/PAT | 0 → 0, 1.0 → 100 |
| FCF margin | −10 % → 0, +10 % → 100 |
| Multiple vs peer median (P/E, P/B) | premium +60 % → 0, discount −40 % → 100 |
| Absolute P/E · P/B · EV/EBITDA (no peer median) | 60 → 0, 10 → 100 · 8 → 0, 1 → 100 · 30 → 0, 6 → 100 |

## 3. Component scores and the fundamental score Q

```
P = 0.30·S(ROE) + 0.30·S(ROCE) + 0.20·S(NPM) + 0.20·S(EBITDA margin)
G = 0.40·S(revenue growth) + 0.35·S(PAT growth) + 0.25·S(growth consistency)
F = 0.30·S(current ratio) + 0.35·S(D/E) + 0.35·S(interest coverage)
C = 0.40·S(OCF/PAT) + 0.35·S(FCF margin) + 0.25·S(cash-flow consistency)
V = 0.40·S(P/E) + 0.30·S(P/B) + 0.30·S(EV/EBITDA)

Q = 0.25·P + 0.25·G + 0.20·F + 0.15·C + 0.15·V
```

* Within a component, weights are rescaled over the available inputs, but only if they carry at
  least 50 % of the component's (applicable) weight; otherwise the component is *unavailable*.
* **Q is issued only if** profitability, growth and financial health are available, at least 85 %
  of the applicable weight is computable and at least two annual periods exist. A missing cash-flow
  or valuation component gives a *partial* Q with rescaled weights and the missing component named.
* **Weight rationale:** profitability and growth carry the most information in restated financials
  (0.25 each); balance-sheet strength next (0.20); cash flow and valuation are noisier for young
  companies and before pricing (0.15 each). These are judgements, not estimates.
* **Classes** (descriptive only — not recommendations or listing-gain probabilities): 80–100 strong ·
  65–79 relatively positive · 50–64 mixed · 35–49 weak · below 35 significant financial concerns.

## 4. Industry profiles (metric applicability)

The sector read from the offer document selects a profile. A ratio that does not fit the business
model is **not applicable**: its value is shown for reference where computable, but it is never
scored and never counted as missing. A profile may replace a component's weights and ranges.

| Profile | Not applicable | Own weights / ranges |
|---|---|---|
| General, Manufacturing | — | — |
| Technology & internet | gross margin, inventory days | EBITDA margin 0 → 0, 30 % → 100 |
| Infrastructure & utilities | gross margin | — |
| Real estate | inventory days, receivable days, current ratio, gross margin | — |
| Lenders (banks, NBFCs) | ROCE, EBITDA/operating/gross margin, current/quick/cash ratio, D/E, interest coverage, debt/EBITDA, debt/assets, EV/EBITDA, all cash-flow ratios, capex intensity, receivable/inventory days, P/S; **component:** cash flow; **risk:** leverage, cash-flow weakness | P = 0.40 ROE + 0.40 ROA + 0.20 NPM (ROE 0 → 0, 18 % → 100; ROA 0 → 0, 2.5 % → 100; NPM 0 → 0, 25 % → 100); F = 0.35 GNPA + 0.25 NNPA + 0.40 CRAR; V = 0.50 P/E + 0.50 P/B |
| Insurers | as lenders | P = 0.50 ROE + 0.25 ROA + 0.25 NPM; F = solvency ratio |

**Why lenders' Q stays incomplete.** GNPA, NNPA and capital adequacy appear only in the prospectus's
KPI tables, which cannot be reconciled against the statements. They are shown *as printed* with their
page but not scored, so a lender's financial-health component is unavailable and Q is withheld —
deliberately, rather than computing Q on ratios that do not describe a lender.

## 5. Risk score (0–100, higher = more risk)

| Component | Weight | Basis |
|---|---|---|
| Financial leverage | 0.20 | D/E (0 → 0, 2.5x → 100) and Debt/EBITDA (0 → 0, 5x → 100), averaged |
| Profitability deterioration | 0.15 | fall in net margin (0 → 0, 5 pp → 100) and PAT decline (0 → 0, 30 % → 100) |
| Cash-flow weakness | 0.15 | OCF/PAT (1.0 → 0, 0 → 100) and share of years with negative OCF |
| Valuation | 0.10 | P/E premium to peer median (0 → 0, 100 % → 100), else absolute P/E (20 → 0, 80 → 100) |
| Customer concentration | 0.10 | top-customer revenue share in the offer document (20 % → 0, 80 % → 100) |
| Contingent liabilities | 0.10 | contingent liabilities ÷ net worth (0 → 0, 50 % → 100) |
| Auditor qualifications | 0.05 | none → 0, qualifications disclosed → 100 |
| Governance & litigation | 0.05 | confirmed disclosures: high 100, medium 60, low 20 |
| Data quality & uncertainty | 0.10 | 100 − coverage, +15 if periods failed checks, +10 if the price is the upper band |

Risk = weighted average of the **available, applicable** components. A component without data is
excluded, never treated as evidence of a problem. **No risk score is issued from the data-quality
component alone** — that measures what is unknown, not how risky the company is. Levels: low < 30 ≤
moderate < 50 ≤ elevated < 70 ≤ high.

**Governance & disclosure risk** is reported separately: the weighted average of the available
customer-concentration, contingent-liability, auditor and governance components.

## 6. Coverage and completeness — two different things

* **Score coverage** = Σ (component weight × share of its inputs computable) over applicable
  components. It says how much of the model could be evaluated.
* **Data completeness** (services/completeness.py) = share of the 55 registry fields on record for the
  IPO's stage, by group (issue 20 %, financials 30 %, ratios 20 %, valuation 15 %, risk 10 %,
  verification 5 %). Estimated and unverified fields count ½, *requires review* ¼; not-applicable and
  not-yet-expected fields are left out. Every missing field carries its reason.

Neither is a confidence level or a probability that a score is right.

## 7. Point-in-time use in listing history

The listing-history view compares a score with the listing outcome only when every document behind
the score's statements was published (SEBI filing date, else the server's Last-Modified header) on or
before the listing date. Score inputs never include listing prices, subscription or post-listing data.

## 8. Reproducibility

Each stored score records the configuration version, the engine version and a SHA-256 fingerprint of
its inputs. A new row is written only when that fingerprint changes; the Score breakdown tab shows
every input, period, formula, normalised score and weight.

## 9. What the scores are not

They are methodology-dependent summaries of stored data. They are not investment advice, price
targets, recommendations to subscribe, or probabilities of listing gains.
