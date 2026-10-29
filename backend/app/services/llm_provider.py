"""Provider-independent LLM adapter.

* ``OllamaProvider`` — local open-weight model served by Ollama (default, zero cost).
* ``ExternalProvider`` — optional OpenAI-compatible endpoint, disabled by default.
* No provider available -> callers use the deterministic engine; nothing is fabricated.

A provider is reported as available only after its health check succeeds *and* the
configured model is present locally.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings


class ProviderError(RuntimeError):
    """Raised for timeouts, HTTP failures and invalid model output."""


@dataclass
class ProviderHealth:
    name: str
    available: bool
    model: str | None
    detail: str
    models_present: list[str] = field(default_factory=list)
    embedding_model: str | None = None
    embedding_available: bool = False
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("checked_at", None)
        return d


def _model_present(wanted: str, names: list[str]) -> bool:
    w = wanted if ":" in wanted else f"{wanted}:latest"
    return wanted in names or w in names


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.s = settings
        self.model = settings.active_ollama_model
        self.client = client or httpx.Client(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds)

    def health(self) -> ProviderHealth:
        try:
            r = self.client.get("/api/tags", timeout=2.5)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as exc:
            return ProviderHealth(self.name, False, self.model, f"Ollama not reachable at {self.s.ollama_base_url}: {type(exc).__name__}")
        ok = _model_present(self.model, names)
        emb = _model_present(self.s.ollama_embed_model, names)
        detail = "ready" if ok else f"model '{self.model}' not downloaded (run: ollama pull {self.model})"
        return ProviderHealth(self.name, ok, self.model, detail, names, self.s.ollama_embed_model, emb)

    def chat_json(self, system: str, messages: list[dict[str, str]], schema: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.1, "num_ctx": 8192},
        }
        try:
            r = self.client.post("/api/chat", json=body, timeout=timeout or self.s.ollama_timeout_seconds)
            r.raise_for_status()
            content = r.json()["message"]["content"]
        except httpx.TimeoutException as exc:
            raise ProviderError("model request timed out") from exc
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderError(f"model request failed: {type(exc).__name__}") from exc
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("model returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("model returned non-object JSON")
        return data

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = self.client.post("/api/embed", json={"model": self.s.ollama_embed_model, "input": texts}, timeout=60)
            r.raise_for_status()
            emb = r.json()["embeddings"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderError(f"embedding request failed: {type(exc).__name__}") from exc
        if len(emb) != len(texts):
            raise ProviderError("embedding count mismatch")
        return emb


class ExternalProvider:
    """Optional OpenAI-compatible chat endpoint. Never required; off unless explicitly enabled."""

    name = "external"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.s = settings
        self.model = settings.external_llm_model
        self.client = client or httpx.Client(base_url=settings.external_llm_base_url.rstrip("/"), timeout=settings.ollama_timeout_seconds)

    def health(self) -> ProviderHealth:
        if not (self.s.external_llm_enabled and self.s.external_llm_base_url and self.model):
            return ProviderHealth(self.name, False, self.model or None, "disabled (KCP_EXTERNAL_LLM_ENABLED=false)")
        try:
            r = self.client.get("/models", headers=self._headers(), timeout=4)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(self.name, False, self.model, f"endpoint unreachable: {type(exc).__name__}")
        return ProviderHealth(self.name, True, self.model, "ready")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.s.external_llm_api_key}"} if self.s.external_llm_api_key else {}

    def chat_json(self, system: str, messages: list[dict[str, str]], schema: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system + "\nRespond with one JSON object only."}, *messages],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            r = self.client.post("/chat/completions", json=body, headers=self._headers(), timeout=timeout or self.s.ollama_timeout_seconds)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except httpx.TimeoutException as exc:
            raise ProviderError("model request timed out") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"model request failed: {type(exc).__name__}") from exc
        if not isinstance(data, dict):
            raise ProviderError("model returned non-object JSON")
        return data

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError("external provider does not provide embeddings")


_cache_lock = threading.Lock()
_health_cache: dict[str, ProviderHealth] = {}
HEALTH_TTL = 20.0


def _cached_health(p: OllamaProvider | ExternalProvider) -> ProviderHealth:
    with _cache_lock:
        h = _health_cache.get(p.name)
        if h and time.time() - h.checked_at < HEALTH_TTL:
            return h
    h = p.health()
    with _cache_lock:
        _health_cache[p.name] = h
    return h


def reset_health_cache() -> None:
    with _cache_lock:
        _health_cache.clear()


@dataclass
class ProviderSelection:
    provider: OllamaProvider | ExternalProvider | None
    mode: str  # "ollama" | "external" | "deterministic"
    reason: str
    health: list[dict[str, Any]]


def select_provider(settings: Settings | None = None) -> ProviderSelection:
    s = settings or get_settings()
    if s.ai_provider == "deterministic":
        return ProviderSelection(None, "deterministic", "AI provider set to deterministic", [])
    candidates: list[OllamaProvider | ExternalProvider] = []
    if s.ai_provider in ("auto", "ollama"):
        candidates.append(OllamaProvider(s))
    if s.ai_provider == "external" or (s.ai_provider == "auto" and s.external_llm_enabled):
        candidates.append(ExternalProvider(s))
    healths = []
    for c in candidates:
        h = _cached_health(c)
        healths.append(h.to_dict())
        if h.available:
            return ProviderSelection(c, c.name, h.detail, healths)
    reason = "; ".join(f"{h['name']}: {h['detail']}" for h in healths) or "no provider configured"
    return ProviderSelection(None, "deterministic", reason, healths)


def embedding_provider(settings: Settings | None = None) -> OllamaProvider | None:
    s = settings or get_settings()
    if s.ai_provider == "deterministic":
        return None
    p = OllamaProvider(s)
    h = _cached_health(p)
    return p if h.embedding_available else None
