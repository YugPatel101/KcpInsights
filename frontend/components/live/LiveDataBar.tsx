"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { Spinner, buttonClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/time";
import { useApi } from "@/lib/useApi";
import type { FreshnessReport } from "@/lib/types";

/** Data freshness strip: last successful sync, source health, stale records. Polls the database every minute. */
export default function LiveDataBar() {
  const { user } = useAuth();
  const { data, error, reload } = useApi<FreshnessReport>("/api/data/freshness", { refreshMs: 60_000 });
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (error) {
    return (
      <div className="mb-6 flex items-center gap-2 rounded-xl border border-neg/30 bg-neg/5 px-4 py-2.5 text-sm text-neg-ink" role="status">
        <WifiOff className="size-4" aria-hidden /> Data status unavailable: {error}
      </div>
    );
  }
  if (!data) return null;
  const nse = data.sources.find((s) => s.key === "nse_ipo");
  const healthy = nse?.health_status === "healthy" && !nse.is_stale;
  const stale = data.stale_records.length;
  return (
    <div className={`mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border px-4 py-2.5 text-sm ${healthy ? "border-pos/20 bg-pos/[0.04]" : "border-warn/30 bg-warn/[0.06]"}`} role="status">
      <span className="flex items-center gap-2 text-ink">
        {healthy ? <Wifi className="size-4 text-pos-ink" aria-hidden /> : <AlertTriangle className="size-4 text-warn-ink" aria-hidden />}
        {data.last_successful_sync_at ? (
          <>Data from NSE public sources · last successful sync <strong className="font-medium">{timeAgo(data.last_successful_sync_at)}</strong></>
        ) : (
          <>No data sync has completed yet</>
        )}
      </span>
      {nse && !healthy && <span className="text-warn-ink">NSE source: {nse.health_status}{nse.is_stale ? " (stale)" : ""}{nse.last_error ? ` — ${nse.last_error.slice(0, 90)}` : ""}</span>}
      {stale > 0 && <span className="text-warn-ink">{stale} record{stale === 1 ? "" : "s"} stale — showing last known values</span>}
      <span className="text-ink-3">{data.scheduler.running ? "auto-refresh on" : "auto-refresh off in this process"}</span>
      <span className="ml-auto flex items-center gap-2">
        {msg && <span className="text-xs text-ink-2">{msg}</span>}
        {user?.is_admin && (
          <button
            className={buttonClass.ghost}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api("/api/admin/data-sync", { body: { job: "all" } });
                setMsg("Sync started — this page refreshes automatically.");
                window.setTimeout(reload, 15_000);
              } catch (e) {
                setMsg(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? <Spinner /> : <RefreshCw className="size-3.5" aria-hidden />} Sync now
          </button>
        )}
        <Link href="/data" className="text-xs text-brand-ink hover:underline">System health</Link>
      </span>
    </div>
  );
}
