"use client";

import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { CompletenessMeter, ErrorState, FieldStatusLabel, LoadingBlock, Panel, ReadinessBadge, tableClass } from "@/components/kcp/ui";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Completeness, FieldState } from "@/lib/types";

function show(f: FieldState): string {
  const v = f.value;
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return `${fmtNum(v, Number.isInteger(v) ? 0 : 2)}${f.unit && !["₹ crore", "₹ cr"].includes(f.unit) ? ` ${f.unit}` : f.unit ? " cr" : ""}`;
  return String(v);
}

/** Field-by-field completeness: what is on record, from where, as of when — and why anything is missing. */
export default function CompletenessPanel({ ipoId }: { ipoId: number }) {
  const { data, error, loading, reload } = useApi<Completeness>(`/api/ipos/${ipoId}/completeness`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading && !data) return <LoadingBlock rows={6} />;
  if (!data) return null;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Analysis readiness" subtitle={data.note}>
          <div className="flex items-baseline gap-3">
            <span className="text-4xl font-semibold tabular-nums text-ink">{Math.round(data.overall_pct)}%</span>
            <ReadinessBadge level={data.readiness.level} />
          </div>
          {data.readiness.reason && <p className="mt-2 text-sm text-ink-2">{data.readiness.reason}</p>}
          <ul className="mt-4 space-y-2">
            {data.groups.map((g) => (
              <li key={g.key} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-ink-2">{g.label}</span>
                <span className="flex items-center gap-2">
                  <span className="text-xs text-ink-3">{g.available}/{g.available + g.partial + g.missing}{g.not_applicable ? ` · ${g.not_applicable} n/a` : ""}</span>
                  <CompletenessMeter value={g.pct} label={g.label} />
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink-3">Computed {fmtDateTime(data.computed_at)}. Estimated and unverified fields count half; not-applicable and not-yet-expected fields are left out.</p>
        </Panel>
        <Panel title="Pipeline" subtitle="Discovery → document → extraction → checks → ratios → score" className="lg:col-span-2">
          <ol className="grid gap-2 sm:grid-cols-2">
            {data.pipeline.map((p) => (
              <li key={p.stage} className="flex items-start gap-2.5 rounded-md border border-line bg-surface-2 px-3 py-2.5">
                {p.status === "done" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-pos" aria-label="done" />
                  : p.status === "failed" ? <XCircle className="mt-0.5 size-4 shrink-0 text-neg" aria-label="failed" />
                  : <CircleDashed className="mt-0.5 size-4 shrink-0 text-ink-3" aria-label="pending" />}
                <span className="min-w-0">
                  <span className="block text-sm text-ink">{p.label}</span>
                  {p.detail && <span className="block text-xs leading-5 text-ink-3">{p.detail.slice(0, 220)}</span>}
                </span>
              </li>
            ))}
          </ol>
          {data.sources_tried.length > 0 && (
            <>
              <h3 className="mb-2 mt-5 text-[11px] font-medium uppercase tracking-wider text-ink-3">Offer-document sources tried</h3>
              <ul className="space-y-1.5 text-sm">
                {data.sources_tried.map((s, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-ink">{s.source}</span>
                    <span className="text-xs text-ink-3">{s.status.replace(/_/g, " ")}</span>
                    {s.detail && <span className="text-xs text-ink-3">— {s.detail.slice(0, 160)}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>
      </div>

      {data.groups.map((g) => (
        <Panel key={g.key} title={g.label} subtitle={g.pct === null ? "nothing expected at this stage" : `${Math.round(g.pct)}% complete`}>
          <div className={tableClass.wrap}>
            <table className={tableClass.table}>
              <thead className={tableClass.thead}>
                <tr>
                  <th className={tableClass.th}>Field</th><th className={tableClass.th}>Status</th><th className={`${tableClass.th} text-right`}>Value</th>
                  <th className={tableClass.th}>Source · period</th><th className={tableClass.th}>Reason / note</th>
                </tr>
              </thead>
              <tbody>
                {g.fields.map((f) => (
                  <tr key={f.key} className={`${tableClass.tr} align-top`}>
                    <td className={`${tableClass.td} text-ink`}>{f.label}</td>
                    <td className={tableClass.td}><FieldStatusLabel status={f.status} />{f.stale && <span className="ml-2 text-xs text-warn-ink">stale</span>}</td>
                    <td className={`${tableClass.td} ${tableClass.num} text-ink`}>{show(f)}</td>
                    <td className={`${tableClass.td} text-xs`}>
                      {f.source ?? "—"}{f.period ? ` · ${f.period}` : ""}
                      {f.as_of && <span className="block text-ink-3">as of {fmtDateTime(f.as_of)}</span>}
                    </td>
                    <td className={`${tableClass.td} max-w-md text-xs leading-5 text-ink-3`}>{f.reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ))}
    </div>
  );
}
