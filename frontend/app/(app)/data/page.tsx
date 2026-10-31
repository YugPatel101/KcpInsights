"use client";

import ExceptionsPanel from "@/components/live/ExceptionsPanel";
import SystemHealthPanel from "@/components/live/SystemHealthPanel";

import Link from "next/link";
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Panel, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, titleCase } from "@/lib/format";
import { timeAgo } from "@/lib/time";
import { useApi } from "@/lib/useApi";
import type { FreshnessReport, SyncStatus } from "@/lib/types";

const HEALTH: Record<string, string> = {
  healthy: "text-pos-ink", degraded: "text-warn-ink", down: "text-neg-ink", blocked: "text-neg-ink",
  manual: "text-ink-2", reachable: "text-brand-ink", unknown: "text-ink-2",
};
const JOB: Record<string, string> = { success: "text-pos-ink", partial: "text-warn-ink", failed: "text-neg-ink", skipped: "text-ink-2", running: "text-brand-ink" };

function AdminSync({ onDone }: { onDone: () => void }) {
  const [job, setJob] = useState("all");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select className={`${inputClass} w-auto`} value={job} onChange={(e) => setJob(e.target.value)} aria-label="Job to run">
        {["all", "discover", "details", "subscriptions", "listings", "filings", "documents", "peers", "health"].map((j) => <option key={j} value={j}>{titleCase(j)}</option>)}
      </select>
      <button
        className={buttonClass.primary}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setMsg(null);
          try {
            await api("/api/admin/data-sync", { body: { job } });
            setMsg("Started in the background. The job list refreshes every 15 seconds.");
            onDone();
          } catch (e) {
            setMsg(errorMessage(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? <Spinner /> : <RefreshCw className="size-4" />} Run sync
      </button>
      {msg && <span className="text-sm text-ink-2" role="status">{msg}</span>}
    </div>
  );
}

export default function DataPipelinePage() {
  const { user } = useAuth();
  const sync = useApi<SyncStatus>("/api/data/sync-status?limit=40", { refreshMs: 15_000 });
  const fresh = useApi<FreshnessReport>("/api/data/freshness", { refreshMs: 60_000 });
  if (sync.error) return <ErrorState message={sync.error} onRetry={sync.reload} />;
  if (!sync.data || !fresh.data) return <LoadingBlock rows={8} />;
  const s = sync.data;
  const f = fresh.data;
  return (
    <>
      <PageHeader
        eyebrow="System"
        title="System health"
        subtitle="Discovery → source resolution → document download → extraction → validation → calculation → scoring, observed end to end. Scheduled jobs fetch each public source once and store normalised data; every page reads only from the database. A source outage never deletes stored records."
        actions={user?.is_admin ? <AdminSync onDone={sync.reload} /> : undefined}
      />
      <div className="space-y-6">
        {!s.scheduler.running && <Notice tone="warn">The automatic scheduler is not running in this API process. {s.scheduler.note}</Notice>}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Panel title="Last successful sync"><p className="text-xl font-semibold text-ink">{timeAgo(f.last_successful_sync_at)}</p><p className="text-xs text-ink-3">{fmtDateTime(f.last_successful_sync_at)} · {f.last_successful_job ?? "—"}</p></Panel>
          <Panel title="Stale records"><p className={`text-xl font-semibold ${f.stale_records.length ? "text-warn-ink" : "text-ink"}`}>{f.stale_records.length}</p><p className="text-xs text-ink-3">live IPOs past their freshness window</p></Panel>
          <Panel title="Missing critical fields"><p className="text-xl font-semibold text-ink">{f.missing_critical_fields.length}</p><p className="text-xs text-ink-3">upcoming/open/closed IPOs</p></Panel>
          <Panel title="Scheduler"><p className="text-sm font-medium text-ink">{s.scheduler.running ? "Running" : "Stopped"}</p><p className="text-xs text-ink-3">{s.scheduler.jobs?.length ?? 0} scheduled jobs in this API process</p></Panel>
        </div>

        <SystemHealthPanel />

        <ExceptionsPanel />

        <Panel title="Sources" subtitle="Only sources that answered with validated data are marked healthy. Manual sources require imports.">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wider text-ink-3"><th className="py-2 pr-3">Source</th><th className="py-2 pr-3">Access</th><th className="py-2 pr-3">Health</th><th className="py-2 pr-3">Last success</th><th className="py-2 pr-3">Requests</th><th className="py-2">Notes / last error</th></tr></thead>
              <tbody>
                {s.sources.map((src) => (
                  <tr key={src.key} className="border-t border-line align-top">
                    <td className="py-2 pr-3">{src.base_url ? <a href={src.base_url} className="text-brand-ink hover:underline" target="_blank" rel="noopener noreferrer">{src.name}</a> : <span className="text-ink">{src.name}</span>}<div className="text-xs text-ink-3">{src.authority}</div></td>
                    <td className="py-2 pr-3 text-ink-2">{src.access_mode === "automatic" ? "automatic" : "manual import"}</td>
                    <td className={`py-2 pr-3 font-medium ${HEALTH[src.health_status] ?? "text-ink-2"}`}>{src.health_status}{src.is_stale ? " · stale" : ""}</td>
                    <td className="py-2 pr-3 text-ink-2">{timeAgo(src.last_success_at)}</td>
                    <td className="py-2 pr-3 tabular-nums text-ink-2">{src.requests_made}</td>
                    <td className="py-2 text-xs text-ink-2">{src.last_error ? <span className="text-neg-ink">{src.last_error}</span> : src.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Scheduler" subtitle="Intervals are upper bounds on how often each source is contacted; jobs sharing a source never overlap.">
          <ul className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(s.intervals_minutes).map(([job, min]) => {
              const next = s.scheduler.jobs?.find((j) => j.id === job)?.next_run_at;
              return <li key={job} className="rounded-lg border border-line px-3 py-2"><span className="text-ink">{titleCase(job)}</span> <span className="text-ink-3">every {min} min</span>{next && <div className="text-xs text-ink-3">next {fmtDateTime(next)}</div>}</li>;
            })}
          </ul>
        </Panel>

        <Panel title="Recent jobs">
          {s.jobs.length ? (
            <div className="relative overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead><tr className="text-left text-xs uppercase tracking-wider text-ink-3"><th className="py-2 pr-3">Started</th><th className="py-2 pr-3">Job</th><th className="py-2 pr-3">Status</th><th className="py-2 pr-3 text-right">Found</th><th className="py-2 pr-3 text-right">New</th><th className="py-2 pr-3 text-right">Updated</th><th className="py-2 pr-3 text-right">Fields changed</th><th className="py-2 pr-3 text-right">Requests</th><th className="py-2">Detail</th></tr></thead>
                <tbody>
                  {s.jobs.map((j) => (
                    <tr key={j.id} className="border-t border-line align-top">
                      <td className="py-1.5 pr-3 text-ink-2">{fmtDateTime(j.started_at)}</td>
                      <td className="py-1.5 pr-3 text-ink">{j.job_type}<span className="ml-1 text-xs text-ink-3">({j.trigger})</span></td>
                      <td className={`py-1.5 pr-3 font-medium ${JOB[j.status]}`}>{j.status}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{j.records_discovered}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{j.records_created}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{j.records_updated}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{j.fields_changed}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{j.requests_made}</td>
                      <td className="py-1.5 text-xs text-ink-3">{j.errors.length ? <span className="text-neg-ink">{j.errors.length} error(s): {String(j.errors[0].error ?? "").slice(0, 80)}</span> : String(j.detail.reason ?? "")}{j.warning_count ? ` · ${j.warning_count} warning(s)` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No ingestion jobs yet" body="Start the API with the scheduler enabled, run `python -m app.cli sync`, or (as admin) use Run sync." />
          )}
        </Panel>

        <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
          <Panel title="Stale records">
            {f.stale_records.length ? (
              <ul className="space-y-1 text-sm">{f.stale_records.map((r) => <li key={r.id}><Link href={`/ipos/${r.id}`} className="text-ink hover:underline">{r.company_name}</Link> <span className="text-xs text-ink-3">({r.status}) — {r.reasons.join("; ")}</span></li>)}</ul>
            ) : <p className="text-sm text-ink-3">None.</p>}
          </Panel>
          <Panel title="Missing critical fields" subtitle="Fields the connected sources have not published. They stay empty rather than being estimated.">
            {f.missing_critical_fields.length ? (
              <ul className="space-y-1 text-sm">{f.missing_critical_fields.slice(0, 20).map((r) => <li key={r.id}><Link href={`/ipos/${r.id}`} className="text-ink hover:underline">{r.company_name}</Link> <span className="text-xs text-ink-3">— {r.missing.join(", ")}</span></li>)}</ul>
            ) : <p className="text-sm text-ink-3">None.</p>}
          </Panel>
        </div>

        <Panel title="Recent field changes" subtitle="Date, price and listing changes detected between syncs.">
          {f.recent_changes.length ? (
            <ul className="space-y-1 text-sm">
              {f.recent_changes.map((c, i) => (
                <li key={i} className="text-ink-2"><span className="text-ink-3">{fmtDateTime(c.changed_at)}</span> · <Link href={`/ipos/${c.ipo_id}`} className="text-ink hover:underline">IPO #{c.ipo_id}</Link> {titleCase(c.field)}: {String(c.old_value)} → <span className="text-ink">{String(c.new_value)}</span> <span className="text-xs">({c.source_key})</span></li>
              ))}
            </ul>
          ) : <p className="text-sm text-ink-3">No changes recorded yet.</p>}
        </Panel>
      </div>
    </>
  );
}
