"""BSE adapter — currently blocked for automated access.

On 2026-10-29 every request from this environment to ``api.bseindia.com`` (including its
robots.txt) returned "Access Denied" from BSE's edge protection. KcpInsights does not
bypass such controls, so this adapter only performs an occasional health check and
reports the source as requiring manual import (Import data page / CSV / JSON bundle).
"""
from __future__ import annotations

from app.ingestion.http import PoliteClient, SourceError
from app.ingestion.sources.base import FetchResult, IPODataSource

HEALTH_URL = "https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w"


class BSEPublicIssuesSource(IPODataSource):
    key = "bse_ipo"
    name = "BSE public issues"
    authority = "official"

    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    def health_check(self) -> FetchResult[str]:
        try:
            self.client.get(HEALTH_URL)
        except SourceError as exc:
            if exc.kind == "access_denied":
                return FetchResult.unavailable("blocked: BSE refuses automated requests (Access Denied); use manual import")
            if exc.status in (301, 302, 303, 307, 308):
                return FetchResult.unavailable("endpoint redirected (moved or gated); no automated access path verified — use manual import")
            return FetchResult.unavailable(f"{exc.kind}: {exc}")
        return FetchResult.ok("reachable — no adapter implemented; manual import still required")
