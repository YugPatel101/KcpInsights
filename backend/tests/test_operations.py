"""Unattended operation: database backups, health problems and alerts."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from app.models import IngestionJob, SourceDocument, utcnow
from app.services import operations as ops


@pytest.fixture()
def ops_settings(db, tmp_path, monkeypatch):
    """Point the settings at this test's database and a fresh data directory."""
    from app.config import get_settings

    db_file = db.get_bind().url.database
    monkeypatch.setenv("KCP_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("KCP_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def test_backup_is_consistent_checked_and_rotated(db, ops_settings):
    db.add(IngestionJob(job_type="discover", trigger="test", status="success", finished_at=utcnow()))
    db.commit()
    first = ops.backup_database(keep=2)
    assert first["status"] == "success" and first["kept"] == 1
    with sqlite3.connect(ops.backup_dir() / first["file"]) as copy:  # a usable database with the data in it
        assert copy.execute("select count(*) from ingestion_jobs").fetchone()[0] == 1
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    names = {first["file"]}
    for i in range(2):  # distinct names (the timestamp has one-second resolution)
        (ops.backup_dir() / f"{ops.BACKUP_PREFIX}2000010{i}-000000.db").write_bytes(b"")
    third = ops.backup_database(keep=2)
    kept = [p.name for p in ops.list_backups()]
    assert third["kept"] == 2 and kept == sorted([first["file"], third["file"]])  # the two oldest (fake) copies were removed
    assert sorted(third["removed"]) == [f"{ops.BACKUP_PREFIX}20000100-000000.db", f"{ops.BACKUP_PREFIX}20000101-000000.db"] and names <= set(kept)


def test_health_problems_are_derived_from_stored_state(db, ops_settings):
    assert ops.health_problems(db) == [{"level": "warning", "code": "backup_missing", "message": ops.health_problems(db)[0]["message"]}]
    old = utcnow() - timedelta(days=5)
    db.add(IngestionJob(job_type="discover", trigger="test", status="success", started_at=old, finished_at=old))
    db.add(SourceDocument(title="RHP", doc_type="rhp", sha256="x", mime_type="application/pdf", data_status="verified",
                          extraction_status="failed", attempts=ops_settings.document_max_attempts))
    db.commit()
    ops.backup_database()
    codes = {p["code"] for p in ops.health_problems(db)}
    assert "job_overdue:discover" in codes and "dead_letters" in codes and "backup_missing" not in codes
    db.add(IngestionJob(job_type="discover", trigger="test", status="skipped", finished_at=utcnow()))  # nothing to do still counts as on time
    db.commit()
    assert "job_overdue:discover" not in {p["code"] for p in ops.health_problems(db)}


def test_alerts_only_when_the_problems_change(ops_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(ops.subprocess, "run", lambda *a, **k: calls.append(a))
    p = [{"level": "warning", "code": "dead_letters", "message": "1 offer document failed"}]
    assert ops.notify(p, p) is False and not calls  # unchanged: nothing
    assert ops.notify(p, []) is False and not calls  # changed, but desktop alerts are off by default
    monkeypatch.setattr(ops_settings, "desktop_alerts", True)
    monkeypatch.setattr(ops.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ops.shutil, "which", lambda _n: "/usr/bin/osascript")
    assert ops.notify(p, []) is True and calls and calls[0][0][0] == "osascript"


def test_health_command_exit_codes(db, ops_settings, capsys, monkeypatch):
    from app import cli
    from app.cli import main

    monkeypatch.setattr(cli, "_db", lambda: db)

    assert main(["health"]) == 1  # no backup yet: a warning
    assert "backup" in capsys.readouterr().out
    assert main(["backup"]) == 0
    assert main(["health"]) == 0
