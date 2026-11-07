"""Registry of data sources, their authority and how they are accessed."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, utcnow


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    base_url: str
    authority: str  # official | secondary | manual
    access_mode: str  # automatic | manual_only
    notes: str


SOURCES: list[SourceSpec] = [
    SourceSpec("nse_ipo", "NSE public issue information", "https://www.nseindia.com/market-data/all-upcoming-issues-ipo", "official", "automatic",
               "Upcoming/open/past issues, issue details, consolidated subscription. Public JSON used by NSE's own pages; robots.txt allows."),
    SourceSpec("nse_bhavcopy", "NSE daily bhavcopy (archives)", "https://nsearchives.nseindia.com/content/cm/", "official", "automatic",
               "Listing-day open and close prices from the official end-of-day file."),
    SourceSpec("nse_rhp", "Offer documents (RHP) in NSE archives", "https://nsearchives.nseindia.com/content/ipo/", "official", "automatic",
               "Red Herring Prospectus archives linked from each NSE issue page. Restated balance sheet, P&L, cash flow, listed peers and "
               "key disclosures are extracted from the PDF text layer and reconciled; scanned (image-only) pages cannot be read."),
    SourceSpec("bse_ipo", "BSE public issues", "https://www.bseindia.com/markets/PublicIssues/IPOIssues_new.aspx", "official", "manual_only",
               "Automated requests are refused (Access Denied). Use manual CSV/JSON import for BSE-only issues."),
    SourceSpec("sebi_offer_documents", "SEBI offer documents (DRHP / RHP filings)",
               "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=11", "official", "automatic",
               "First page of the draft (DRHP) and red herring (RHP) filing lists, polled twice a day; robots.txt allows. New companies "
               "become pipeline issues; a SEBI RHP is read only when the NSE copy could not be. Older pages need a form token and are "
               "not automated. SME offer documents are filed with the exchange, not SEBI."),
    SourceSpec("nse_equity_list", "NSE listed-equity lists (archives)", "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", "official",
               "automatic", "Symbol, company name, face value and ISIN of every NSE mainboard and SME equity; used to match listed peers to "
               "the daily bhavcopy and as the fallback for a listed issue's face value and ISIN."),
    SourceSpec("nse_shareholding", "NSE shareholding-pattern filings", "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
               "official", "automatic", "Promoter and public shareholding filed by each listed company (SEBI LODR Regulation 31). The pattern "
               "filed for listing gives the post-issue promoter holding. Public JSON used by NSE's own pages; robots.txt allows."),
    SourceSpec("company_ir", "Company investor-relations pages", "", "official", "manual_only",
               "Not crawled automatically (no common structure). Restated financials come from the offer document instead."),
    SourceSpec("user_import", "User-imported research", "", "manual", "manual_only", "CSV/JSON imports with stated provenance."),
]

# Higher number wins when two sources report different values for the same field.
AUTHORITY_RANK = {"official": 3, "manual_verified": 3, "manual": 2, "secondary": 1}
SOURCE_AUTHORITY = {s.key: s.authority for s in SOURCES}


def authority_of(source_key: str) -> int:
    return AUTHORITY_RANK.get(SOURCE_AUTHORITY.get(source_key, "manual"), 1)


def ensure_sources(db: Session) -> dict[str, DataSource]:
    rows = {r.key: r for r in db.execute(select(DataSource)).scalars()}
    for spec in SOURCES:
        row = rows.get(spec.key)
        if row is None:
            row = DataSource(key=spec.key, name=spec.name, base_url=spec.base_url, authority=spec.authority, access_mode=spec.access_mode,
                             notes=spec.notes, health_status="manual" if spec.access_mode == "manual_only" else "unknown")
            db.add(row)
            rows[spec.key] = row
        else:
            row.name, row.base_url, row.authority, row.access_mode, row.notes = spec.name, spec.base_url, spec.authority, spec.access_mode, spec.notes
    db.commit()
    return rows


def record_source_result(db: Session, key: str, ok: bool, error: str | None = None, requests: int = 0) -> None:
    src = ensure_sources(db)[key]
    now = utcnow()
    src.last_attempt_at = now
    src.requests_made += requests
    if ok:
        src.last_success_at = now
        src.consecutive_failures = 0
        src.health_status = "healthy"
        src.last_error = None
    else:
        src.consecutive_failures += 1
        src.last_error = (error or "unknown error")[:1000]
        if error and ("access_denied" in error or error.startswith("blocked")):
            src.health_status = "blocked"
        else:
            src.health_status = "down" if src.consecutive_failures >= 3 else "degraded"
    db.commit()
