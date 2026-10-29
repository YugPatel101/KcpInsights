# KcpInsights scoring methodology (configuration v1.0.0)

All constants live in `backend/app/services/scoring_config.py`. Versions are immutable; an
administrator publishes a new version through `POST /api/scoring/configs`. Every stored score
records the configuration version, an input fingerprint (SHA-256 of inputs + config) and a UTC
timestamp, so any result can be reproduced.

The weights are **educational defaults chosen for explainability**, not coefficients fitted to
data. The research score is **not** a probability of listing gains, a price target, or advice.

## 1. Normalisation

For a metric *x* with thresholds *a < b*:

| Direction | Formula |
|---|---|
| higher is better | N(x) = 100 · clip((x − a)/(b − a), 0, 1) |
| lower is better | N(x) = 100 · clip((b − x)/(b − a), 0, 1) |
| target range [lo, hi] | 100 inside; linear decay to 0 over `tol_lo` below / `tol_hi` above |

Risk inputs use N_risk(x) = 100 · clip((x − a)/(b − a)) where *a* is the zero-risk point and *b*
the full-risk point (*a* may exceed *b* for "riskier when smaller").

Only **12-month periods** feed annual metrics; interim periods are displayed but excluded.
Amounts are converted to INR crore on import (raw values are kept with the source record).

## 2. Fundamental quality Q

Q = 0.25·P + 0.20·G + 0.20·C + 0.20·B + 0.15·R

| Component | Metric (weight) | Thresholds | Edge rules |
|---|---|---|---|
| P profitability | EBITDA margin (0.35) | 0 → 25 % | revenue ≤ 0 → not meaningful |
| | PAT margin (0.25) | 0 → 15 % | |
| | ROE = PAT / avg equity (0.20) | 0 → 25 % | closing or average equity ≤ 0 → not meaningful |
| | ROCE = EBIT / (equity + debt) (0.20) | 0 → 25 % | capital employed ≤ 0 → not meaningful |
| G growth | Revenue CAGR (0.50) | 0 → 25 % | needs ≥ 2 annual periods, start and end > 0 |
| | PAT CAGR (0.30) | 0 → 30 % | loss at start or end → not meaningful (never a fake CAGR) |
| | Latest YoY revenue growth (0.20) | 0 → 25 % | prior revenue ≤ 0 → not meaningful |
| C cash flow | Σ OCF / Σ PAT (0.40) | target 0.9–1.6 | Σ PAT ≤ 0 → not meaningful |
| | Σ(OCF − capex) / Σ revenue (0.35) | −5 → 10 % | negative FCF kept negative (scores toward 0) |
| | Share of periods with OCF > 0 (0.25) | 0.5 → 1.0 | needs ≥ 2 periods |
| B balance sheet | Debt / equity (0.40) | lower: 0.1 → 2.0 | equity ≤ 0 → score 0 (documented rule) |
| | Interest cover = EBIT / interest (0.30) | 1.5 → 8 | no debt and no interest → score 100 |
| | Net debt / EBITDA (0.30) | lower: 0 → 4 | net cash → 100; EBITDA ≤ 0 with net debt → not meaningful |
| R stability | Std. dev. of YoY revenue growth (0.40) | lower: 3 → 25 pp | needs ≥ 3 annual periods |
| | Share of years with growth (0.35) | 0.34 → 1.0 | |
| | Disclosed customer concentration (0.25) | lower: 20 → 80 % | used only when disclosed |

Inside a component, available sub-metrics are re-weighted among themselves only if they carry
≥ 50 % of the component weight; otherwise the component is unavailable. **Q is unavailable if any
component is unavailable** — the formula-level weights are never silently renormalised.

## 3. Relative valuation V

V = 100 · clip((V_high − V_IPO) / (V_high − V_low), 0, 1)

* V_IPO: the IPO multiple at the final issue price, or the upper price band if unknown, on
  **post-issue diluted shares** (market cap = price × post-issue shares / 10⁷).
* Multiple preference: financials (banks, NBFCs, HFCs, insurers) P/B → P/E; others P/E → EV/EBITDA
  → P/S. The first applicable multiple with enough peers is used and every skipped attempt is
  reported. P/E is never computed on zero or negative earnings; EV/EBITDA never on EBITDA ≤ 0;
  P/S only as a flagged last resort for loss-makers.
