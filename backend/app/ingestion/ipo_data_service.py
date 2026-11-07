"""Upsert normalised source records into the database with field-level provenance.

Precedence rule (documented in README):
1. A value from a higher-authority source replaces a lower-authority one.
2. Between equal-authority sources the most recent observation wins, and the
   disagreement is flagged as a conflict on the observation.
3. A lower-authority value never overwrites a higher-authority one; it is recorded
   with ``applied = False, conflict = True``.
4. An estimate never overwrites a sourced value.
Every observation is kept; unchanged re-observations only refresh ``last_verified_at``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion import normalizer as nz
from app.ingestion.source_registry import authority_of
from app.ingestion.sources.base import IssueRecord, ListingPriceRecord, ShareholdingRecord, SubscriptionRecord
from app.models import (
    Company,
    DataMode,
    FieldChange,
    FieldObservation,
    IPOIssue,
    SourceRecord,
    SubscriptionSnapshot,
    utcnow,
)

# IssueRecord attribute -> IPOIssue attribute
FIELD_MAP = {
    "open_date": "open_date",
    "close_date": "close_date",
    "price_band_low": "price_band_low",
    "price_band_high": "price_band_high",
    "final_issue_price": "final_issue_price",
    "lot_size": "lot_size",
    "shares_offered": "shares_offered",
    "face_value": "face_value",
    "listing_date": "listing_date",
    "registrar": "registrar",
    "lead_managers": "lead_managers",
    "offer_document_url": "offer_document_url",
    "basis_of_price_url": "basis_of_price_url",
    "issue_size_text": "issue_size_text",
    "isin": "isin",
    "issue_method": "issue_method",
}
IMPORTANT_FIELDS = {
    "open_date", "close_date", "price_band_low", "price_band_high", "final_issue_price", "lot_size",
    "listing_date", "listing_price", "issue_size_cr", "allotment_date",
}
T3_START = date(2023, 12, 1)  # SEBI's mandatory T+3 listing timeline applies to issues closing after this
ESTIMATE_BASIS = "SEBI T+3 timeline counted from the issue close; weekends skipped, exchange holidays NOT applied"


@dataclass
class UpsertStats:
    discovered: int = 0
    created: int = 0
    updated: int = 0
    fields_changed: int = 0
    warnings: list[str] = field(default_factory=list)
    changed_ipo_ids: set[int] = field(default_factory=set)

    def merge(self, other: UpsertStats) -> None:
        self.discovered += other.discovered
        self.created += other.created
        self.updated += other.updated
        self.fields_changed += other.fields_changed
        self.warnings += other.warnings
        self.changed_ipo_ids |= other.changed_ipo_ids


def _enc(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return json.dumps(v.isoformat())
    return json.dumps(v)


def _latest_obs(db: Session, ipo_id: int, fld: str, applied_only: bool = True) -> FieldObservation | None:
    q = select(FieldObservation).where(FieldObservation.ipo_id == ipo_id, FieldObservation.field == fld)
    if applied_only:
        q = q.where(FieldObservation.applied.is_(True))
    return db.execute(q.order_by(FieldObservation.id.desc()).limit(1)).scalar_one_or_none()


def _implicit_source(ipo: IPOIssue) -> str:
    """Source key for values that predate field-level tracking (imports, demo)."""
    if ipo.data_mode == DataMode.demo.value:
        return "demo"
    if ipo.data_status == "verified":
        return "manual_verified"
    return "user_import"


def set_field(
    db: Session,
    ipo: IPOIssue,
    fld: str,
    new: Any,
    *,
    source_key: str,
    source_url: str | None,
    status: str,
    basis: str | None = None,
    now: datetime | None = None,
    stats: UpsertStats,
) -> bool:
    """Apply one observed value. Returns True when the stored value changed."""
    if new is None:
        return False
    now = now or utcnow()
    cur = getattr(ipo, fld)
    latest = _latest_obs(db, ipo.id, fld)
    if cur == new:
        if latest is not None and latest.source_key == source_key and latest.value == _enc(new):
            latest.last_verified_at = now
            latest.data_status = status
        else:
            db.add(FieldObservation(ipo_id=ipo.id, field=fld, value=_enc(new), source_key=source_key, source_url=source_url,
                                    observed_at=now, last_verified_at=now, data_status=status, basis=basis, applied=True))
        return False
    cur_source = latest.source_key if latest else (_implicit_source(ipo) if cur is not None else None)
    # values that predate field tracking (imports, demo) count as sourced, never as estimates
    cur_status = latest.data_status if latest else ("implicit" if cur is not None else None)
    new_rank = authority_of(source_key)
    cur_rank = authority_of(cur_source) if cur_source else 0
    conflict = False
    if cur is None:
        apply = True
    elif status == "estimated" and cur_status not in (None, "estimated"):
        apply = False  # never replace a sourced value with an estimate
    elif cur_status == "estimated" and status != "estimated":
        apply = True  # a sourced value supersedes an estimate
    elif new_rank > cur_rank:
        apply = True
    elif new_rank == cur_rank:
        apply = True
        conflict = cur_source != source_key  # equal authorities disagree: newest wins, flagged
    else:
        apply, conflict = False, True
    db.add(FieldObservation(ipo_id=ipo.id, field=fld, value=_enc(new), source_key=source_key, source_url=source_url, observed_at=now,
                            last_verified_at=now, data_status=status, basis=basis, applied=apply, conflict=conflict))
    if not apply:
        stats.warnings.append(f"{ipo.company.name}: {fld} from {source_key} ({new}) not applied — kept {cur} from {cur_source}")
        return False
    setattr(ipo, fld, new)
    if fld in IMPORTANT_FIELDS and cur is not None:
        db.add(FieldChange(ipo_id=ipo.id, field=fld, old_value=_enc(cur), new_value=_enc(new), source_key=source_key, changed_at=now))
    stats.fields_changed += 1
    stats.changed_ipo_ids.add(ipo.id)
    return True


def _source_record(db: Session, ipo: IPOIssue, rec: IssueRecord, source_key: str, now: datetime) -> SourceRecord:
    src = db.get(SourceRecord, ipo.source_record_id) if ipo.source_record_id else None
    if src is None or src.source_type != "official_url" or not (src.notes or "").startswith(source_key):
        src = SourceRecord(source_type="official_url", title=f"NSE public issue information — {rec.company_name} ({rec.symbol})",
                           source_url=rec.source_url, data_status="verified", currency="INR",
                           notes=f"{source_key}: {rec.api_url}")
        db.add(src)
        db.flush()
        ipo.source_record_id = src.id
    src.retrieved_at = now
    src.source_url = rec.source_url
    return src


def find_ipo(db: Session, rec: IssueRecord) -> IPOIssue | None:
    ipo = db.execute(select(IPOIssue).where(IPOIssue.nse_symbol == rec.symbol).order_by(IPOIssue.id.desc())).scalars().first()
    if ipo is not None:
        return ipo
    target = nz.normalize_company_name(rec.company_name)
    candidates = db.execute(
        select(IPOIssue).join(Company).where(IPOIssue.data_mode != DataMode.demo.value, IPOIssue.nse_symbol.is_(None))
    ).scalars()
    for c in candidates:
        if nz.normalize_company_name(c.company.name) != target:
            continue
        if rec.open_date and c.open_date and abs((rec.open_date - c.open_date).days) > 60:
            continue  # same name, different issue
        return c
    return None


def upsert_issue(db: Session, rec: IssueRecord, *, source_key: str, now: datetime | None = None) -> UpsertStats:
    now = now or utcnow()
    stats = UpsertStats(discovered=1)
    stats.warnings += [f"{rec.symbol}: {w}" for w in rec.warnings]
    ipo = find_ipo(db, rec)
    if ipo is None:
        company = Company(name=rec.company_name, sector=rec.industry or "Unclassified", industry=rec.industry, data_status="verified")
        db.add(company)
        db.flush()
        ipo = IPOIssue(company_id=company.id, exchange="NSE Emerge" if rec.issue_type == "sme" else "NSE", issue_type=rec.issue_type,
                       data_mode=DataMode.source.value, data_status="verified", nse_symbol=rec.symbol, risk_disclosures_reviewed=False)
        db.add(ipo)
        db.flush()
        db.refresh(ipo)
        stats.created = 1
        stats.changed_ipo_ids.add(ipo.id)
    else:
        if ipo.nse_symbol is None:
            ipo.nse_symbol = rec.symbol
        if ipo.data_mode == DataMode.imported.value:
            stats.warnings.append(f"{rec.company_name}: matched an imported record; official NSE values take precedence for issue fields")
    _source_record(db, ipo, rec, source_key, now)
    before = stats.fields_changed
    for src_attr, dst_attr in FIELD_MAP.items():
        set_field(db, ipo, dst_attr, getattr(rec, src_attr), source_key=source_key, source_url=rec.source_url, status="verified", now=now, stats=stats)
    if rec.listing_date is not None:
        ipo.listing_date_status = "actual"
    if rec.industry and ipo.company.sector == "Unclassified":
        ipo.company.sector = rec.industry
        ipo.company.industry = rec.industry
    if ipo.issue_size_text:
        apply_issue_size(db, ipo, source_key=source_key, source_url=rec.source_url, now=now, stats=stats)
    apply_expected_dates(db, ipo, source_key=source_key, now=now, stats=stats)
    ipo.last_verified_at = now
    if stats.fields_changed > before and not stats.created:
        stats.updated = 1
    return stats


def apply_issue_size(db: Session, ipo: IPOIssue, *, source_key: str, source_url: str | None, now: datetime, stats: UpsertStats) -> None:
    """Rupee issue size from the official issue-size sentence.

    Rupee amounts stated in the sentence are used as-is (verified). Share counts are converted
    with the final issue price when known (verified: size = shares x issue price) or with the
    upper end of the price band (estimated) before pricing is final.
    """
    comp = nz.parse_issue_components(ipo.issue_size_text)
    if not comp:
        if ipo.issue_size_cr is None:
            stats.warnings.append(f"{ipo.company.name}: issue size in rupees left unavailable (issue-size text not in a recognised structure)")
        return
    price, price_basis = (ipo.final_issue_price, "final issue price") if ipo.final_issue_price else (ipo.price_band_high, "upper end of the price band")
    if "total_cr" in comp or "total_shares" in comp:
        # the sentence states only the whole issue: its size is known, the fresh/OFS split is not (left unavailable)
        if "total_cr" in comp:
            total, est, basis = comp["total_cr"], False, "rupee total stated in the NSE issue-size sentence"
        elif price:
            total, est = comp["total_shares"] * price / 1e7, price_basis != "final issue price"
            basis = f"from the NSE issue-size sentence; {comp['total_shares']:,.0f} shares x {price_basis}"
        else:
            return
        set_field(db, ipo, "issue_size_cr", round(total, 4), source_key=f"{source_key}:derived" if est else source_key, source_url=source_url,
                  status="estimated" if est else "verified", basis=basis, now=now, stats=stats)
        return
    values: dict[str, float] = {}
    estimated = False
    for part in ("fresh", "ofs"):
        if f"{part}_cr" in comp:
            values[part] = comp[f"{part}_cr"]
        elif f"{part}_shares" in comp:
            if not price:
                return
            values[part] = comp[f"{part}_shares"] * price / 1e7
            estimated = estimated or price_basis != "final issue price"
        else:
            values[part] = 0.0
    status = "estimated" if estimated else "verified"
    basis = (f"from the NSE issue-size sentence; share counts x {price_basis}" if any(k.endswith("_shares") for k in comp)
             else "rupee amounts stated in the NSE issue-size sentence")
    for f, v in (("fresh_issue_cr", values["fresh"]), ("ofs_cr", values["ofs"]), ("issue_size_cr", values["fresh"] + values["ofs"])):
        set_field(db, ipo, f, round(v, 4), source_key=f"{source_key}:derived" if estimated else source_key, source_url=source_url,
                  status=status, basis=basis, now=now, stats=stats)


def apply_expected_dates(db: Session, ipo: IPOIssue, *, source_key: str, now: datetime, stats: UpsertStats) -> None:
    """Expected post-issue dates, stored as estimates and never shown as actual."""
    if ipo.close_date is None or ipo.close_date < T3_START:
        return
    url = None
    set_field(db, ipo, "allotment_date", nz.add_working_days(ipo.close_date, 1), source_key=f"{source_key}:derived", source_url=url,
              status="estimated", basis=ESTIMATE_BASIS, now=now, stats=stats)
    for f in ("refund_date", "demat_credit_date"):
        set_field(db, ipo, f, nz.add_working_days(ipo.close_date, 2), source_key=f"{source_key}:derived", source_url=url,
                  status="estimated", basis=ESTIMATE_BASIS, now=now, stats=stats)
    if ipo.listing_date_status != "actual":
        if set_field(db, ipo, "listing_date", nz.add_working_days(ipo.close_date, 3), source_key=f"{source_key}:derived", source_url=url,
                     status="estimated", basis=ESTIMATE_BASIS, now=now, stats=stats) or ipo.listing_date_status is None:
            ipo.listing_date_status = "expected"


def upsert_subscriptions(db: Session, ipo: IPOIssue, subs: list[SubscriptionRecord], *, now: datetime | None = None) -> int:
    added = 0
    existing = {(s.as_of, s.category, s.basis) for s in db.execute(select(SubscriptionSnapshot).where(SubscriptionSnapshot.ipo_id == ipo.id)).scalars()}
    for s in subs:
        key = (s.as_of, s.category, s.basis)
        if key in existing:
            continue
        db.add(SubscriptionSnapshot(ipo_id=ipo.id, as_of=s.as_of, category=s.category, times_subscribed=s.times_subscribed, basis=s.basis,
                                    shares_offered=s.shares_offered, shares_bid=s.shares_bid, data_status="verified",
                                    source_record_id=ipo.source_record_id))
        existing.add(key)
        added += 1
    if added:
        ipo.updated_at = now or utcnow()
    return added


def apply_listing_price(db: Session, ipo: IPOIssue, lp: ListingPriceRecord, *, now: datetime | None = None) -> UpsertStats:
    now = now or utcnow()
    stats = UpsertStats(discovered=1)
    if ipo.listing_date is None or ipo.listing_date_status != "actual" or lp.trade_date != ipo.listing_date:
        stats.warnings.append(f"{ipo.company.name}: bhavcopy date {lp.trade_date} is not the confirmed listing date; ignored")
        return stats
    issue_price = ipo.final_issue_price or ipo.price_band_high
    if lp.previous_close and issue_price and abs(lp.previous_close - issue_price) / issue_price > 0.005:
        stats.warnings.append(f"{ipo.company.name}: bhavcopy reference price {lp.previous_close} differs from issue price {issue_price}; listing price not applied")
        return stats
    src = SourceRecord(source_type="official_url", title=f"NSE bhavcopy {lp.trade_date:%d-%b-%Y} ({lp.symbol})", source_url=lp.source_url,
                       data_status="verified", currency="INR", reporting_period=lp.trade_date.isoformat(),
                       raw_payload={"symbol": lp.symbol, "open": lp.open_price, "high": lp.high_price, "low": lp.low_price, "close": lp.close_price,
                                    "prev_close": lp.previous_close, "series": lp.series},
                       notes="nse_bhavcopy: listing-day open (OpnPric), high (HghPric), low (LwPric) and close (ClsPric)")
    db.add(src)
    db.flush()
    basis = "listing-day opening price (NSE bhavcopy OpnPric)"
    set_field(db, ipo, "listing_price", lp.open_price, source_key="nse_bhavcopy", source_url=lp.source_url, status="verified", basis=basis, now=now, stats=stats)
    set_field(db, ipo, "listing_close_price", lp.close_price, source_key="nse_bhavcopy", source_url=lp.source_url, status="verified",
              basis="listing-day closing price (NSE bhavcopy ClsPric)", now=now, stats=stats)
    set_field(db, ipo, "listing_high_price", lp.high_price, source_key="nse_bhavcopy", source_url=lp.source_url, status="verified",
              basis="listing-day high (NSE bhavcopy HghPric)", now=now, stats=stats)
    set_field(db, ipo, "listing_low_price", lp.low_price, source_key="nse_bhavcopy", source_url=lp.source_url, status="verified",
              basis="listing-day low (NSE bhavcopy LwPric)", now=now, stats=stats)
    ipo.listing_price_basis = "listing_day_open"
    ipo.listing_data_status = "verified"
    if stats.fields_changed:
        stats.updated = 1
    return stats


PRE_LISTING_PATTERN_DAYS = 15  # the listing-time shareholding pattern is stated as of the day before listing


def apply_shareholding(db: Session, ipo: IPOIssue, records: list[ShareholdingRecord], *, now: datetime | None = None) -> UpsertStats:
    """Promoter holding from the shareholding-pattern filings on NSE (SEBI LODR Regulation 31).

    The pattern stated as of a date in the 15 days before listing is the one filed for listing (Regulation 31(1)(a)):
    it is the post-issue holding and replaces any figure derived from the offer terms. The most recent filing is kept
    separately as the current holding. Nothing is set when no filing falls in that window.
    """
    now = now or utcnow()
    stats = UpsertStats()
    if not records or ipo.listing_date is None:
        return stats
    window = [r for r in records if ipo.listing_date - timedelta(days=PRE_LISTING_PATTERN_DAYS) <= r.as_of <= ipo.listing_date]
    if window:
        r = window[-1]
        set_field(db, ipo, "promoter_holding_post_pct", round(r.promoter_pct, 2), source_key="nse_shareholding", source_url=r.source_url,
                  status="verified", basis=f"shareholding pattern as of {r.as_of:%d %b %Y}, filed with NSE for listing", now=now, stats=stats)
    latest = records[-1]
    facts = dict(ipo.document_facts or {})
    facts["shareholding_latest"] = {"value": latest.promoter_pct, "public_pct": latest.public_pct, "as_of": latest.as_of.isoformat(),
                                    "page": None, "text": "", "basis": "latest shareholding pattern filed with NSE", "document_id": None,
                                    "source_url": latest.source_url, "read_at": now.isoformat()}
    if facts != (ipo.document_facts or {}):
        ipo.document_facts = facts
        stats.changed_ipo_ids.add(ipo.id)
    return stats


def field_provenance(db: Session, ipo_id: int) -> dict[str, dict[str, Any]]:
    """Latest applied observation per field, plus conflict flags."""
    out: dict[str, dict[str, Any]] = {}
    rows = db.execute(select(FieldObservation).where(FieldObservation.ipo_id == ipo_id).order_by(FieldObservation.id)).scalars()
    for o in rows:
        entry = out.setdefault(o.field, {"conflicts": 0})
        if o.conflict:
            entry["conflicts"] += 1
        if o.applied:
            value = json.loads(o.value) if o.value else None
            if entry.get("source_key") and entry.get("value") == value and authority_of(o.source_key) < authority_of(entry["source_key"]):
                continue  # the same value from a lower-authority source (e.g. a derivation) corroborates; it does not replace the citation
            entry.update({
                "value": value,
                "source_key": o.source_key,
                "source_url": o.source_url,
                "first_seen_at": o.observed_at.isoformat(),
                "last_verified_at": o.last_verified_at.isoformat(),
                "data_status": o.data_status,
                "basis": o.basis,
            })
    return out


def recent_changes(db: Session, ipo_id: int | None = None, since: datetime | None = None, limit: int = 50) -> list[dict[str, Any]]:
    q = select(FieldChange).order_by(FieldChange.changed_at.desc()).limit(limit)
    if ipo_id is not None:
        q = q.where(FieldChange.ipo_id == ipo_id)
    if since is not None:
        q = q.where(FieldChange.changed_at >= since)
    return [{"ipo_id": c.ipo_id, "field": c.field, "old_value": json.loads(c.old_value) if c.old_value else None,
             "new_value": json.loads(c.new_value) if c.new_value else None, "source_key": c.source_key, "changed_at": c.changed_at.isoformat()}
            for c in db.execute(q).scalars()]


def observation_count(db: Session) -> int:
    return db.execute(select(func.count(FieldObservation.id))).scalar_one()

