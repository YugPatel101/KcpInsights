"""NSE adapters (official exchange data).

Verified on 2026-10-29 from this environment with a plain, honest User-Agent and no
cookies: the JSON endpoints that power NSE's public IPO pages, and the official daily
bhavcopy archive. NSE's robots.txt allows these paths. The equity quote API returns
"Access Denied" (anti-bot protection) and is deliberately NOT used.

Field semantics (checked against the payloads):
* ``issueSize`` in the list endpoints is a number of *shares* offered in public bidding, not rupees.
* ``noOfTime`` in ``ipo-current-issue`` covers NSE bids only. The consolidated (all-exchange)
  multiple per category comes from ``activeCat`` / ``ipo-active-category`` with an
  "Updated as on" timestamp; only that one is stored as the subscription figure.
* ``public-past-issues`` gives the final issue price and the actual listing date.
* Listing-day open/close prices come from the bhavcopy of the listing date (``OpnPric``,
  ``ClsPric``); ``PrvsClsgPric`` on that day equals the issue price and is used as a cross-check.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

from app.config import get_settings
from app.ingestion import normalizer as nz
from app.ingestion.http import PoliteClient, SourceError
from app.ingestion.sources.base import FetchResult, IPODataSource, IssueRecord, ListingPriceRecord, SubscriptionRecord

BASE = "https://www.nseindia.com"
LIST_PAGE = f"{BASE}/market-data/all-upcoming-issues-ipo"
ARCHIVE = "https://nsearchives.nseindia.com"
MAX_LISTING_LAG_DAYS = 30


def issue_page(symbol: str, series: str, kind: str) -> str:
    return f"{BASE}/market-data/issue-information?symbol={symbol}&series={series}&type={kind}"


class NSEOfficialSource(IPODataSource):
    key = "nse_ipo"
    name = "NSE public issue information"
    authority = "official"

    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    # ----------------------------------------------------------------- lists
    def _list_record(self, row: dict, kind: str, api_url: str) -> IssueRecord | None:
        symbol = str(row.get("symbol") or "").strip()
        name = str(row.get("companyName") or row.get("company") or "").strip()
        series = str(row.get("series") or row.get("securityType") or "").strip().upper()
        itype = nz.issue_type_for_series(series)
        if not symbol or not name or itype is None:
            return None  # debt, REIT units with unknown series, etc.
        lo, hi = nz.parse_price_band(row.get("priceBand") or row.get("issuePrice") or row.get("priceRange"))
        rec = IssueRecord(
            symbol=symbol,
            company_name=name,
            series=series,
            issue_type=itype,
            source_url=issue_page(symbol, series, kind) if kind != "Past" else LIST_PAGE,
            api_url=api_url,
            open_date=nz.parse_date(row.get("issueStartDate") or row.get("ipoStartDate")),
            close_date=nz.parse_date(row.get("issueEndDate") or row.get("ipoEndDate")),
            price_band_low=lo,
            price_band_high=hi,
            lot_size=int(nz.parse_number(row.get("lotSize")) or 0) or None,
            shares_offered=nz.parse_number(row.get("issueSize")) if kind != "Past" else None,
            status_text=row.get("status"),
        )
        if kind == "Past":
            rec.final_issue_price = nz.parse_number(row.get("issuePrice"))
            rec.listing_date = nz.parse_date(row.get("listingDate"))
            rec.price_band_low, rec.price_band_high = nz.parse_price_band(row.get("priceRange"))
        if rec.open_date and rec.close_date and rec.close_date < rec.open_date:
            rec.warnings.append("close date before open date in source; dates ignored")
            rec.open_date = rec.close_date = None
        return rec

    def _fetch_list(self, path: str, kind: str) -> FetchResult[list[IssueRecord]]:
        url = f"{BASE}/{path}"
        try:
            rows = self.client.get_json(url, cache_ttl=300)
        except SourceError as exc:
            return FetchResult.unavailable(f"{exc.kind}: {exc}")
        if not isinstance(rows, list):
            return FetchResult.unavailable("parse: expected a JSON list")
        out = [r for r in (self._list_record(x, kind, url) for x in rows if isinstance(x, dict)) if r]
        return FetchResult.ok(out, LIST_PAGE)

    def fetch_upcoming_ipos(self) -> FetchResult[list[IssueRecord]]:
        return self._fetch_list("api/all-upcoming-issues?category=ipo", "Forthcoming")

    def fetch_open_ipos(self) -> FetchResult[list[IssueRecord]]:
        return self._fetch_list("api/ipo-current-issue", "Active")

    def fetch_recently_listed_ipos(self, since: date) -> FetchResult[list[IssueRecord]]:
        res = self._fetch_list("api/public-past-issues", "Past")
        if res.status != "ok" or res.data is None:
            return res
        recent = []
        for r in res.data:
            if (r.listing_date or r.close_date or date.min) < since:
                continue
            # Only genuine IPO listings: they list within days of the issue closing. Later
            # "listings" in this feed are migrations/relistings or debt series (e.g. NCDs).
            if r.listing_date and r.close_date and not 0 <= (r.listing_date - r.close_date).days <= MAX_LISTING_LAG_DAYS:
                continue
            if r.final_issue_price and r.price_band_high and not (r.price_band_low or 0) * 0.9 <= r.final_issue_price <= r.price_band_high:
                continue  # issue price outside its own band: not an equity IPO record
            recent.append(r)
        return FetchResult.ok(recent, LIST_PAGE)

    # ----------------------------------------------------------------- detail / subscription
    @staticmethod
    def parse_subscription(rows: list, update_time: object, basis: str = "consolidated") -> list[SubscriptionRecord]:
        as_of = nz.parse_update_time(update_time)
        if as_of is None:
            return []  # without a timestamp a subscription figure is not stored
        out: list[SubscriptionRecord] = []
        for r in rows:
            if not isinstance(r, dict) or r.get("srNo") == "Sr.No.":
                continue
            cat = nz.subscription_category(str(r.get("category") or ""), r.get("srNo"))
            times = nz.parse_number(r.get("noOfTotalMeant") if "noOfTotalMeant" in r else r.get("noOfTime"))
            if cat is None or times is None:
                continue
            out.append(SubscriptionRecord(
                category=cat, times_subscribed=times, as_of=as_of, basis=basis,
                shares_offered=nz.parse_number(r.get("noOfShareOffered") or r.get("noOfSharesOffered")),
                shares_bid=nz.parse_number(r.get("noOfSharesBid") or r.get("noOfsharesBid")),
            ))
        return out

    def fetch_ipo_details(self, symbol: str, series: str) -> FetchResult[tuple[IssueRecord, list[SubscriptionRecord]]]:
        url = f"{BASE}/api/ipo-detail?symbol={symbol}&series={series}"
        try:
            d = self.client.get_json(url, cache_ttl=300)
        except SourceError as exc:
            return FetchResult.unavailable(f"{exc.kind}: {exc}")
        if not isinstance(d, dict):
            return FetchResult.unavailable("parse: expected a JSON object")
        info = {str(r.get("title") or "").strip(): r.get("value") for r in (d.get("issueInfo") or {}).get("dataList", []) if isinstance(r, dict)}
        meta = d.get("metaInfo") or {}
        itype = nz.issue_type_for_series(series) or "mainboard"
        name = meta.get("companyName") or next((t for t, v in info.items() if t and v == ""), None) or symbol
        rec = IssueRecord(
            symbol=symbol, company_name=str(name), series=series, issue_type=itype,
            source_url=issue_page(symbol, series, "Active"), api_url=url,
        )
        period = str(info.get("Issue Period") or "")
        if " to " in period:
            a, b = period.split(" to ", 1)
            rec.open_date, rec.close_date = nz.parse_date(a), nz.parse_date(b)
        rec.price_band_low, rec.price_band_high = nz.parse_price_band(info.get("Price Range"))
        rec.face_value = nz.parse_rupees_per_share(info.get("Face Value"))
        rec.lot_size = nz.parse_first_int(info.get("Bid Lot"))
        rec.registrar = nz.strip_html(info.get("Name of the Registrar"))
        rec.lead_managers = nz.strip_html(info.get("Book Running Lead Managers"))
        rec.offer_document_url = nz.first_url(info.get("Red Herring Prospectus") or info.get("Prospectus"))
        rec.basis_of_price_url = nz.first_url(info.get("Ratios / Basis of Issue Price"))
        rec.issue_size_text = nz.strip_html(info.get("Issue Size"))
        rec.industry = meta.get("industry") or None
        rec.isin = meta.get("isin") or None
        if meta.get("listingDate"):
            rec.listing_date = nz.parse_date(str(meta["listingDate"]))
        active = d.get("activeCat") or {}
        subs = self.parse_subscription(active.get("dataList") or [], active.get("updateTime"))
        return FetchResult.ok((rec, subs), rec.source_url)

    def fetch_subscription_data(self, symbol: str) -> FetchResult[list[SubscriptionRecord]]:
        url = f"{BASE}/api/ipo-active-category?symbol={symbol}"
        try:
            d = self.client.get_json(url, cache_ttl=120)
        except SourceError as exc:
            return FetchResult.unavailable(f"{exc.kind}: {exc}")
        if not isinstance(d, dict):
            return FetchResult.unavailable("parse: expected a JSON object")
        subs = self.parse_subscription(d.get("dataList") or [], d.get("updateTime"))
        if not subs:
            return FetchResult.unavailable("no timestamped subscription data published yet")
        return FetchResult.ok(subs, LIST_PAGE)

    def health_check(self) -> FetchResult[str]:
        res = self.fetch_upcoming_ipos()
        return FetchResult.ok(f"{len(res.data or [])} issues listed") if res.status == "ok" else FetchResult.unavailable(res.error or "unavailable")


class NSEBhavcopySource:
    """Official daily equity bhavcopy (one file per trading day) — listing-day prices."""

    key = "nse_bhavcopy"
    name = "NSE daily bhavcopy (archives)"
    authority = "official"

    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    @staticmethod
    def url_for(d: date) -> str:
        return f"{ARCHIVE}/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"

    @staticmethod
    def parse_csv(text: str, url: str) -> dict[str, ListingPriceRecord]:
        out: dict[str, ListingPriceRecord] = {}
        for row in csv.DictReader(io.StringIO(text)):
            series = (row.get("SctySrs") or "").strip().upper()
            if series not in nz.EQUITY_SERIES:
                continue
            sym = (row.get("TckrSymb") or "").strip()
            op = nz.parse_number(row.get("OpnPric"))
            td = nz.parse_date(row.get("TradDt") or "")
            if not sym or op is None or td is None:
                continue
            out[sym] = ListingPriceRecord(
                symbol=sym, trade_date=td, open_price=op, close_price=nz.parse_number(row.get("ClsPric")),
                previous_close=nz.parse_number(row.get("PrvsClsgPric")), series=series, isin=row.get("ISIN") or None, source_url=url,
                high_price=nz.parse_number(row.get("HghPric")), low_price=nz.parse_number(row.get("LwPric")),
            )
        return out

    def fetch_day(self, d: date) -> FetchResult[dict[str, ListingPriceRecord]]:
        s = get_settings()
        cache = s.cache_dir / "bhavcopy" / f"{d:%Y%m%d}.csv"
        url = self.url_for(d)
        if cache.exists():
            return FetchResult.ok(self.parse_csv(cache.read_text(), url), url)
        try:
            body, _ = self.client.get(url, max_bytes=20 * 1024 * 1024)
        except SourceError as exc:
            if exc.status == 404:
                return FetchResult.unavailable("bhavcopy not published for this date (holiday or not yet available)")
            return FetchResult.unavailable(f"{exc.kind}: {exc}")
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if len(names) != 1 or zf.getinfo(names[0]).file_size > 100 * 1024 * 1024:
                    return FetchResult.unavailable("unexpected archive contents")
                text = zf.read(names[0]).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            return FetchResult.unavailable("parse: not a zip archive")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text)  # bhavcopies are immutable once published
        return FetchResult.ok(self.parse_csv(text, url), url)


class NSEEquityList:
    """Official lists of NSE-listed equities (mainboard and SME): symbol and company name, used to match listed peers.

    ``content/equities/EQUITY_L.csv`` and ``emerge/corporates/content/SME_EQUITY_L.csv`` on the NSE archive host (verified
    2026-10-31). Cached for a day.
    """

    URLS = (f"{ARCHIVE}/content/equities/EQUITY_L.csv", f"{ARCHIVE}/emerge/corporates/content/SME_EQUITY_L.csv")

    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    @staticmethod
    def parse(text: str) -> dict[str, str]:
        """normalised company name -> symbol"""
        out: dict[str, str] = {}
        for row in csv.DictReader(io.StringIO(text)):
            row = {k.strip().upper(): (v or "").strip() for k, v in row.items() if k}
            sym, name = row.get("SYMBOL"), row.get("NAME OF COMPANY") or row.get("NAME_OF_COMPANY")
            if sym and name:
                out.setdefault(nz.normalize_company_name(name), sym)
        return out

    def fetch(self, today: date) -> FetchResult[dict[str, str]]:
        s = get_settings()
        merged: dict[str, str] = {}
        for url in self.URLS:
            cache = s.cache_dir / "equity_list" / f"{today:%Y%m%d}_{url.rsplit('/', 1)[-1]}"
            if cache.exists():
                text = cache.read_text()
            else:
                try:
                    body, _ = self.client.get(url, max_bytes=5 * 1024 * 1024)
                except SourceError as exc:
                    return FetchResult.unavailable(f"{exc.kind}: {exc}")
                text = body.decode("utf-8", errors="replace")
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text)
            for k, v in self.parse(text).items():
                merged.setdefault(k, v)
        return FetchResult.ok(merged, self.URLS[0])
