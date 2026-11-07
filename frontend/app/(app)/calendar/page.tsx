"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Panel, StageBadge, buttonClass } from "@/components/kcp/ui";
import { cn } from "@/lib/utils";
import { useApi } from "@/lib/useApi";
import type { CalendarEvent, CalendarResponse } from "@/lib/types";

const EVENT_STYLE: Record<CalendarEvent["event"], string> = {
  open: "border-pos/40 text-pos-ink", close: "border-warn/40 text-warn-ink", allotment: "border-brand/40 text-brand-ink",
  refund: "border-line-strong text-ink-2", demat_credit: "border-line-strong text-ink-2", listing: "border-brand/60 bg-brand/10 text-ink",
};
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function CalendarPage() {
  const [month, setMonth] = useState(() => { const t = new Date(); return new Date(t.getFullYear(), t.getMonth(), 1); });
  const [type, setType] = useState<"" | "mainboard" | "sme">("");
  const [view, setView] = useState<"month" | "list">("month");
  const start = new Date(month.getFullYear(), month.getMonth(), 1);
  const end = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  const { data, error, loading, reload } = useApi<CalendarResponse>(`/api/calendar?start=${iso(start)}&end=${iso(end)}${type ? `&issue_type=${type}` : ""}`, { refreshMs: 300_000 });
  const byDay = useMemo(() => {
    const m: Record<string, CalendarEvent[]> = {};
    for (const e of data?.events ?? []) (m[e.date] ??= []).push(e);
    return m;
  }, [data]);
  const lead = (start.getDay() + 6) % 7; // Monday-first grid
  const cells = Array.from({ length: Math.ceil((lead + end.getDate()) / 7) * 7 }, (_, i) => {
    const day = i - lead + 1;
    return day >= 1 && day <= end.getDate() ? new Date(month.getFullYear(), month.getMonth(), day) : null;
  });
  const today = data?.today;

  const Chip = ({ e }: { e: CalendarEvent }) => (
    <Link href={`/ipos/${e.ipo_id}`} title={`${e.company_name}: ${e.label}${e.status === "estimated" ? " (estimated)" : " (confirmed by NSE)"}`}
          className={cn("block truncate rounded border px-1.5 py-0.5 text-[11px] leading-4 hover:bg-surface-3", EVENT_STYLE[e.event], e.status === "estimated" && "border-dashed opacity-80")}>
      {e.label.replace("Bidding ", "")}{e.status === "estimated" ? "*" : ""} · {e.company_name}
    </Link>
  );

  return (
    <>
      <PageHeader eyebrow="Listing calendar" title="IPO calendar"
                  subtitle="Openings, closings, allotment, refunds, demat credit and listing for every stored issue. Dashed chips with * are estimates; solid chips are dates published by NSE." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button className={buttonClass.secondary} aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft className="size-4" /></button>
        <div className="min-w-40 text-center text-lg font-semibold text-ink">{month.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</div>
        <button className={buttonClass.secondary} aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight className="size-4" /></button>
        <button className={buttonClass.ghost} onClick={() => { const t = new Date(); setMonth(new Date(t.getFullYear(), t.getMonth(), 1)); }}>Today</button>
        <div className="ml-auto flex gap-1">
          {([["", "All"], ["mainboard", "Mainboard"], ["sme", "SME"]] as const).map(([v, l]) => (
            <button key={v} className={type === v ? buttonClass.primary : buttonClass.secondary} onClick={() => setType(v)}>{l}</button>
          ))}
          {(["month", "list"] as const).map((v) => (
            <button key={v} className={view === v ? buttonClass.primary : buttonClass.secondary} onClick={() => setView(v)}>{v === "month" ? "Month" : "List"}</button>
          ))}
        </div>
      </div>
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingBlock rows={8} />}
      {data && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2 text-xs">
            {(Object.keys(EVENT_STYLE) as CalendarEvent["event"][]).map((k) => (
              <span key={k} className={cn("rounded border px-2 py-0.5", EVENT_STYLE[k])}>{{ open: "Opens", close: "Closes", allotment: "Allotment", refund: "Refunds", demat_credit: "Demat credit", listing: "Listing" }[k]}</span>
            ))}
            <span className="rounded border border-dashed border-line-strong px-2 py-0.5 text-ink-2">* estimated</span>
          </div>
          {view === "month" ? (
            <div className="overflow-x-auto">
              <div className="grid min-w-[840px] grid-cols-7 gap-px overflow-hidden rounded-xl border border-line bg-surface-3">
                {WEEKDAYS.map((w) => <div key={w} className="bg-[#0b0b0c] px-2 py-2 text-xs font-medium uppercase tracking-wider text-ink-3">{w}</div>)}
                {cells.map((d, i) => {
                  const key = d ? iso(d) : `x${i}`;
                  const evs = d ? byDay[iso(d)] ?? [] : [];
                  return (
                    <div key={key} className={cn("min-h-28 bg-[#0b0b0c] p-1.5", !d && "bg-surface", d && iso(d) === today && "ring-1 ring-inset ring-sky-400/60")}>
                      {d && <div className={cn("mb-1 text-xs tabular-nums", iso(d) === today ? "font-semibold text-brand-ink" : "text-ink-3")}>{d.getDate()}</div>}
                      <div className="space-y-0.5">
                        {evs.slice(0, 5).map((e) => <Chip key={`${e.ipo_id}-${e.event}`} e={e} />)}
                        {evs.length > 5 && <div className="text-[11px] text-ink-3">+{evs.length - 5} more</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : data.events.length ? (
            <Panel>
              <ol className="divide-y divide-line text-sm">
                {data.events.map((e) => (
                  <li key={`${e.date}-${e.ipo_id}-${e.event}`} className="flex flex-wrap items-center gap-3 py-2">
                    <span className="w-24 shrink-0 tabular-nums text-ink-2">{e.date}</span>
                    <span className={cn("w-28 shrink-0 rounded border px-1.5 py-0.5 text-center text-xs", EVENT_STYLE[e.event], e.status === "estimated" && "border-dashed")}>{e.label}</span>
                    <Link href={`/ipos/${e.ipo_id}`} className="min-w-0 flex-1 truncate text-ink hover:underline">{e.company_name}</Link>
                    <span className="text-xs text-ink-3">{e.issue_type === "sme" ? "SME" : "Mainboard"}</span>
                    <StageBadge stage={e.stage} />
                    <span className={e.status === "estimated" ? "text-xs text-warn-ink" : "text-xs text-pos-ink"}>{e.status}</span>
                  </li>
                ))}
              </ol>
            </Panel>
          ) : <EmptyState title="No dated events this month" />}
          <Notice>{data.note}</Notice>
        </div>
      )}
    </>
  );
}
