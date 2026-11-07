"""Unattended operation: database backups, health problems and local alerts.

* Backups use SQLite's online-backup API, which copies a consistent snapshot while the API keeps writing (copying the
  live file is unsafe in WAL mode). Each copy is integrity-checked; the oldest beyond the retention count are removed.
* Health problems are derived from stored state only (job runs, documents, backups, free disk), so the CLI, the API and
  the scheduler all report the same thing. Each problem has a level (warning | error), a stable code and a message.
* Alerts are local and opt-in: when ``KCP_DESKTOP_ALERTS=true`` on macOS, a change in the set of problems shows a
  notification. Nothing is sent over the network.
"""
from __future__ import annotations

import logging
import platform
import shutil
import sqlite3
import subprocess  # noqa: S404 - fixed argv (osascript), no shell
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IngestionJob, SourceDocument, utcnow

log = logging.getLogger("kcp.operations")
BACKUP_PREFIX = "kcpinsights-"


def database_file() -> Path | None:
    url = get_settings().database_url
    return Path(url.removeprefix("sqlite:///")) if url.startswith("sqlite:///") else None


def backup_dir() -> Path:
    return get_settings().data_dir / "backups"


def list_backups() -> list[Path]:
    d = backup_dir()
    return sorted(d.glob(f"{BACKUP_PREFIX}*.db")) if d.exists() else []


def backup_database(keep: int | None = None) -> dict[str, Any]:
    """Consistent copy of the SQLite database into data/backups, integrity-checked, keeping the newest ``keep`` copies."""
    src = database_file()
    if src is None:
        return {"status": "skipped", "reason": "not a SQLite database; use the database's own backup tooling"}
    keep = keep if keep is not None else get_settings().backup_keep
    d = backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = f"{BACKUP_PREFIX}{datetime.now():%Y%m%d-%H%M%S}"
    dest, n = d / f"{stamp}.db", 1
    while dest.exists():  # two backups within one second keep both
        n += 1
        dest = d / f"{stamp}-{n}.db"
    tmp = dest.with_suffix(".partial")
    source, target = sqlite3.connect(f"file:{src}?mode=ro", uri=True), sqlite3.connect(tmp)
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")  # a single self-contained file (the copy inherits WAL mode otherwise)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        source.close()
        target.close()
    if result != "ok":
        tmp.unlink(missing_ok=True)
        return {"status": "failed", "reason": f"integrity check of the copy failed: {result}"}
    tmp.rename(dest)
    removed = [p.name for p in list_backups()[:-keep]] if keep > 0 else []
    for name in removed:
        (d / name).unlink(missing_ok=True)
    return {"status": "success", "file": dest.name, "size_mb": round(dest.stat().st_size / 1024 / 1024, 1), "kept": len(list_backups()),
            "removed": removed}


def last_backup_at() -> datetime | None:
    """When the newest backup was written, as naive UTC like every other timestamp the API returns."""
    b = list_backups()
    return datetime.fromtimestamp(b[-1].stat().st_mtime, tz=UTC).replace(tzinfo=None) if b else None


def job_intervals() -> dict[str, int]:
    s = get_settings()
    return {"discover": s.ingest_discovery_minutes, "details": s.ingest_details_minutes, "listings": s.ingest_listing_minutes,
            "documents": s.ingest_documents_minutes, "filings": s.ingest_filings_minutes, "peers": s.ingest_peer_prices_minutes,
            "enrichment": s.ingest_enrichment_minutes, "health": s.ingest_health_minutes, "backup": s.backup_hours * 60}


def health_problems(db: Session) -> list[dict[str, str]]:
    """What needs attention, from stored state. Empty when everything is running as scheduled."""
    s = get_settings()
    now = utcnow()
    problems: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        problems.append({"level": level, "code": code, "message": message})

    # each scheduled job should have succeeded (or been skipped for having nothing to do) within three of its intervals
    last_ok: dict[str, datetime | None] = {jt: done for jt, done in db.execute(
        select(IngestionJob.job_type, func.max(IngestionJob.finished_at))
        .where(IngestionJob.status.in_(("success", "partial", "skipped"))).group_by(IngestionJob.job_type)).tuples()}
    ever = {r[0] for r in db.execute(select(IngestionJob.job_type).distinct())}
    for job, minutes in job_intervals().items():
        if job == "backup" or not ever:
            continue
        done = last_ok.get(job)
        if done is None or now - done > timedelta(minutes=3 * minutes):
            when = "has never completed" if done is None else f"last completed {(now - done).total_seconds() / 3600:.0f} h ago"
            add("warning", f"job_overdue:{job}", f"The {job} job {when} (runs every {minutes} min); "
                "data stays current only while the API or `python -m app.cli worker` runs.")
    dead = db.execute(select(func.count()).select_from(SourceDocument).where(
        SourceDocument.extraction_status == "failed", SourceDocument.attempts >= s.document_max_attempts)).scalar_one()
    if dead:
        add("warning", "dead_letters", f"{dead} offer document(s) failed {s.document_max_attempts} times and are no longer retried (System health → Documents).")
    if s.backup_enabled and database_file() is not None:
        last = last_backup_at()
        if last is None:
            add("warning", "backup_missing", "No database backup yet: run `python -m app.cli backup` (the scheduler makes one every "
                f"{s.backup_hours} h while it runs).")
        elif now - last > timedelta(hours=2 * s.backup_hours):
            add("warning", "backup_stale", f"The newest database backup is {(now - last).total_seconds() / 3600:.0f} h old.")
    try:
        free_gb = shutil.disk_usage(s.data_dir).free / 1024 ** 3
        if free_gb < s.min_free_disk_gb:
            add("error", "disk_low", f"Only {free_gb:.1f} GB free where the data directory lives (minimum {s.min_free_disk_gb} GB).")
    except OSError:
        pass
    return problems


def notify(problems: list[dict[str, str]], previous: list[dict[str, str]] | None) -> bool:
    """A local notification when the set of problems changed (macOS, opt-in). Returns True when one was shown."""
    s = get_settings()
    codes, before = {p["code"] for p in problems}, {p["code"] for p in previous or []}
    if codes == before:
        return False
    new = [p for p in problems if p["code"] not in before]
    message = (f"{len(problems)} issue(s): " + "; ".join(p["message"] for p in new)[:180]) if problems else "All checks passing again."
    log.warning("health changed: %s", message)
    if not s.desktop_alerts or platform.system() != "Darwin" or shutil.which("osascript") is None:
        return False
    text = message.replace("\\", " ").replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "KcpInsights"'],  # noqa: S603,S607 - fixed program
                   check=False, timeout=10, capture_output=True)
    return True
