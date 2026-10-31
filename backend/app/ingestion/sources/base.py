"""Common source-adapter interface and normalised record types.

Adapters are synchronous (they run in the scheduler's worker thread) and must never
return invented data: an unsupported operation returns ``FetchResult.unsupported``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

T = TypeVar("T")


@dataclass
class FetchResult(Generic[T]):
    status: Literal["ok", "unsupported", "unavailable"]
    data: T | None = None
    error: str | None = None
    source_url: str | None = None

    @classmethod
    def ok(cls, data: T, source_url: str | None = None) -> FetchResult[T]:
        return cls("ok", data, None, source_url)

    @classmethod
    def unsupported(cls, why: str) -> FetchResult[T]:
        return cls("unsupported", None, why)

    @classmethod
    def unavailable(cls, why: str) -> FetchResult[T]:
        return cls("unavailable", None, why)


@dataclass
class IssueRecord:
    """One public issue as reported by a source. ``None`` means the source did not report it."""

    symbol: str
    company_name: str
    series: str
    issue_type: str  # mainboard | sme
    source_url: str  # human-readable page for citations
    api_url: str
    open_date: date | None = None
    close_date: date | None = None
    price_band_low: float | None = None
    price_band_high: float | None = None
    final_issue_price: float | None = None
    lot_size: int | None = None
    shares_offered: float | None = None
    face_value: float | None = None
    listing_date: date | None = None  # always an *actual* listing date when set by an adapter
    industry: str | None = None
    isin: str | None = None
    registrar: str | None = None
    lead_managers: str | None = None
    offer_document_url: str | None = None
    basis_of_price_url: str | None = None
    issue_size_text: str | None = None
    status_text: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class SubscriptionRecord:
    category: str  # qib | nii | retail | employee | shareholder | total
    times_subscribed: float
    as_of: datetime
    basis: str  # consolidated | nse_only
    shares_offered: float | None = None
    shares_bid: float | None = None


@dataclass
class ListingPriceRecord:
    symbol: str
    trade_date: date
    open_price: float
    close_price: float | None
    previous_close: float | None  # on listing day this is the issue price
    series: str
    isin: str | None
    source_url: str
    high_price: float | None = None
    low_price: float | None = None


class IPODataSource:
    key = "base"
    name = "base"
    authority = "official"

    def fetch_upcoming_ipos(self) -> FetchResult[list[IssueRecord]]:
        return FetchResult.unsupported("not supported by this source")

    def fetch_open_ipos(self) -> FetchResult[list[IssueRecord]]:
        return FetchResult.unsupported("not supported by this source")

    def fetch_recently_listed_ipos(self, since: date) -> FetchResult[list[IssueRecord]]:
        return FetchResult.unsupported("not supported by this source")

    def fetch_ipo_details(self, symbol: str, series: str) -> FetchResult[tuple[IssueRecord, list[SubscriptionRecord]]]:
        return FetchResult.unsupported("not supported by this source")

    def fetch_subscription_data(self, symbol: str) -> FetchResult[list[SubscriptionRecord]]:
        return FetchResult.unsupported("not supported by this source")

    def health_check(self) -> FetchResult[str]:
        return FetchResult.unsupported("no health check")
