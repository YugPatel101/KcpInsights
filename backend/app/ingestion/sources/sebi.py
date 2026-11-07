"""SEBI public-issue filings (official): draft and red herring offer documents.

Verified on 2026-10-31 from this environment with the honest KcpInsights User-Agent and no cookies:

* ``robots.txt`` disallows only ``/js`` and ``/css``.
* The listing pages ``HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10`` (draft offer documents
  filed with SEBI) and ``smid=11`` (red herring documents filed with the RoC) answer a plain GET
  with the 25 most recent filings. Older pages are reached through a form POST carrying a
  session token, which KcpInsights does not automate — new filings appear at the top, so polling
  the first page daily is enough for incremental discovery.
* Each filing page embeds the PDF in an iframe (``/web/?file=https://www.sebi.gov.in/sebi_data/
  attachdocs/<month>/<id>.PDF``); the PDF answers HEAD with Content-Length and Last-Modified.

Mainboard offer documents are filed with SEBI; SME offer documents are filed with the exchange
and therefore do not appear here.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlparse

from app.ingestion.http import PoliteClient, SourceError
from app.ingestion.sources.base import FetchResult

BASE = "https://www.sebi.gov.in"
LISTING = {
    "drhp": f"{BASE}/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10",
    "rhp": f"{BASE}/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=11",
}
SEBI_HOSTS = {"www.sebi.gov.in", "sebi.gov.in"}

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_DATE = re.compile(r"<td>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</td>")
_LINK = re.compile(r'<a href="(https://www\.sebi\.gov\.in/filings/public-issues/[^"]+\.html)"[^>]*title="([^"]*)"', re.I)
_PDF = re.compile(r"file=(https://www\.sebi\.gov\.in/sebi_data/attachdocs/[A-Za-z0-9_\-/]+\.pdf)", re.I)
# "Company Ltd.- RHP", "Company Limited - DRHP", "Company Limited- UDRHP-1"; addenda, notices and abridged
# prospectuses are separate filings and are not offer documents in themselves.
_KIND = re.compile(r"^(?P<company>.+?)\s*[-–]\s*(?P<kind>U?DRHP(?:\s*[-–]?\s*[IVX\d]+)?|RHP|Red Herring Prospectus|Draft Red Herring Prospectus)\s*$", re.I)


@dataclass(frozen=True)
class Filing:
    company_name: str
    kind: str  # drhp | rhp
    title: str
    filed_on: date
    filing_url: str


def parse_listing(text: str, listing: str) -> list[Filing]:
    """Offer-document filings on one SEBI listing page (addenda, notices and abridged documents skipped)."""
    out: list[Filing] = []
    for row in _ROW.findall(text):
        d, link = _DATE.search(row), _LINK.search(row)
        if not d or not link:
            continue
        title = html.unescape(link.group(2).split("<br")[0]).strip()
        m = _KIND.match(title)
        if not m:
            continue
        kind = "drhp" if re.match(r"(?i)u?drhp|draft", m.group("kind")) else "rhp"
        if listing == "drhp" and kind != "drhp":
            continue
        out.append(Filing(company_name=m.group("company").strip(" .-–"), kind=kind, title=title,
                          filed_on=datetime.strptime(d.group(1), "%b %d, %Y").date(), filing_url=link.group(1)))
    return out


def pdf_url_from_filing(text: str) -> str | None:
    m = _PDF.search(text)
    if not m:
        return None
    url = m.group(1)
    return url if urlparse(url).hostname in SEBI_HOSTS else None


class SEBIFilingsSource:
    key = "sebi_offer_documents"
    name = "SEBI offer documents"
    authority = "official"

    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    def fetch_filings(self, listing: str) -> FetchResult[list[Filing]]:
        url = LISTING[listing]
        try:
            body, ctype = self.client.get(url, max_bytes=2 * 1024 * 1024)
        except SourceError as exc:
            return FetchResult.unavailable(f"{exc.kind}: {exc}")
        if "html" not in ctype:
            return FetchResult.unavailable(f"parse: expected HTML, received {ctype or 'unknown type'}")
        filings = parse_listing(body.decode("utf-8", "replace"), listing)
        if not filings and "public-issues" not in body.decode("utf-8", "replace"):
            return FetchResult.unavailable("parse: listing layout changed (no filing links found)")
        return FetchResult.ok(filings, url)

    def resolve_pdf(self, filing_url: str) -> str:
        """The PDF behind one filing page (one request). Raises SourceError when the page has none."""
        if urlparse(filing_url).hostname not in SEBI_HOSTS:
            raise SourceError("parse", "filing URL is not on sebi.gov.in")
        body, _ = self.client.get(filing_url, max_bytes=1024 * 1024)
        url = pdf_url_from_filing(body.decode("utf-8", "replace"))
        if url is None:
            raise SourceError("parse", "no offer-document PDF linked on the SEBI filing page")
        return url
