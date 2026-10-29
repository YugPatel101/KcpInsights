"use client";

import { Suspense, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import UpcomingTable from "@/components/dashboard/UpcomingTable";
import { EmptyState, ErrorState, LoadingBlock, PageHeader, buttonClass, inputClass } from "@/components/kcp/ui";
import { useApi } from "@/lib/useApi";
import type { IpoSummary, Paged } from "@/lib/types";

interface Meta {
  sectors: Record<string, number>;
  exchanges: string[];
  statuses: Record<string, number>;
  data_modes: Record<string, number>;
  total: number;
}

const SORTS = [
  ["-open_date", "Newest first"],
  ["open_date", "Oldest first"],
  ["-composite", "Research score ↓"],
  ["-quality", "Quality ↓"],
  ["risk", "Risk ↑ (lowest first)"],
  ["-issue_size", "Issue size ↓"],
  ["name", "Name A–Z"],
] as const;

function Filters() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const [moreOpen, setMoreOpen] = useState(false);
  const meta = useApi<Meta>("/api/ipos/meta");
  const query = sp.toString();
  const list = useApi<Paged<IpoSummary>>(`/api/ipos?${query}${query.includes("page_size") ? "" : "&page_size=20"}`);

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(sp.toString());
    if (value === null || value === "") next.delete(key);
    else next.set(key, value);
    if (key !== "page") next.delete("page");
    router.replace(`${pathname}?${next.toString()}`);
  };
  const page = Number(sp.get("page") ?? 1);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;
  const sectors = useMemo(() => Object.keys(meta.data?.sectors ?? {}), [meta.data]);

  const sel = (key: string, label: string, options: [string, string][]) => (
    <label className="text-xs text-slate-400">
      <span className="mb-1 block">{label}</span>
      <select className={inputClass} value={sp.get(key) ?? ""} onChange={(e) => set(key, e.target.value)}>
        <option value="">Any</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <div className="mb-6 grid gap-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <label className="text-xs text-slate-400 sm:col-span-2">
          <span className="mb-1 block">Search</span>
          <input className={inputClass} defaultValue={sp.get("q") ?? ""} placeholder="Company, sector, symbol" onKeyDown={(e) => { if (e.key === "Enter") set("q", (e.target as HTMLInputElement).value.trim()); }} onBlur={(e) => set("q", e.target.value.trim())} />
        </label>
        {sel("status", "Status", [["open", "Open"], ["upcoming", "Upcoming"], ["closed", "Closed"], ["listed", "Listed"], ["open,upcoming", "Open + upcoming"], ["withdrawn", "Withdrawn"]])}
        <button type="button" className={`${buttonClass.secondary} sm:hidden`} aria-expanded={moreOpen} onClick={() => setMoreOpen(!moreOpen)}>
          {moreOpen ? "Hide filters" : "More filters"}
        </button>
        {/* On phones the secondary filters collapse; from sm up they flow into the grid. */}
        <div className={moreOpen ? "contents" : "hidden sm:contents"}>
        {sel("issue_type", "Issue type", [["mainboard", "Mainboard"], ["sme", "SME"]])}
        {sel("sector", "Sector", sectors.map((s) => [s, s]))}
        {sel("exchange", "Exchange", (meta.data?.exchanges ?? []).map((e) => [e, e]))}
        {sel("risk_level", "Risk level", [["low", "Low"], ["moderate", "Moderate"], ["high", "High"]])}
        {sel("min_quality", "Min quality", [["40", "≥ 40"], ["55", "≥ 55"], ["70", "≥ 70"]])}
        {sel("min_valuation", "Min valuation score", [["25", "≥ 25"], ["50", "≥ 50"], ["75", "≥ 75"]])}
        {sel("min_issue_size", "Min issue size", [["100", "≥ ₹100 cr"], ["500", "≥ ₹500 cr"], ["1000", "≥ ₹1,000 cr"]])}
        {sel("data_mode", "Data mode", [["demo", "Demo (synthetic)"], ["imported", "Imported"], ["source", "Source-connected"]])}
        </div>
        <label className="text-xs text-slate-400">
          <span className="mb-1 block">Sort</span>
          <select className={inputClass} value={sp.get("sort") ?? "-open_date"} onChange={(e) => set("sort", e.target.value)}>
            {SORTS.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <button className={buttonClass.ghost} onClick={() => router.replace(pathname)}>Reset filters</button>
        </div>
      </div>

      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <LoadingBlock rows={6} />}
      {list.data && (
        <>
          <p className="mb-3 text-sm text-slate-400" aria-live="polite">{list.data.total} IPO{list.data.total === 1 ? "" : "s"} match</p>
          {list.data.items.length ? (
            <UpcomingTable ipos={list.data.items} showListing={sp.get("status") === "listed"} />
          ) : (
            <EmptyState title="No IPOs match these filters" body="Score filters exclude IPOs whose score is unavailable." action={<button className={buttonClass.secondary} onClick={() => router.replace(pathname)}>Clear filters</button>} />
          )}
          {pages > 1 && (
            <nav className="mt-4 flex items-center justify-end gap-2 text-sm" aria-label="Pagination">
              <button className={buttonClass.secondary} disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Previous</button>
              <span className="text-slate-400">Page {page} of {pages}</span>
              <button className={buttonClass.secondary} disabled={page >= pages} onClick={() => set("page", String(page + 1))}>Next</button>
            </nav>
          )}
        </>
      )}
    </>
  );
}

export default function IposPage() {
  return (
    <>
      <PageHeader
        eyebrow="IPO discovery"
        title="Indian IPOs"
        subtitle="Mainboard and SME issues stored in KcpInsights. Missing fields show as “—”; nothing is filled in. Research score = 0.45·Quality + 0.30·Valuation + 0.25·(100 − Risk)."
      />
      <Suspense fallback={<LoadingBlock rows={6} />}>
        <Filters />
      </Suspense>
    </>
  );
}
