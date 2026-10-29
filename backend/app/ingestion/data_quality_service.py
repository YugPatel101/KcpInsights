"""Freshness, staleness and missing-field checks for stored IPO data."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DataMode, DataSource, IngestionJob, IPOIssue, SubscriptionSnapshot, utcnow

IST_OFFSET = timedelta(hours=5, minutes=30)


def now_ist(now_utc: datetime | None = None) -> datetime:
    return (now_utc or utcnow()) + IST_OFFSET


def latest_subscription_time(ipo: IPOIssue) -> datetime | None:
    snaps = [s.as_of for s in ipo.subscriptions if s.basis == "consolidated"]
    return max(snaps) if snaps else None


def ipo_freshness(ipo: IPOIssue, status: str, now_utc: datetime | None = None) -> dict[str, Any]:
    """Stale-data assessment for one IPO. Only live (source-mode) records can be stale."""
    s = get_settings()
    now = now_utc or utcnow()
    live = ipo.data_mode == DataMode.source.value
    out: dict[str, Any] = {
        "live": live,
        "last_verified_at": ipo.last_verified_at.isoformat() if ipo.last_verified_at else None,
        "is_stale": False,
        "stale_reasons": [],
        "missing_critical": [],
    }
    if not live:
        out["note"] = "Not a live record (demo or imported); freshness depends on the import."
        return out
    if status in ("upcoming", "open", "closed"):
        if ipo.last_verified_at is None or now - ipo.last_verified_at > timedelta(hours=s.stale_issue_details_hours):
            out["is_stale"] = True
            out["stale_reasons"].append(f"issue details not re-verified for more than {s.stale_issue_details_hours} h")
    if status == "closed" and ipo.listing_date_status == "expected" and ipo.listing_date and ipo.listing_date < (now + IST_OFFSET).date() - timedelta(days=3):
        days = ((now + IST_OFFSET).date() - ipo.listing_date).days
        out["is_stale"] = True
        out["listing_unconfirmed"] = True
        out["stale_reasons"].append(
            f"listing not confirmed on NSE {days} days after the expected date (it may have listed on BSE only, been delayed or withdrawn)")
    if status == "open":
        ist = now_ist(now)
        sub_at = latest_subscription_time(ipo)  # NSE timestamps are IST
        in_session = time(10, 0) <= ist.time() <= time(19, 0)
        if in_session and (sub_at is None or ist - sub_at > timedelta(minutes=s.stale_subscription_minutes)):
            out["is_stale"] = True
            out["stale_reasons"].append(f"subscription not updated in the last {s.stale_subscription_minutes} min of the bidding session")
    req: list[tuple[str, Any]] = [("price band", ipo.price_band_high), ("open date", ipo.open_date), ("close date", ipo.close_date),
                                  ("lot size", ipo.lot_size), ("issue size (₹)", ipo.issue_size_cr)]
    if status in ("closed", "listed"):
        req.append(("listing date", ipo.listing_date))
    if status == "listed":
        req += [("final issue price", ipo.final_issue_price), ("listing price", ipo.listing_price)]
    out["missing_critical"] = [name for name, v in req if v is None]
    return out


def source_overview(db: Session) -> list[dict[str, Any]]:
    s = get_settings()
    stale_after = {"nse_ipo": timedelta(minutes=3 * s.ingest_discovery_minutes), "nse_bhavcopy": timedelta(days=3)}
    out = []
    now = utcnow()
    for src in db.execute(select(DataSource).order_by(DataSource.id)).scalars():
        limit = stale_after.get(src.key)
        stale = bool(limit and src.access_mode == "automatic" and (src.last_success_at is None or now - src.last_success_at > limit))
        out.append({
            "key": src.key, "name": src.name, "base_url": src.base_url, "authority": src.authority, "access_mode": src.access_mode,
            "health_status": src.health_status, "last_attempt_at": src.last_attempt_at.isoformat() if src.last_attempt_at else None,
            "last_success_at": src.last_success_at.isoformat() if src.last_success_at else None, "last_error": src.last_error,
            "consecutive_failures": src.consecutive_failures, "requests_made": src.requests_made, "is_stale": stale, "notes": src.notes,
        })
    return out


def last_successful_job(db: Session, job_type: str | None = None) -> IngestionJob | None:
    q = select(IngestionJob).where(IngestionJob.status.in_(("success", "partial")))
    if job_type:
        q = q.where(IngestionJob.job_type == job_type)
    return db.execute(q.order_by(IngestionJob.id.desc()).limit(1)).scalar_one_or_none()


def subscription_rows(db: Session, ipo_id: int) -> list[SubscriptionSnapshot]:
    return list(db.execute(select(SubscriptionSnapshot).where(SubscriptionSnapshot.ipo_id == ipo_id).order_by(SubscriptionSnapshot.as_of)).scalars())


def is_open_today(ipo: IPOIssue, today: date) -> bool:
    return bool(ipo.open_date and ipo.close_date and ipo.open_date <= today <= ipo.close_date)
