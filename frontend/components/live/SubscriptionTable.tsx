"use client";

import { DataStatusBadge, EmptyState, ErrorState, LoadingBlock, Notice, Panel } from "@/components/kcp/ui";
import { fmtDateTime, fmtInt, fmtNum } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { SubscriptionDetail } from "@/lib/types";

const LABEL: Record<string, string> = { qib: "QIB", nii: "Non-institutional (NII)", retail: "Retail (RII)", employee: "Employee", shareholder: "Shareholder", total: "Total" };
const ORDER = ["qib", "nii", "retail", "employee", "shareholder", "total"];

/** Exchange-published subscription by category. Polls the database every minute while bidding is open. */
export default function SubscriptionTable({ ipoId, live }: { ipoId: number; live: boolean }) {
  const { data, error, loading, reload } = useApi<SubscriptionDetail>(`/api/ipos/${ipoId}/subscription`, { refreshMs: live ? 60_000 : undefined });
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock rows={3} />;
  const rows = [...data.latest].sort((a, b) => ORDER.indexOf(a.category) - ORDER.indexOf(b.category));
  return (
    <Panel
      title="Subscription"
      subtitle={data.latest_as_of ? `As of ${fmtDateTime(data.latest_as_of)}${data.timezone ? ` ${data.timezone}` : ""} · ${data.basis_note}` : undefined}
    >
      {data.freshness.is_stale && <div className="mb-3"><Notice tone="warn">{data.freshness.stale_reasons.join("; ")} — showing the last published figures.</Notice></div>}
      {rows.length ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
              <th className="py-2">Category</th>
              <th className="py-2 text-right">Times subscribed</th>
              <th className="hidden py-2 text-right 2xl:table-cell">Shares offered</th>
              <th className="hidden py-2 text-right 2xl:table-cell">Shares bid</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.category} className={`border-t border-white/5 ${r.category === "total" ? "font-semibold" : ""}`}>
                <td className="py-1.5 text-slate-300">{LABEL[r.category] ?? r.category}</td>
                <td className="py-1.5 text-right tabular-nums text-slate-100">{fmtNum(r.times_subscribed, 2)}x</td>
                <td className="hidden py-1.5 text-right tabular-nums text-slate-400 2xl:table-cell">{fmtInt(r.shares_offered)}</td>
                <td className="hidden py-1.5 text-right tabular-nums text-slate-400 2xl:table-cell">{fmtInt(r.shares_bid)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <EmptyState title="No subscription figures published yet" body="Figures appear once the exchange publishes them for this issue; nothing is estimated." />
      )}
      {rows[0] && (
        <p className="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <DataStatusBadge status={rows[0].data_status} compact />
          {data.source_url ? <a className="hover:underline" href={data.source_url} target="_blank" rel="noopener noreferrer">NSE issue page</a> : "stored data"}
          {live && " · auto-updates every minute from the database"}
        </p>
      )}
    </Panel>
  );
}
