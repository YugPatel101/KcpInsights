"use client";

import { Suspense, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import UpcomingTable from "@/components/dashboard/UpcomingTable";
import IPOCard from "@/components/home/IPOCard";
import { EmptyState, ErrorState, LoadingBlock, PageHeader, buttonClass, inputClass } from "@/components/kcp/ui";
import { PROFILE_LABEL } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { IpoSummary, Paged } from "@/lib/types";

interface Meta {
  sectors: Record<string, number>;
  industries: Record<string, number>;
  stages: Record<string, number>;
  exchanges: string[];
  statuses: Record<string, number>;
  data_modes: Record<string, number>;
  total: number;
}

const SORTS = [
  ["-open_date", "Newest first"],
  ["open_date", "Oldest first"],
  ["-composite", "Fundamental score ↓"],
  ["risk", "Risk ↑ (lowest first)"],
  ["-coverage", "Score coverage ↓"],
  ["-completeness", "Data completeness ↓"],
  ["-listing_date", "Listing date (latest)"],
  ["-issue_size", "Issue size ↓"],
  ["name", "Name A–Z"],
] as const;

function Filters() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const [moreOpen, setMoreOpen] = useState(false);
  const view = sp.get("view") === "cards" ? "cards" : "table";
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
    <label className="text-xs text-ink-2">
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
      <div className="mb-6 grid gap-3 rounded-xl border border-line bg-surface-2 p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <label className="text-xs text-ink-2 sm:col-span-2">
          <span className="mb-1 block">Search</span>
          <input className={inputClass} defaultValue={sp.get("q") ?? ""} placeholder="Company, sector, symbol" onKeyDown={(e) => { if (e.key === "Enter") set("q", (e.target as HTMLInputElement).value.trim()); }} onBlur={(e) => set("q", e.target.value.trim())} />
        </label>
        {sel("stage", "Stage", [["open,upcoming", "Open + upcoming"], ["open", "Open"], ["upcoming", "Upcoming"], ["awaiting_allotment", "Awaiting allotment"], ["awaiting_listing", "Awaiting listing"], ["listing_unconfirmed", "Listing unconfirmed"], ["listed", "Listed"], ["pipeline", "Offer document filed (no dates)"], ["withdrawn", "Withdrawn"]])}
        <button type="button" className={`${buttonClass.secondary} sm:hidden`} aria-expanded={moreOpen} onClick={() => setMoreOpen(!moreOpen)}>
          {moreOpen ? "Hide filters" : "More filters"}
        </button>
        {/* On phones the secondary filters collapse; from sm up they flow into the grid. */}
        <div className={moreOpen ? "contents" : "hidden sm:contents"}>
        {sel("issue_type", "Issue type", [["mainboard", "Mainboard"], ["sme", "SME"]])}
        {sel("sector", "Sector", sectors.map((s) => [s, s]))}
        {sel("profile", "Analysis profile", Object.entries(PROFILE_LABEL).map(([k, v]) => [k, v]))}
        {sel("min_completeness", "Data completeness", [["75", "≥ 75%"], ["50", "≥ 50%"], ["25", "≥ 25%"]])}
        {sel("min_score", "Fundamental score", [["80", "≥ 80 strong"], ["65", "≥ 65"], ["50", "≥ 50"], ["35", "≥ 35"]])}
        {sel("max_score", "Score at most", [["64", "≤ 64"], ["49", "≤ 49"], ["34", "≤ 34"]])}
        {sel("risk_level", "Risk level", [["low", "Low"], ["moderate", "Moderate"], ["elevated", "Elevated"], ["high", "High"]])}
        {sel("max_risk", "Risk score at most", [["30", "≤ 30"], ["50", "≤ 50"], ["70", "≤ 70"]])}
        {sel("min_issue_size", "Min issue size", [["50", "≥ ₹50 cr"], ["100", "≥ ₹100 cr"], ["500", "≥ ₹500 cr"], ["1000", "≥ ₹1,000 cr"]])}
        {sel("max_issue_size", "Max issue size", [["50", "≤ ₹50 cr"], ["100", "≤ ₹100 cr"], ["500", "≤ ₹500 cr"]])}
        <label className="text-xs text-ink-2"><span className="mb-1 block">Opens from</span>
          <input type="date" className={inputClass} value={sp.get("opening_from") ?? ""} onChange={(e) => set("opening_from", e.target.value)} /></label>
        <label className="text-xs text-ink-2"><span className="mb-1 block">Opens to</span>
          <input type="date" className={inputClass} value={sp.get("opening_to") ?? ""} onChange={(e) => set("opening_to", e.target.value)} /></label>
        {sel("data_mode", "Data mode", [["source", "Exchange data"], ["imported", "Imported"], ["demo", "Demo (synthetic)"]])}
        <label className="flex items-end gap-2 pb-2 text-xs text-ink-2">
          <input type="checkbox" checked={sp.get("scored_only") === "true"} onChange={(e) => set("scored_only", e.target.checked ? "true" : null)} /> Scored only
        </label>
        </div>
        <label className="text-xs text-ink-2">
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
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-ink-2" aria-live="polite">{list.data.total} IPO{list.data.total === 1 ? "" : "s"} match</p>
            <div className="flex gap-1" role="group" aria-label="View">
              {(["table", "cards"] as const).map((v) => (
                <button key={v} className={view === v ? buttonClass.primary : buttonClass.secondary} onClick={() => set("view", v === "table" ? null : v)}>{v === "table" ? "Table" : "Cards"}</button>
              ))}
            </div>
          </div>
          {list.data.items.length ? (
            view === "cards" ? (
              <div className="grid gap-3 lg:grid-cols-2">{list.data.items.map((i) => <IPOCard key={i.id} ipo={i} />)}</div>
            ) : (
              <UpcomingTable ipos={list.data.items} showListing={sp.get("stage") === "listed"} />
            )
          ) : (
            <EmptyState title="No IPOs match these filters" body="Score filters exclude IPOs whose score is unavailable." action={<button className={buttonClass.secondary} onClick={() => router.replace(pathname)}>Clear filters</button>} />
          )}
          {pages > 1 && (
            <nav className="mt-4 flex items-center justify-end gap-2 text-sm" aria-label="Pagination">
              <button className={buttonClass.secondary} disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Previous</button>
              <span className="text-ink-2">Page {page} of {pages}</span>
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
        subtitle="Mainboard and SME issues discovered automatically from NSE, plus companies whose offer documents SEBI has published. Missing fields show as “—” and are never filled in. The data column is completeness (how much expected information is on record), not confidence."
      />
      <Suspense fallback={<LoadingBlock rows={6} />}>
        <Filters />
      </Suspense>
    </>
  );
}
