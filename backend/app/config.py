"""Centralised application settings, read from environment variables / .env.

Nothing in here is a secret by default. Secrets (if any) must be provided through
environment variables and are never logged.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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

    # --- AI provider configuration -------------------------------------------------
    # "auto": use Ollama when its health check passes, otherwise the deterministic engine.
    # "deterministic": never call a model. "ollama": prefer Ollama (still falls back).
    ai_provider: Literal["auto", "deterministic", "ollama", "external"] = "auto"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_small_model: str = "qwen2.5:1.5b"
    ollama_use_small_model: bool = False
    ollama_embed_model: str = "nomic-embed-text"
    ollama_timeout_seconds: float = 60.0

    # Optional OpenAI-compatible endpoint. Disabled by default and never required.
    external_llm_enabled: bool = False
    external_llm_base_url: str = ""
    external_llm_model: str = ""
    external_llm_api_key: str = Field(default="", repr=False)

    # Agent limits (prevent runaway loops)
    agent_max_steps: int = 6
    agent_max_tool_calls: int = 12
    agent_deadline_seconds: float = 75.0
    agent_max_context_chars: int = 24_000

    # Mode C: allow-listed official hosts for server-side document fetching.
    source_allowed_hosts: str = (
        "www.sebi.gov.in,sebi.gov.in,www.nseindia.com,nsearchives.nseindia.com,"
        "www.bseindia.com,bseindia.com"
    )
    source_fetch_timeout_seconds: float = 20.0
    source_fetch_max_mb: int = 25
    source_fetch_min_interval_seconds: float = 5.0
    source_user_agent: str = "KcpInsights-Research/1.0 (educational; manual-trigger)"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_source_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.source_allowed_hosts.split(",") if h.strip()}

    @property
    def active_ollama_model(self) -> str:
        return self.ollama_small_model if self.ollama_use_small_model else self.ollama_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