* EV = market cap + debt − cash − fresh-issue proceeds (proceeds treated as cash).
  Post-issue book for P/B = equity + fresh-issue proceeds.
* V_low / V_high: the 25th / 75th percentiles of peers with a positive multiple, an admissible
  status and a snapshot within 180 days. Needs ≥ 3 peers and a non-degenerate spread
  ((p75 − p25)/median ≥ 0.10); otherwise V is unavailable.
* This is relative valuation versus listed peers, **not** intrinsic value.

## 4. Risk R (higher = riskier)

R = 0.25·R_f + 0.20·R_v + 0.20·R_g + 0.20·R_m + 0.15·R_d

| Component | Inputs |
|---|---|
| R_f financial | distress flags on the latest year (each 0 or 100): loss (0.25), negative OCF (0.25), negative equity (0.20), interest cover < 1.5x (0.15), D/E > 2x when equity > 0 (0.15) |
| R_v valuation | premium of IPO multiple over peer median, 0 → 100 % (0.70); basis risk of the multiple used: P/E 0, P/B 20, EV/EBITDA 35, P/S 75 (0.30) |
| R_g governance | disclosures: confirmed severity points low 10 / medium 25 / high 45, unresolved concerns × 0.5, capped at 100 (0.50); OFS share of issue 30 → 100 % (0.25); post-issue promoter holding 75 → 30 % (0.25) |
| R_m market | configured sector cyclicality assumption (0.50); issue-type liquidity: mainboard 30, SME 75 (0.30); issue size ₹1,000 cr → ₹50 cr (0.20) |
| R_d data quality | 100 − evidence coverage C |

Rules: each metric feeds exactly one risk component (enforced by a test); negative equity is not
also counted as excess leverage; **unreviewed disclosures are left out, never scored as
misconduct**; unresolved concerns are kept separate from confirmed disclosures. Levels: low < 35 ≤
moderate < 60 ≤ high.

## 5. Composite and coverage

S = 0.45·Q + 0.30·V + 0.25·(100 − R). If any of Q, V or R is unavailable, S is **not** calculated
and the response lists each missing component with its reason.

Evidence coverage C = 100 · Σ wᵢIᵢ / Σ wᵢ over 18 weighted inputs (price band, share count,
financial fields, three-year history, peer set, disclosure review, …). Iᵢ = 1 only for present,
current (financials ≤ 18 months old), **verified or imported** inputs; estimated and synthetic
inputs earn 0. Coverage measures evidence completeness — it is not the probability that the
score is correct. "Input completeness" (presence regardless of status) is reported separately.

## 6. Scenarios (hypothetical)

* P/E: Equity = Revenue₀·(1+g)·m·k · PE · (1 + market adj.)
* EV/EBITDA: Equity = Revenue₀·(1+g)·m · EV/EBITDA · (1 + adj.) − (debt − cash − fresh issue)
* Price = Equity (₹ cr) · 10⁷ / post-issue diluted shares; return = (P − P_issue)/P_issue

Defaults: base growth = historical revenue CAGR capped to [−20 %, 40 %]; margin = latest EBITDA
margin; k = latest PAT/EBITDA; multiples = peer p25 / median / p75 for bear / base / bull;
market adjustment −10 % / 0 / +5 %; bear −10 pp growth and −3 pp margin, bull +5 pp and +2 pp.
A scenario is unavailable (never invented) when inputs are missing or earnings are not positive.

## 7. Listing-outcome model (optional, separate)

Target Y = (P_listing − P_issue)/P_issue. Classes: negative < −2 %, near-zero, positive > +5 %.
Features are computed at the issue close using only statements dated before the issue opened,
peer snapshots and subscription snapshots dated on or before that time. Baselines (historical mean
return, base rate) are compared with ridge regression and logistic regression; hyper-parameters
are chosen on a chronological validation block, models are refit on train+validation and tested on
the most recent block, plus an expanding-window walk-forward. Imputation and scaling are fitted on
training rows only. Metrics: MAE, RMSE, ROC-AUC, Brier, ECE, bootstrap 95 % intervals.

No model is trained with fewer than 40 real (verified/imported, non-demo) listed IPOs or fewer than
8 per class. Synthetic datasets can only run as labelled pipeline tests (`train-model --synthetic`)
and are never reported as predictive evidence.
