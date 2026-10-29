"use client";

import { DataStatusBadge, EmptyState, ErrorState, LoadingBlock, Panel } from "@/components/kcp/ui";
import { fmtDate, fmtDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { SourceRecord } from "@/lib/types";

export default function SourcesPanel({ ipoId }: { ipoId: number }) {
  const { data, error, loading, reload } = useApi<{ sources: SourceRecord[] }>(`/api/ipos/${ipoId}/sources`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock />;
  if (!data.sources.length) return <EmptyState title="No source records" />;
  return (
    <Panel title="Data provenance" subtitle="Every stored value points to one of these records. Raw values as received are preserved with each record.">
      <ul className="divide-y divide-white/5">
        {data.sources.map((s) => (
          <li key={s.id} id={`source-${s.id}`} className="py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-slate-500">#{s.id}</span>
              {s.url ? (
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="font-medium text-sky-300 hover:underline">{s.title}</a>
              ) : (
                <span className="font-medium text-slate-200">{s.title}</span>
              )}
              <DataStatusBadge status={s.data_status} />
              <span className="text-xs text-slate-500">{titleCase(s.source_type)}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
              <span>Retrieved {fmtDateTime(s.retrieved_at)}</span>
              {s.publication_date && <span>Published {fmtDate(s.publication_date)}</span>}
              {s.reporting_period && <span>Period {s.reporting_period}</span>}
              {s.unit && <span>{s.currency} {s.unit}</span>}
              {s.transformation && <span className="text-amber-300/90">Transformation: {s.transformation}</span>}
            </div>
            <div className="mt-1 text-xs text-slate-500">Used for: {s.used_for.join(", ")}</div>
            {s.notes && <div className="mt-1 text-xs text-slate-500">{s.notes}</div>}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
