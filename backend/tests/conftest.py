"""Test fixtures. Every test gets a fresh SQLite database built by Alembic migrations.

No test depends on a live external API or a downloaded LLM: AI providers are mocked.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="kcp-tests-"))
os.environ.setdefault("KCP_ENVIRONMENT", "test")
os.environ["KCP_DATABASE_URL"] = f"sqlite:///{_TMP / 'bootstrap.db'}"
os.environ["KCP_DATA_DIR"] = str(_TMP)
os.environ["KCP_UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["KCP_CACHE_DIR"] = str(_TMP / "cache")
os.environ["KCP_AI_PROVIDER"] = "deterministic"

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import BACKEND_DIR  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.db import get_db, make_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.llm_provider import reset_health_cache  # noqa: E402

TODAY = date.today()


def _migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture()
def db(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    _migrate(url)
    engine = make_engine(url)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    app.dependency_overrides[get_db] = lambda: (yield from _yield(Session))
    limiter.reset()
    reset_health_cache()
    yield session
    session.close()
    app.dependency_overrides.clear()
    engine.dispose()


def _yield(Session):
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def seeded(db):
    from app.services.demo_seed import seed_demo

    seed_demo(db, today=TODAY)
    return db


@pytest.fixture()
def client(db):
    return TestClient(app)


def register(client: TestClient, email: str = "user@example.com", password: str = "correct-horse-9", name: str = "User") -> str:
    r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()["csrf_token"]


def ipo_id_by_name(client: TestClient, prefix: str) -> int:
    items = client.get("/api/ipos", params={"page_size": 100}).json()["items"]
    return next(i["id"] for i in items if i["company_name"].startswith(prefix))
