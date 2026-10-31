"""Ingestion jobs, cross-process locks and the background scheduler.

Jobs fetch each upstream source once per run and store normalised data; the API and
every browser read only from the database. Jobs that touch the same source share one
lock, so they never overlap — even across several API workers or a separate
``python -m app.cli worker`` process. Each run is recorded in ``ingestion_jobs``.

The in-process scheduler only runs while the API (or worker) process is running. A
sleeping free-tier host does not run it; see README → "Live data".
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.ingestion import ipo_data_service as svc
from app.ingestion.data_quality_service import is_open_today
from app.ingestion.http import PoliteClient
from app.ingestion.source_registry import ensure_sources, record_source_result
from app.ingestion.sources.base import IssueRecord
from app.ingestion.sources.bse import BSEPublicIssuesSource
from app.ingestion.sources.nse import NSEBhavcopySource, NSEEquityList, NSEOfficialSource
from app.ingestion.sources.sebi import SEBIFilingsSource
from app.models import DataSource, FieldObservation, IngestionJob, IPOIssue, JobLock, PeerSnapshot, utcnow

log = logging.getLogger("kcp.ingestion")

JOB_TYPES = ("discover", "details", "subscriptions", "listings", "filings", "documents", "peers", "health")
JOB_LOCK = {"discover": "source:nse", "details": "source:nse", "subscriptions": "source:nse", "listings": "source:nse",
            "filings": "source:sebi", "documents": "source:documents", "peers": "source:nse_archives", "health": "source:health"}
# DataSource row that a job's requests and health are attributed to
JOB_SOURCE = {"listings": "nse_bhavcopy", "health": "bse_ipo", "documents": "nse_rhp", "filings": "sebi_offer_documents", "peers": "nse_equity_list"}
OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------- locks
def owner_is_dead(owner: str) -> bool:
    """True when the owner ran on this host and its process no longer exists (crash, reload, kill)."""
    try:
        host, pid, _ = owner.split(":")
        if host != socket.gethostname():
            return False  # cannot check another machine; rely on expiry
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return True
    except (ValueError, PermissionError, OSError):
        return False
    return False


def acquire_lock(db: Session, key: str, minutes: int = 30) -> bool:
    now = utcnow()
    row = db.get(JobLock, key)
    if row is not None:
        if row.expires_at > now and row.owner != OWNER and not owner_is_dead(row.owner):
            return False
        row.owner, row.acquired_at, row.expires_at = OWNER, now, now + timedelta(minutes=minutes)
        db.commit()
        return True
    db.add(JobLock(key=key, owner=OWNER, acquired_at=now, expires_at=now + timedelta(minutes=minutes)))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def release_lock(db: Session, key: str) -> None:
    db.execute(delete(JobLock).where(JobLock.key == key, JobLock.owner == OWNER))
    db.commit()


# ---------------------------------------------------------------------------- runner
class IngestionRunner:
    def __init__(self, session_factory: sessionmaker, client: PoliteClient | None = None, today: Callable[[], date] = date.today) -> None:
        self.session_factory = session_factory
        self.client = client or PoliteClient()
        self.nse = NSEOfficialSource(self.client)
        self.bhav = NSEBhavcopySource(self.client)
        self.bse = BSEPublicIssuesSource(self.client)
        self.sebi = SEBIFilingsSource(self.client)
        self.equity_list = NSEEquityList(self.client)
        self.today = today
        self._mutex = threading.Lock()

    # ---------------------------------------------------------------- orchestration
    def run(self, job_type: str, trigger: str = "schedule") -> dict[str, Any]:
        if job_type == "all":
            results = [self.run(j, trigger) for j in ("discover", "details", "subscriptions", "listings", "filings", "documents", "peers")]
            return {"job_type": "all", "runs": results}
        if job_type not in JOB_TYPES:
            raise ValueError(f"unknown job {job_type!r}")
        s = get_settings()
        db = self.session_factory()
        try:
            ensure_sources(db)
            job = IngestionJob(job_type=job_type, trigger=trigger, status="running", detail={"owner": OWNER})
            db.add(job)
            db.commit()
            if not s.ingest_enabled:
                return self._finish(db, job, "skipped", detail={"reason": "ingestion disabled (KCP_INGEST_ENABLED=false)"})
            lock = JOB_LOCK[job_type]
            if not acquire_lock(db, lock):
                return self._finish(db, job, "skipped", detail={"reason": f"another job holds {lock}"})
            before = self.client.requests_made
            try:
                with self._mutex:
                    status, detail = getattr(self, f"job_{job_type}")(db, job)
            except Exception as exc:  # noqa: BLE001 - a job failure must never crash the scheduler
                db.rollback()
                log.exception("ingestion job %s failed", job_type)
                job = db.get(IngestionJob, job.id) or job
                job.errors = [*job.errors, {"error": f"{type(exc).__name__}: {exc}"[:500]}]
                status, detail = "failed", {}
            finally:
                job.requests_made = self.client.requests_made - before
                release_lock(db, lock)
                src_key = JOB_SOURCE.get(job_type, "nse_ipo")
                src_row = ensure_sources(db).get(src_key)
                if src_row is not None and job_type != "health":
                    src_row.requests_made += job.requests_made
            return self._finish(db, job, status, detail=detail)
        finally:
            db.close()

    @staticmethod
    def _finish(db: Session, job: IngestionJob, status: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        job.status = status
        job.finished_at = utcnow()
        job.detail = {**(job.detail or {}), **(detail or {})}
        db.commit()
        return {"id": job.id, "job_type": job.job_type, "status": job.status, "records_discovered": job.records_discovered,
                "records_created": job.records_created, "records_updated": job.records_updated, "fields_changed": job.fields_changed,
                "requests_made": job.requests_made, "errors": job.errors, "detail": job.detail}

    @staticmethod
    def _apply_stats(job: IngestionJob, st: svc.UpsertStats) -> None:
        job.records_discovered += st.discovered
        job.records_created += st.created
        job.records_updated += st.updated
        job.fields_changed += st.fields_changed
        if st.warnings:
            job.detail = {**(job.detail or {}), "warnings": [*(job.detail or {}).get("warnings", []), *st.warnings][-100:]}

    def _upsert_records(self, db: Session, job: IngestionJob, records: list[IssueRecord], source_key: str) -> None:
        changed: set[int] = set()
        for rec in records:
            try:
                with db.begin_nested():
                    st = svc.upsert_issue(db, rec, source_key=source_key)
                self._apply_stats(job, st)
                changed |= st.changed_ipo_ids
            except Exception as exc:  # noqa: BLE001 - one bad record must not abort the run
                job.errors = [*job.errors, {"symbol": rec.symbol, "error": f"{type(exc).__name__}: {exc}"[:300]}]
        db.commit()
        self._rescore(db, job, changed)

    @staticmethod
    def _rescore(db: Session, job: IngestionJob, ipo_ids: set[int] | None) -> None:
        """Scores and completeness are stored, not computed per request: refresh them for IPOs whose inputs changed."""
        from app.services.ipo_service import refresh_scores

        try:
            res = refresh_scores(db, ipo_ids)
            job.detail = {**(job.detail or {}), "rescored": res}
        except Exception as exc:  # noqa: BLE001 - scoring problems must not fail ingestion
            db.rollback()
            log.exception("rescoring failed")
            job.errors = [*job.errors, {"stage": "scoring", "error": f"{type(exc).__name__}: {exc}"[:300]}]

    # ---------------------------------------------------------------- jobs
    def job_discover(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        s = get_settings()
        since = self.today() - timedelta(days=s.ingest_listing_window_days)
        results = {"upcoming": self.nse.fetch_upcoming_ipos(), "open": self.nse.fetch_open_ipos(), "recently_listed": self.nse.fetch_recently_listed_ipos(since)}
        merged: dict[str, IssueRecord] = {}
        for res in results.values():
            for rec in res.data or []:
                cur = merged.get(rec.symbol)
                if cur is None:
                    merged[rec.symbol] = rec
                else:  # keep every field any list reported
                    for k, v in vars(rec).items():
                        if v not in (None, [], "") and getattr(cur, k) in (None, [], ""):
                            setattr(cur, k, v)
        self._upsert_records(db, job, list(merged.values()), "nse_ipo")
        failed = [k for k, r in results.items() if r.status != "ok"]
        errs = "; ".join(f"{k}: {results[k].error}" for k in failed)
        record_source_result(db, "nse_ipo", ok=len(failed) < len(results), error=errs or None, requests=0)
        if failed:
            job.errors = [*job.errors, *({"endpoint": k, "error": results[k].error} for k in failed)]
        status = "failed" if len(failed) == len(results) else ("partial" if failed or job.errors else "success")
        return status, {"lists": {k: (len(r.data or []) if r.status == "ok" else r.status) for k, r in results.items()}}

    def _live_ipos(self, db: Session) -> list[IPOIssue]:
        return list(db.execute(select(IPOIssue).where(IPOIssue.nse_symbol.is_not(None))).scalars())

    def job_details(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        s = get_settings()
        today = self.today()
        cutoff = utcnow() - timedelta(minutes=s.ingest_details_minutes)
        todo = []
        for ipo in self._live_ipos(db):
            relevant = (ipo.close_date is None or ipo.close_date >= today - timedelta(days=3)) or (
                ipo.listing_date is not None and ipo.listing_date >= today - timedelta(days=10) and ipo.company.sector == "Unclassified") or (
                # listed issues: one details fetch to find the offer-document link for financial statements
                ipo.offer_document_url is None and ipo.listing_date is not None
                and ipo.listing_date >= today - timedelta(days=s.document_window_days))
            if not relevant:
                continue
            obs = svc._latest_obs(db, ipo.id, "face_value")
            if obs is None or obs.last_verified_at < cutoff:
                todo.append(ipo)
        todo = todo[: s.ingest_max_detail_fetches_per_run]
        failures = 0
        changed: set[int] = set()
        for ipo in todo:
            series = "SME" if ipo.issue_type == "sme" else "EQ"
            res = self.nse.fetch_ipo_details(ipo.nse_symbol or "", series)
            if res.status != "ok" or res.data is None:
                failures += 1
                job.errors = [*job.errors, {"symbol": ipo.nse_symbol, "error": res.error}]
                continue
            rec, subs = res.data
            rec.company_name = ipo.company.name  # the detail payload may carry only the symbol
            try:
                with db.begin_nested():
                    st = svc.upsert_issue(db, rec, source_key="nse_ipo")
                    self._apply_stats(job, st)
                    svc.upsert_subscriptions(db, ipo, subs)
                    changed |= st.changed_ipo_ids
            except Exception as exc:  # noqa: BLE001
                job.errors = [*job.errors, {"symbol": ipo.nse_symbol, "error": f"{type(exc).__name__}: {exc}"[:300]}]
        db.commit()
        self._rescore(db, job, changed)
        if todo:
            record_source_result(db, "nse_ipo", ok=failures < len(todo), error=job.errors[-1]["error"] if failures else None)
        status = "success" if not job.errors else ("failed" if failures == len(todo) and todo else "partial")
        return status, {"fetched": len(todo), "failures": failures}

    def job_subscriptions(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        today = self.today()
        targets = [i for i in self._live_ipos(db) if is_open_today(i, today) or (i.close_date and 0 < (today - i.close_date).days <= 1)]
        if not targets:
            return "skipped", {"reason": "no issue is open for bidding; no requests made"}
        added = 0
        for ipo in targets:
            res = self.nse.fetch_subscription_data(ipo.nse_symbol or "")
            if res.status != "ok" or not res.data:
                job.errors = [*job.errors, {"symbol": ipo.nse_symbol, "error": res.error}]
                continue
            added += svc.upsert_subscriptions(db, ipo, res.data)
            job.records_discovered += 1
        if added:
            job.records_updated += added
        db.commit()
        record_source_result(db, "nse_ipo", ok=len(job.errors) < len(targets), error=job.errors[-1]["error"] if job.errors else None)
        return ("success" if not job.errors else "partial"), {"open_issues": len(targets), "snapshots_added": added}

    def job_listings(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        s = get_settings()
        today = self.today()
        live = self._live_ipos(db)
        # 1) confirm listing dates for issues whose expected listing date has arrived
        pending = [i for i in live if i.listing_date_status == "expected" and i.listing_date and i.listing_date <= today + timedelta(days=1)]
        if pending:
            res = self.nse.fetch_recently_listed_ipos(today - timedelta(days=30))
            if res.status == "ok" and res.data:
                wanted = {i.nse_symbol for i in pending}
                self._upsert_records(db, job, [r for r in res.data if r.symbol in wanted], "nse_ipo")
            elif res.status != "ok":
                job.errors = [*job.errors, {"endpoint": "public-past-issues", "error": res.error}]
        # 2) listing-day prices from the official bhavcopy (one file per listing date)
        window = today - timedelta(days=s.ingest_listing_window_days)
        # missing listing prices, or a listing-day range not yet stored (cached bhavcopies make that backfill request-free)
        need = [i for i in self._live_ipos(db) if i.listing_date_status == "actual" and i.listing_date and window <= i.listing_date <= today
                and (i.listing_price is None or i.listing_high_price is None)]
        by_date: dict[date, list[IPOIssue]] = defaultdict(list)
        for i in need:
            by_date[i.listing_date].append(i)  # type: ignore[index]
        bhav_ok = bhav_fail = 0
        listed_changed: set[int] = set()
        for d, ipos in sorted(by_date.items()):
            day = self.bhav.fetch_day(d)
            if day.status != "ok" or day.data is None:
                bhav_fail += 1
                if "not published" not in (day.error or ""):
                    job.errors = [*job.errors, {"date": d.isoformat(), "error": day.error}]
                continue
            bhav_ok += 1
            for ipo in ipos:
                lp = day.data.get(ipo.nse_symbol or "")
                if lp is None:
                    job.detail = {**job.detail, "missing_in_bhavcopy": [*(job.detail or {}).get("missing_in_bhavcopy", []), ipo.nse_symbol]}
                    continue
                st = svc.apply_listing_price(db, ipo, lp)
                self._apply_stats(job, st)
                listed_changed |= st.changed_ipo_ids
        db.commit()
        self._rescore(db, job, listed_changed)
        if by_date:
            record_source_result(db, "nse_bhavcopy", ok=bhav_ok > 0 or bhav_fail == 0, error=None if bhav_ok else (job.errors[-1]["error"] if job.errors else "not published"))
        if not pending and not by_date:
            return "skipped", {"reason": "no listing confirmations or listing prices pending; no requests made"}
        return ("success" if not job.errors else "partial"), {"confirmations_checked": len(pending), "listing_days": len(by_date)}

    def job_documents(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        """Discover, download (only when new/changed), extract and score offer documents."""
        s = get_settings()
        if not s.ingest_download_offer_documents:
            return "skipped", {"reason": "offer-document processing disabled (KCP_INGEST_DOWNLOAD_OFFER_DOCUMENTS=false)"}
        from app.ingestion.document_service import run_documents

        st = run_documents(db, self.client, self._live_ipos(db), self.today())
        job.records_discovered = st.discovered
        job.records_created = st.extracted
        job.errors = [*job.errors, *st.errors]
        detail = {"discovered": st.discovered, "downloaded": st.downloaded, "unchanged": st.checked_unchanged, "extracted": st.extracted,
                  "failed": st.failed, "duplicates": st.duplicates, "dead_letters": st.dead_letters, "pruned_originals": st.pruned,
                  "processed": st.processed[:10]}
        return ("success" if not st.errors and not st.failed else "partial"), detail

    def job_filings(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        """New SEBI offer-document filings (two listing pages); documents are downloaded later by the documents job."""
        s = get_settings()
        if not s.ingest_sebi_filings:
            return "skipped", {"reason": "SEBI filings discovery disabled (KCP_INGEST_SEBI_FILINGS=false)"}
        from app.ingestion.document_service import DocRunStats, discover_sebi

        st = DocRunStats()
        discover_sebi(db, self.sebi, st)
        job.records_discovered = st.filings_seen
        job.records_created = st.discovered
        job.errors = [*job.errors, *st.errors]
        record_source_result(db, "sebi_offer_documents", ok=len(st.errors) < 2, error=st.errors[-1]["error"] if st.errors else None)
        self._rescore(db, job, None if st.pipeline_ipos_created else set())
        return ("success" if not st.errors else ("failed" if len(st.errors) == 2 else "partial")), {
            "filings_seen": st.filings_seen, "new_documents": st.discovered, "pipeline_ipos_created": st.pipeline_ipos_created}

    def job_peers(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        """Latest official close for each listed peer: name → NSE symbol (equity list), price from the latest bhavcopy."""
        from app.ingestion import normalizer as nz

        peers = list(db.execute(select(PeerSnapshot).where(PeerSnapshot.document_id.is_not(None))).scalars())
        if not peers:
            return "skipped", {"reason": "no listed peers on record"}
        names = self.equity_list.fetch(self.today())
        if names.status != "ok" or names.data is None:
            record_source_result(db, "nse_equity_list", ok=False, error=names.error)
            job.errors = [*job.errors, {"endpoint": "equity list", "error": names.error}]
            return "failed", {}
        record_source_result(db, "nse_equity_list", ok=True)
        day = None
        for back in range(1, 8):  # the latest published trading day
            d = self.today() - timedelta(days=back)
            if d.weekday() >= 5:
                continue
            res = self.bhav.fetch_day(d)
            if res.status == "ok" and res.data:
                day = (d, res.data)
                break
        if day is None:
            return "partial", {"reason": "no bhavcopy published in the last week"}
        matched = 0
        for p in peers:
            sym = p.nse_symbol or names.data.get(nz.normalize_company_name(p.name))
            lp = day[1].get(sym or "")
            if sym and lp is not None:
                p.nse_symbol, p.latest_price, p.latest_price_date = sym, lp.close_price, day[0]
                matched += 1
        db.commit()
        return "success", {"peers": len(peers), "matched": matched, "price_date": day[0].isoformat()}

    def job_health(self, db: Session, job: IngestionJob) -> tuple[str, dict[str, Any]]:
        src = ensure_sources(db)
        bse: DataSource = src["bse_ipo"]
        checked = False
        if bse.last_attempt_at is None or utcnow() - bse.last_attempt_at > timedelta(hours=24):
            res = self.bse.health_check()
            bse.last_attempt_at = utcnow()
            bse.requests_made += 1
            err = res.error or ""
            bse.health_status = "reachable" if res.status == "ok" else ("blocked" if err.startswith("blocked") else "unavailable")
            bse.last_error = res.error
            db.commit()
            checked = True
        stale_obs = db.execute(select(FieldObservation.id).limit(1)).first() is not None
        self._rescore(db, job, None)  # picks up configuration changes and time-dependent stages; rows are added only on change
        return "success", {"bse_checked": checked, "has_observations": stale_obs}


# ---------------------------------------------------------------------------- scheduler
_runner: IngestionRunner | None = None
_scheduler: Any = None


def get_runner() -> IngestionRunner:
    global _runner
    if _runner is None:
        from app.db import SessionLocal

        _runner = IngestionRunner(SessionLocal)
    return _runner


def run_in_background(job_type: str, trigger: str) -> None:
    threading.Thread(target=lambda: get_runner().run(job_type, trigger), name=f"ingest-{job_type}", daemon=True).start()


def recover_interrupted_jobs(db: Session) -> int:
    """Mark jobs left 'running' by a process that no longer exists as failed, and free their locks."""
    n = 0
    for job in db.execute(select(IngestionJob).where(IngestionJob.status == "running")).scalars():
        owner = str((job.detail or {}).get("owner", ""))
        if owner and owner_is_dead(owner):
            job.status, job.finished_at = "failed", utcnow()
            job.errors = [*job.errors, {"error": "interrupted: the process running this job exited"}]
            n += 1
    for lock in db.execute(select(JobLock)).scalars():
        if owner_is_dead(lock.owner):
            db.delete(lock)
    db.commit()
    return n


def start_scheduler() -> Any:
    """Start interval jobs in this process. Safe to call once per process."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    from app.db import SessionLocal

    with SessionLocal() as db:
        recovered = recover_interrupted_jobs(db)
        if recovered:
            log.warning("marked %d interrupted ingestion job(s) as failed", recovered)
    from apscheduler.schedulers.background import BackgroundScheduler

    s = get_settings()
    sched = BackgroundScheduler(timezone="Asia/Kolkata", job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 600})
    now = utcnow()
    plan = [("discover", s.ingest_discovery_minutes, 15), ("details", s.ingest_details_minutes, 90), ("subscriptions", s.ingest_subscription_minutes, 150),
            ("listings", s.ingest_listing_minutes, 200), ("health", s.ingest_health_minutes, 60), ("filings", s.ingest_filings_minutes, 240),
            ("documents", s.ingest_documents_minutes, 300), ("peers", s.ingest_peer_prices_minutes, 420)]
    import datetime as _dt

    for name, minutes, delay in plan:
        first = _dt.datetime.now(_dt.UTC) + timedelta(seconds=delay)
        sched.add_job(get_runner().run, "interval", minutes=minutes, args=[name, "schedule"], id=name, next_run_time=first, jitter=30)
    sched.start()
    _scheduler = sched
    log.info("ingestion scheduler started at %s", now.isoformat())
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> dict[str, Any]:
    s = get_settings()
    if _scheduler is None:
        return {"running": False, "enabled": s.scheduler_enabled,
                "note": "The in-process scheduler is not running in this API process. Run `python -m app.cli worker` or enable KCP_SCHEDULER_ENABLED."}
    return {"running": True, "enabled": True, "jobs": [{"id": j.id, "next_run_at": j.next_run_time.isoformat() if j.next_run_time else None,
                                                        "interval_minutes": int(j.trigger.interval.total_seconds() // 60)} for j in _scheduler.get_jobs()]}
