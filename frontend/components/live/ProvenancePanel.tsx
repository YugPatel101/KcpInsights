"use client";

import { DataStatusBadge, EmptyState, ErrorState, LoadingBlock, Panel } from "@/components/kcp/ui";
import { fmtDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { FieldProvenance } from "@/lib/types";

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 80 ? `${s.slice(0, 80)}…` : s;
}

/** Per-field provenance: source, first seen, last verified, status and conflicts. */
export default function ProvenancePanel({ ipoId }: { ipoId: number }) {
  const { data, error, loading, reload } = useApi<{ fields: Record<string, FieldProvenance> }>(`/api/ipos/${ipoId}/provenance`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock />;
  const entries = Object.entries(data.fields).filter(([, f]) => f.source_key);
  return (
    <Panel title="Field-level provenance" subtitle="Each value with the source that supplied it, when it was first seen and last re-verified. Conflicts are recorded, never silently overwritten.">
      {entries.length ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-3">Field</th><th className="py-2 pr-3">Value</th><th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Source</th><th className="py-2 pr-3">Last verified</th><th className="py-2">Basis</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([k, f]) => (
                <tr key={k} className="border-t border-white/5 align-top">
                  <td className="py-1.5 pr-3 text-slate-300">{titleCase(k)}</td>
                  <td className="py-1.5 pr-3 tabular-nums text-slate-100">{show(f.value)}</td>
                  <td className="py-1.5 pr-3"><DataStatusBadge status={f.data_status} compact />{f.conflicts > 0 && <span className="ml-1 text-[11px] text-amber-300">{f.conflicts} conflict{f.conflicts > 1 ? "s" : ""}</span>}</td>
                  <td className="py-1.5 pr-3 text-xs">{f.source_url ? <a href={f.source_url} target="_blank" rel="noopener noreferrer" className="text-sky-300 hover:underline">{f.source_key}</a> : <span className="text-slate-400">{f.source_key}</span>}</td>
                  <td className="py-1.5 pr-3 text-xs text-slate-400">{fmtDateTime(f.last_verified_at)}</td>
                  <td className="py-1.5 text-xs text-slate-500">{f.basis ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No field-level observations" body="Field-level provenance is recorded for live (source-connected) IPOs. Imported and demo records keep provenance per source record below." />
      )}
    </Panel>
  );
}
