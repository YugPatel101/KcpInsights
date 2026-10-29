"""Command-line administration: migrations, demo seed, first admin, model training, documents.

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


def cmd_train(a: argparse.Namespace) -> int:
    from app.services.prediction import run_training

    res = run_training(_db(), synthetic=a.synthetic)
    res.pop("params", None)
    print(json.dumps(res, indent=2, default=str))
    if a.synthetic:
        print("\nNOTE: synthetic pipeline test — these metrics are NOT evidence of predictive performance.")
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
    print(f"document {doc.id}: {doc.page_count} pages, {len(doc.chunks)} chunks, embeddings: {doc.embedding_model or 'none (keyword search)'}")
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
    p = sub.add_parser("train-model", help="train/evaluate the listing-outcome baselines on stored real data")
    p.add_argument("--synthetic", action="store_true", help="pipeline test on a clearly labelled synthetic dataset")
    p.set_defaults(fn=cmd_train)
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
