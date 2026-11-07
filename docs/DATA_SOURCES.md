# Data sources

Only official sources are contacted automatically, by backend jobs — never by the browser. Each was
checked from this environment with the honest User-Agent `KcpInsights-Research/1.0 (educational;
manual-trigger)`, no cookies and no session tricks. KcpInsights never bypasses authentication,
CAPTCHAs, rate limits or anti-bot controls; a source that refuses automated access is reported as
blocked and not used.

## Connected (automatic)

| Key | Source | Verified | Access path | Provides |
|---|---|---|---|---|
| `nse_ipo` | NSE public issue information | 2026-10-29, re-checked 2026-10-31 | JSON behind NSE's own IPO pages: `api/all-upcoming-issues`, `api/ipo-current-issue`, `api/public-past-issues`, `api/ipo-detail`, `api/ipo-active-category`. robots.txt: `Allow: /` | symbol, mainboard/SME, open/close dates, price band, lot size, face value, final issue price, actual listing date, registrar, lead managers, offer-document and basis-of-price links, issue-size sentence, consolidated subscription by category with "as of" time, NSE industry label (some issues) |
| `nse_bhavcopy` | NSE daily bhavcopy | 2026-10-29 | `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip` | listing-day open, high, low, close; previous close (= issue price, used as a cross-check); latest close of listed peers. Files are immutable and cached locally |
| `nse_rhp` | Offer documents in NSE archives | 2026-10-29 | `nsearchives.nseindia.com/content/ipo/RHP_<SYMBOL>.zip`, linked from each issue page | restated balance sheet, P&L, cash flow (every period, consolidated or standalone), listed-peer table, shares before the issue, customer concentration, auditor qualifications, contingent liabilities, business overview, industry evidence |
| `sebi_offer_documents` | SEBI public-issue filings | 2026-10-31 | `sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10` (draft offer documents) and `…smid=11` (red herring documents); each filing page embeds `sebi_data/attachdocs/<month>/<id>.PDF`. robots.txt disallows only `/js` and `/css` | new DRHP/RHP filings (company, date, PDF). A SEBI RHP is read only when the NSE copy could not be; identical files are detected by SHA-256; DRHP filers not yet on NSE become *pipeline* issues |
| `nse_equity_list` | NSE listed-equity lists | 2026-10-31 | `nsearchives.nseindia.com/content/equities/EQUITY_L.csv`, `…/emerge/corporates/content/SME_EQUITY_L.csv` | symbol ↔ company name, to match listed peers to the bhavcopy; face value and ISIN of every listed issue (fallback when the issue page lacked them) |
| `nse_shareholding` | NSE shareholding-pattern filings | 2026-11-02 | `www.nseindia.com/api/corporate-share-holdings-master?index=equities|sme&symbol=…` (JSON behind NSE's own shareholding-pattern pages; robots.txt allows `/api/`) | promoter and promoter-group % per filing; the pattern stated as of the day before listing (LODR Reg. 31(1)(a)) is the official **post-issue promoter holding**; the latest filing is shown as the current holding |

### Request discipline

* One request at a time per host, ≥ 2.5 s apart; streamed downloads with size caps (prospectus ≤ 80 MB).
* Bounded retries with exponential backoff for timeouts and 5xx only; **401/403/429 are never retried**
  — they mean the source refused automated access.
* Documents: HEAD first (ETag, Last-Modified); download only when new or changed; content hash detects
  revisions. Failed documents back off 1, 2, 4, 8 h … up to 7 days, then become dead letters.
* Short-lived response caching so jobs in one run share one request; bhavcopies and equity lists cached on disk.

### Schedule (in the API process, or `python -m app.cli worker`)

| Job | Every | Requests |
|---|---|---|
| discover | 6 h | 3 list calls |
| details | 6 h | ≤ 15 issue-detail calls: upcoming/open/just-closed issues every run; any other issue still missing an NSE field (face value, lot, band, registrar, lead managers, RHP link, issue type, ISIN) once a week |
| subscriptions | 20 min | only while an issue is open; none otherwise |
| listings | 45 min | listing confirmations; one bhavcopy per listing day (cached) |
| filings | 12 h | 2 SEBI listing pages |
| documents | 1 h | ≤ 3 documents (HEAD + download + filing page for SEBI) |
| peers | 24 h | 2 equity lists + 1 bhavcopy (all cached daily) |
| enrichment | 6 h | re-reads stored offer documents when the offer-terms extractor changes (no requests); 2 equity lists (cached daily); ≤ 15 shareholding-pattern calls for listed issues without an official post-issue promoter holding (daily for a month after listing, then weekly, then monthly) |
| health | 30 min | BSE probe at most daily; rescoring (no requests) |

## Not connected

| Source | Status | What happens instead |
|---|---|---|
| NSE quote API | "Access Denied" (anti-bot) | not used; peers priced from the official bhavcopy |
| BSE (`api.bseindia.com`) | refused / redirected for automated requests (re-checked 2026-10-31: HTTP 301) | probed at most daily and reported; BSE-only issues need a manual CSV/JSON import |
| SEBI listing pages beyond the first | need a form POST with a session token | not automated; new filings appear on the first page |
| Company investor-relations sites | no common structure | not crawled; restated financials come from the offer document |
| Registrars (allotment status) | per-application lookups behind forms/CAPTCHA | not used; allotment dates are SEBI T+3 estimates until confirmed |
| Grey-market premium sites | unofficial, unverifiable | not used; never scored |
| Moneycontrol IPO pages | re-checked 2026-11-02: an honest automated client gets "Access Denied" (HTTP 403) even for `robots.txt` — anti-bot protection | not fetched. Used only as a **reference checklist** of what an IPO page should show (face value, lot, issue size, shares offered, promoter holding, promoters, objects, registrar, lead managers, website); every one of those fields now comes from NSE, the offer document or an NSE filing |
| NSE "Ratios / Basis of issue price" archives | newspaper price-band advertisements, mostly scanned images | not read; P/E comes from verified statements and post-issue shares |

## Field-level sources and fallbacks (issue data)

| Field | Primary | Fallbacks, in order |
|---|---|---|
| Face value | NSE issue page (`Face Value`; Rs./Re./₹/INR prefixes) | offer-document cover (the value stated most often in the opening pages; two values stated comparably often → refused) → NSE equity list after listing |
| Lot size | NSE issue page (`Bid Lot` on mainboard pages, `Lot Size` on SME pages) | NSE list endpoints |
| Issue type | NSE `Issue Type` (Book Building / Fixed Price) | offer-document cover ("Book Built Issue" / "Fixed Price Issue") |
| Final issue price | NSE past issues | a fixed-price issue's stated price |
| ISIN | NSE issue metadata | NSE equity list after listing |
| Shares before the issue | offer document (capital structure / offer summary) | — |
| Shares after the issue | offer document when printed (fixed share counts) | pre-issue shares + NSE fresh-issue share count (exact) → + fresh-issue ₹ ÷ price (estimated at the upper band until the price is final) → equal to pre-issue shares for an offer for sale only |
| Promoter holding before the issue | offer document shareholding pattern ((A) promoter & promoter group row; accepted only when promoter + public = 100% ±0.6 pt) | — |
| Promoter holding after the issue | NSE shareholding pattern filed for listing (official) | derived for fresh-issue-only offers (pre % × pre-issue shares ÷ post-issue shares); with an offer for sale it waits for the filing |
| Listing exchanges, promoters, company website, objects of the issue | offer-document cover / 'Objects of the Issue' chapter | — |

## Fields no connected source provides

Stay **unavailable** with the reason, never estimated: litigation counts (tables too varied to read
reliably), financials of prospectuses whose statements are scanned *and* defeat OCR (e.g. totals printed
in shaded boxes), lender asset-quality ratios in verified form, and any offer-document field whose page
does not match the patterns above (the research page names the gap and the sources tried).

## Licences and terms

Exchange and regulator pages are read as published, for educational research, at a low request rate.
Check each source's current terms before redistributing data. PyMuPDF is AGPL-3.0 (free for open,
self-hosted use); Tesseract is Apache-2.0.
