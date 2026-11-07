"use client";

import { History } from "lucide-react";
import { DataStatusBadge, Panel } from "@/components/kcp/ui";
import { fmtDate, fmtDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { FieldChangeRow, KeyDate } from "@/lib/types";

const DATE_FIELD: Record<string, string> = { open: "open_date", close: "close_date", allotment: "allotment_date", listing: "listing_date" };

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return fmtDate(v);
  return String(v);
}

/** Issue timeline: confirmed vs expected dates, with any recorded changes. */
export default function KeyDates({ ipoId, dates }: { ipoId: number; dates: KeyDate[] }) {
  const changes = useApi<{ changes: FieldChangeRow[] }>(`/api/ipos/${ipoId}/changes`);
  const rows = changes.data?.changes ?? [];
  return (
    <Panel title="Key dates" subtitle="Expected dates follow SEBI's T+3 timeline from the issue close and do not account for exchange holidays.">
      <ol className="space-y-2">
        {dates.map((d) => {
          const ch = rows.filter((c) => c.field === DATE_FIELD[d.key]);
          return (
            <li key={d.key} className="flex flex-wrap items-center justify-between gap-2 border-b border-line py-1.5 text-sm">
              <span className="text-ink-2">{d.label}</span>
              <span className="flex items-center gap-2">
                <span className="tabular-nums text-ink">{fmtDate(d.date)}</span>
                <DataStatusBadge status={d.status} compact />
                {ch.length > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-md border border-warn/30 px-1.5 py-0.5 text-[11px] text-warn-ink"
                    title={ch.map((c) => `${show(c.old_value)} → ${show(c.new_value)} (${fmtDateTime(c.changed_at)})`).join("\n")}>
                    <History className="size-3" aria-hidden /> changed
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
      {rows.length > 0 && (
        <details className="mt-3 text-xs text-ink-2">
          <summary className="cursor-pointer text-ink-2">Change history ({rows.length})</summary>
          <ul className="mt-2 space-y-1">
            {rows.map((c, i) => (
              <li key={i}>
                {fmtDateTime(c.changed_at)} · {titleCase(c.field)}: {show(c.old_value)} → <span className="text-ink">{show(c.new_value)}</span>{" "}
                <span className="text-ink-3">({c.source_key})</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}
