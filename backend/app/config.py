"""Centralised application settings, read from environment variables / .env.

Nothing in here is a secret by default. Secrets (if any) must be provided through
environment variables and are never logged.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_prefix="KCP_", extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'kcpinsights.db'}"
    data_dir: Path = BACKEND_DIR / "data"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    cache_dir: Path = BACKEND_DIR / "data" / "cache"

    # Comma-separated list of browser origins allowed to call the API directly.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    session_cookie_name: str = "kcp_session"
    csrf_cookie_name: str = "kcp_csrf"
    session_ttl_hours: int = 24 * 7
    session_idle_hours: int = 24 * 2

    request_timeout_seconds: float = 90.0
    max_upload_mb: int = 20
    max_pdf_pages: int = 600

    # Mode C: allow-listed official hosts for server-side document fetching.
    source_allowed_hosts: str = (
        "www.sebi.gov.in,sebi.gov.in,www.nseindia.com,nsearchives.nseindia.com,"
        "www.bseindia.com,bseindia.com"
    )
    source_fetch_timeout_seconds: float = 20.0
    source_fetch_max_mb: int = 25
    source_fetch_min_interval_seconds: float = 5.0
    source_user_agent: str = "KcpInsights-Research/1.0 (educational; manual-trigger)"

    # --- Live ingestion (Mode C) ----------------------------------------------------------
    scheduler_enabled: bool = True  # in-process scheduler inside the API (also: `python -m app.cli worker`)
    ingest_enabled: bool = True
    ingest_min_request_interval_seconds: float = 2.5  # per host, never concurrent
    ingest_discovery_minutes: int = 360
    ingest_details_minutes: int = 360
    ingest_subscription_minutes: int = 20
    ingest_listing_minutes: int = 45
    ingest_health_minutes: int = 30
    ingest_documents_minutes: int = 60  # each run handles at most ingest_max_documents_per_run documents
    ingest_listing_window_days: int = 120  # how far back recently listed issues are imported
    ingest_max_detail_fetches_per_run: int = 15
    # Official offer documents (RHP) from NSE archives: downloaded, parsed for restated financials, then scored.
    ingest_download_offer_documents: bool = True
    ingest_max_offer_document_mb: int = 80  # per download; RHP archives are typically 10–30 MB
    ingest_max_documents_per_run: int = 3
    documents_max_total_mb: int = 1500  # originals beyond this are pruned (oldest listed first); extracted data is kept
    document_recheck_days: int = 3  # upcoming/open issues: re-check the archive for a revised RHP (HEAD request)
    document_window_days: int = 180  # listed issues older than this are not fetched
    document_max_attempts: int = 5  # failed downloads/extractions retry with exponential backoff, then become dead letters
    # SEBI public-issue filings (draft and red herring offer documents), first listing page polled daily
    ingest_sebi_filings: bool = True
    ingest_filings_minutes: int = 720
    # listed peers: daily official closing price from the NSE bhavcopy, matched via the NSE equity list
    ingest_peer_prices_minutes: int = 1440
    # Gap filling for every IPO, not only active ones: NSE issue details are re-checked weekly while NSE-published fields
    # are missing; the enrichment job adds face value/ISIN from NSE's equity lists, the shareholding pattern filed with
    # NSE after listing, and re-reads stored offer documents when the offer-terms extractor changes
    details_recheck_days: int = 7
    ingest_enrichment_minutes: int = 360
    ingest_max_shareholding_per_run: int = 15
    ingest_max_offer_term_rereads_per_run: int = 10
    # Unattended operation: daily database backups (data/backups, newest kept), health problems and local alerts
    backup_enabled: bool = True
    backup_hours: int = 24
    backup_keep: int = 14
    min_free_disk_gb: float = 2.0
    desktop_alerts: bool = False  # macOS notification when the set of health problems changes (no network)
    # Local OCR (Tesseract) for image-only prospectus pages; skipped automatically when Tesseract is not installed
    ocr_enabled: bool = True
    ocr_max_pages: int = 150
    ocr_dpi: int = 300
    ocr_time_budget_seconds: int = 600
    # Freshness thresholds used for stale-data warnings
    stale_subscription_minutes: int = 120
    stale_issue_details_hours: int = 24
    stale_peer_price_days: int = 30  # peer prices older than this (vs the issue) are flagged
    log_format: Literal["text", "json"] = "text"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_source_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.source_allowed_hosts.split(",") if h.strip()}



@lru_cache
def get_settings() -> Settings:
    return Settings()
