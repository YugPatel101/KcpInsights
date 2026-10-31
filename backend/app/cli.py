"""Command-line administration: migrations, demo seed, first admin, data sync, documents.

Usage (from backend/):  python -m app.cli <command> [options]
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.config import BACKEND_DIR


def _db():
    from app.db import SessionLocal

    return SessionLocal()


def cmd_migrate(_: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    print("database migrated to head")
    return 0


def cmd_seed_demo(a: argparse.Namespace) -> int:
    from app.services.demo_seed import seed_demo
    from app.services.ipo_service import get_active_config_row

    db = _db()
    get_active_config_row(db)
    res = seed_demo(db, reset=a.reset)
    print(json.dumps({k: v for k, v in res.items() if k != "report"}, indent=2, default=str))
    return 0


def cmd_create_admin(a: argparse.Namespace) -> int:
    from app.core.security import hash_password, password_problems
    from app.models import User

    db = _db()
    email = (a.email or input("Admin e-mail: ")).strip().lower()
    if db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none():
        print("a user with that e-mail already exists", file=sys.stderr)
        return 1
    pw = getpass.getpass("Password (min 10 chars, letters and digits): ")
    if pw != getpass.getpass("Repeat password: "):
        print("passwords do not match", file=sys.stderr)
        return 1
    problems = password_problems(pw, email)
    if problems:
        print("weak password: " + "; ".join(problems), file=sys.stderr)
        return 1
    db.add(User(email=email, display_name=a.name or "Administrator", password_hash=hash_password(pw), is_admin=True))
    db.commit()
    print(f"administrator {email} created")
    return 0


def cmd_reset_password(a: argparse.Namespace) -> int:
    """Set a new password for an account and revoke its sessions (no e-mail service is needed)."""
    from app.core.security import hash_password, password_problems
    from app.models import User, UserSession

    db = _db()
    email = a.email.strip().lower()
    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if user is None:
        print("no user with that e-mail", file=sys.stderr)
        return 1
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Repeat password: "):
        print("passwords do not match", file=sys.stderr)
        return 1
    problems = password_problems(pw, email)
    if problems:
        print("weak password: " + "; ".join(problems), file=sys.stderr)
        return 1
    user.password_hash = hash_password(pw)
    for s in db.execute(select(UserSession).where(UserSession.user_id == user.id)).scalars():
        s.revoked = True
    db.commit()
    print(f"password reset for {email}; existing sessions revoked")
    return 0


def cmd_ingest(a: argparse.Namespace) -> int:
    from app.services import rag

    p = Path(a.path)
    data = p.read_bytes()
    db = _db()
    if p.suffix.lower() == ".pdf":
        doc = rag.ingest_pdf_document(db, ipo_id=a.ipo_id, title=a.title or p.stem, doc_type=a.doc_type, data=data, source_url=a.url, user_id=None)
    else:
        doc = rag.ingest_text_document(db, ipo_id=a.ipo_id, title=a.title or p.stem, doc_type=a.doc_type, text=data.decode("utf-8", "replace"),
                                       source_url=a.url, user_id=None)
    print(f"document {doc.id}: {doc.page_count} pages, {len(doc.chunks)} chunks")
    return 0


def cmd_sync(a: argparse.Namespace) -> int:
    """Run ingestion jobs now (fetches public NSE data; respects rate limits)."""
    from app.ingestion.ingestion_scheduler import get_runner

    out = get_runner().run(a.job, "cli")
    runs = out["runs"] if a.job == "all" else [out]
    for r in runs:
        warnings = r["detail"].pop("warnings", [])
        print(f"{r['job_type']:<14} {r['status']:<8} discovered={r['records_discovered']} created={r['records_created']} "
              f"updated={r['records_updated']} fields_changed={r['fields_changed']} requests={r['requests_made']} "
              f"errors={len(r['errors'])} warnings={len(warnings)} {json.dumps(r['detail'], default=str)[:200]}")
    return 0 if all(r["status"] in ("success", "partial", "skipped") for r in runs) else 1


def cmd_refresh_scores(_: argparse.Namespace) -> int:
    from app.services.ipo_service import refresh_scores

    print(json.dumps(refresh_scores(_db())))
    return 0


def cmd_process_documents(a: argparse.Namespace) -> int:
    """The documents job with a larger per-run budget, for catching up after a parser upgrade or a first install."""
    from app.config import get_settings
    from app.ingestion.ingestion_scheduler import get_runner

    get_settings().ingest_max_documents_per_run = a.limit
    r = get_runner().run("documents", "cli")
    print(json.dumps({k: r[k] for k in ("status", "records_discovered", "records_created", "requests_made", "errors")}, default=str))
    print(json.dumps(r["detail"].get("processed", []), default=str, indent=1)[:4000])
    return 0 if r["status"] in ("success", "partial", "skipped") else 1


def cmd_backfill_history(a: argparse.Namespace) -> int:
    """Listed issues from the last ``--days`` days (NSE past issues), then listing-day prices from the cached/official bhavcopies."""
    from app.config import get_settings
    from app.ingestion.ingestion_scheduler import get_runner

    get_settings().ingest_listing_window_days = a.days
    for job in ("discover", "listings"):
        r = get_runner().run(job, "cli")
        print(f"{job:<10} {r['status']:<8} discovered={r['records_discovered']} created={r['records_created']} "
              f"updated={r['records_updated']} requests={r['requests_made']} errors={len(r['errors'])}")
    return 0


def cmd_e2e_demo(a: argparse.Namespace) -> int:
    from app.cli_e2e import run_e2e

    report = run_e2e(_db(), a.symbol.upper())
    print(report)
    if a.report:
        Path(a.report).write_text(report)
        print(f"report written to {a.report}")
    return 0


def cmd_reclassify(_: argparse.Namespace) -> int:
    """Re-run the industry classifier over every stored offer document (after a classifier change), then rescore."""
    import pymupdf

    from app.financials.disclosures import business_overview
    from app.financials.industry import classify_industry, lender_kpis
    from app.ingestion.document_service import document_path
    from app.ingestion.financial_store import StoreStats, store_classification
    from app.models import IPOIssue, SourceDocument, utcnow
    from app.services.ipo_service import refresh_scores

    db = _db()
    done: dict[int, str] = {}
    docs = db.execute(select(SourceDocument).where(SourceDocument.original_retained.is_(True)).order_by(SourceDocument.id.desc())).scalars()
    for doc in docs:
        path = document_path(doc)
        ipo = db.get(IPOIssue, doc.ipo_id) if doc.ipo_id else None
        if path is None or ipo is None or ipo.id in done:
            continue
        with pymupdf.open(path) as pdf:
            texts = [p.get_text() for p in pdf]
            c = classify_industry(texts, ipo.company.name)
            kpis = lender_kpis(pdf, texts) if c.profile in ("lender", "insurer") else {}
            overview = business_overview(texts)
        store_classification(db, ipo, doc, c, kpis, StoreStats())
        if overview is not None:
            ipo.document_facts = {**(ipo.document_facts or {}), "business_overview": {
                "value": overview.value, "page": overview.page, "text": overview.text[:400], "basis": overview.basis,
                "document_id": doc.id, "read_at": utcnow().isoformat()}}
        db.commit()
        done[ipo.id] = f"{c.sector} ({c.profile})"
    print(json.dumps({"classified": len(done), "rescored": refresh_scores(db)}))
    return 0


def cmd_worker(_: argparse.Namespace) -> int:
    """Run only the ingestion scheduler (use when the API runs without KCP_SCHEDULER_ENABLED)."""
    import signal
    import time

    from app.ingestion.ingestion_scheduler import scheduler_status, start_scheduler, stop_scheduler

    start_scheduler()
    print("ingestion worker running — Ctrl+C to stop")
    for j in scheduler_status().get("jobs", []):
        print(f"  {j['id']:<14} every {j['interval_minutes']} min, next {j['next_run_at']}")
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    try:
        while not stop["flag"]:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    stop_scheduler()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=cmd_migrate)
    p = sub.add_parser("seed-demo", help="load the synthetic demonstration fixture")
    p.add_argument("--reset", action="store_true", help="remove and recreate demo IPOs (refreshes relative dates)")
    p.set_defaults(fn=cmd_seed_demo)
    p = sub.add_parser("create-admin", help="create the first administrator interactively")
    p.add_argument("--email")
    p.add_argument("--name")
    p.set_defaults(fn=cmd_create_admin)
    p = sub.add_parser("reset-password", help="set a new password for an account (revokes its sessions)")
    p.add_argument("email")
    p.set_defaults(fn=cmd_reset_password)
    p = sub.add_parser("sync", help="fetch live IPO data now (NSE public feeds)")
    p.add_argument("job", nargs="?", default="all",
                   choices=["all", "discover", "details", "subscriptions", "listings", "filings", "documents", "peers", "health"])
    p.set_defaults(fn=cmd_sync)
    sub.add_parser("reclassify", help="re-run the industry classifier over stored offer documents, then rescore").set_defaults(fn=cmd_reclassify)
    sub.add_parser("refresh-scores", help="recompute stored scores and completeness for every IPO (rows added only on change)").set_defaults(
        fn=cmd_refresh_scores)
    p = sub.add_parser("process-documents", help="download and extract queued offer documents now (still one request at a time)")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(fn=cmd_process_documents)
    p = sub.add_parser("backfill-history", help="import listed issues from a longer window, then their listing-day prices")
    p.add_argument("--days", type=int, default=365)
    p.set_defaults(fn=cmd_backfill_history)
    p = sub.add_parser("e2e-demo", help="run the full pipeline for one real IPO twice and report each step (idempotency check)")
    p.add_argument("symbol", help="NSE symbol, e.g. BCSSL")
    p.add_argument("--report", help="write a Markdown report to this path")
    p.set_defaults(fn=cmd_e2e_demo)
    sub.add_parser("worker", help="run the ingestion scheduler as a standalone process").set_defaults(fn=cmd_worker)
    p = sub.add_parser("ingest", help="ingest a local PDF/TXT offer document")
    p.add_argument("path")
    p.add_argument("--ipo-id", type=int)
    p.add_argument("--title")
    p.add_argument("--url")
    p.add_argument("--doc-type", default="rhp", choices=["drhp", "rhp", "prospectus", "annual_report", "disclosure", "other"])
    p.set_defaults(fn=cmd_ingest)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
