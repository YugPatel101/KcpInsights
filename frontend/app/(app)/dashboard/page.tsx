"use client";

import Link from "next/link";
import { Activity, CalendarClock, FileCheck2, FileSearch, Hourglass, Landmark, Rocket } from "lucide-react";
import DashboardHeader from "@/components/dashboard/DashboardHeader";
import StatCard from "@/components/dashboard/StatCard";
import UpcomingTable from "@/components/dashboard/UpcomingTable";
import Watchlist from "@/components/dashboard/Watchlist";
import { ActivityChart, CountBarChart, ListingReturnsChart, SERIES, ScoreRiskScatter } from "@/components/charts/Charts";
import LiveDataBar from "@/components/live/LiveDataBar";
import { EmptyState, ErrorState, LoadingBlock, Notice, Panel, Tabs } from "@/components/kcp/ui";
import { useAuth } from "@/lib/auth";
import { fmtCr, fmtDate, fmtDateTime, fmtPct, titleCase } from "@/lib/format";
import { timeAgo } from "@/lib/time";
import { useApi } from "@/lib/useApi";
import type { DashboardSummary } from "@/lib/types";
import { useState } from "react";

const EVENT_LABEL = { opens: "Opens", closes: "Closes", lists: "Lists" } as const;
type Board = "live" | "awaiting" | "closed" | "listed" | "pipeline";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  // reads the database every 2 minutes while the tab is visible; never triggers upstream fetches
  const { data, error, loading, reload } = useApi<DashboardSummary>(authLoading ? null : `/api/dashboard/summary?u=${user?.id ?? 0}`, { refreshMs: 120_000 });
  const [board, setBoard] = useState<Board>("live");

  return (
    <>
      <DashboardHeader asOf={data?.as_of} />
      <LiveDataBar />
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingBlock rows={6} />}
      {data && (
        <div className="space-y-6">
          {data.totals.ipos === 0 ? (
            <EmptyState title="No IPO records yet" body="The first data sync runs about a minute after the API starts. Check System health for progress."
                        action={<Link href="/data" className="text-brand-ink hover:underline">System health</Link>} />
          ) : (
            <>
              {data.demo_included && data.synthetic_share > 0 && (
                <Notice tone="synthetic">
                  {Math.round(data.synthetic_share * 100)}% of the IPOs shown are <strong>synthetic demonstration records</strong> about fictional companies.
                </Notice>
              )}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
                <StatCard title="Open now" value={String(data.totals.by_status.open ?? 0)} icon={Activity} />
                <StatCard title="Upcoming" value={String(data.totals.by_status.upcoming ?? 0)} icon={CalendarClock} />
                <StatCard title="Awaiting allotment" value={String(data.totals.by_stage.awaiting_allotment ?? 0)} icon={Hourglass} />
                <StatCard title="Awaiting listing" value={String(data.totals.by_stage.awaiting_listing ?? 0)} icon={Rocket}
                          hint={data.totals.by_stage.listing_unconfirmed ? `${data.totals.by_stage.listing_unconfirmed} unconfirmed` : undefined} />
                <StatCard title="Listed (30 days)" value={String(data.totals.recently_listed_30d)} icon={Landmark} />
                <StatCard title="Offer documents filed" value={String(data.totals.pipeline ?? 0)} icon={FileSearch} hint="SEBI DRHP/RHP, no dates yet" />
                <StatCard title="Financials extracted" value={`${data.totals.documents_extracted}/${data.totals.documents}`} icon={FileCheck2} hint={`${data.totals.scored} IPOs scored`} />
              </div>

              <div className="grid gap-6 xl:grid-cols-3 [&>*]:min-w-0">
                <section className="xl:col-span-2">
                  <Tabs<Board>
                    value={board}
                    onChange={setBoard}
                    tabs={[
                      { id: "live", label: `Open & upcoming (${data.upcoming.length})` },
                      { id: "awaiting", label: `Awaiting allotment / listing (${data.awaiting.length})` },
                      { id: "closed", label: `Recently closed (${data.recently_closed?.length ?? 0})` },
                      { id: "listed", label: `Recently listed (${data.recently_listed.length})` },
                      { id: "pipeline", label: `Filed with SEBI (${data.pipeline?.length ?? 0})` },
                    ]}
                  />
                  {board === "live" && (data.upcoming.length ? <UpcomingTable ipos={data.upcoming} /> : <EmptyState title="No open or upcoming issues" />)}
                  {board === "awaiting" && (data.awaiting.length ? <UpcomingTable ipos={data.awaiting} dateField="listing_date" />
                    : <EmptyState title="No issues awaiting allotment or listing" />)}
                  {board === "closed" && (data.recently_closed?.length ? <UpcomingTable ipos={data.recently_closed} dateField="close_date" />
                    : <EmptyState title="No issues closed in the last 14 days" />)}
                  {board === "listed" && (data.recently_listed.length ? <UpcomingTable ipos={data.recently_listed} showListing />
                    : <EmptyState title="No listings in the last 30 days" />)}
                  {board === "pipeline" && (data.pipeline?.length ? <UpcomingTable ipos={data.pipeline} />
                    : <EmptyState title="No offer documents waiting for dates" body="Companies appear here when SEBI publishes their DRHP or RHP before NSE announces the issue." />)}
                  <p className="mt-2 text-xs text-ink-3">
                    Allotment and listing dates are estimated (SEBI T+3) until NSE confirms them. <Link href="/ipos" className="text-brand-ink hover:underline">All IPOs →</Link>
                  </p>
                </section>
                <Panel title="Next 3 weeks" subtitle="Openings, closings and listings" action={<Link href="/calendar" className="text-xs font-medium text-brand-ink hover:underline">Calendar →</Link>}>
                  {data.calendar.length ? (
                    <ol className="divide-y divide-line text-sm">
                      {data.calendar.slice(0, 12).map((e) => (
                        <li key={`${e.date}-${e.event}-${e.ipo_id}`} className="flex items-start gap-3 py-2">
                          <span className="w-14 shrink-0 tabular-nums text-xs text-ink-3">{fmtDate(e.date).replace(/ \d{4}$/, "")}</span>
                          <span className="min-w-0 flex-1">
                            <Link href={`/ipos/${e.ipo_id}`} className="text-ink hover:text-brand-ink">{e.company_name}</Link>
                            <span className="ml-1.5 text-xs text-ink-3">{EVENT_LABEL[e.event]}{e.estimated ? " (expected)" : ""}</span>
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : <EmptyState title="Nothing scheduled" />}
                </Panel>
              </div>

              <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
                <Panel title="Market activity" subtitle="IPO openings per month, mainboard and SME (stored records)">
                  <ActivityChart data={data.activity} />
                </Panel>
                <Panel title="Recent listings" subtitle="Listing gain: listing-day open vs final issue price, last 30 days (NSE bhavcopy)"
                       action={<Link href="/history" className="text-xs font-medium text-brand-ink hover:underline">History →</Link>}>
                  {data.recently_listed.some((r) => r.listing_return_pct !== null) ? (
                    <ListingReturnsChart items={data.recently_listed.filter((r) => r.listing_return_pct !== null).map((r) => ({ name: r.company_name, ret: r.listing_return_pct as number, date: fmtDate(r.listing_date) }))} />
                  ) : <EmptyState title="No verified listing prices in the last 30 days" />}
                </Panel>
              </div>

              <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
                <Panel title="Sectors" subtitle="Classified from each offer document; 'Unclassified' until one is read">
                  <CountBarChart data={data.sectors.slice(0, 8).map((s) => ({ sector: s.sector, count: s.count }))} labelKey="sector" valueKey="count" label="IPOs" color={SERIES[2]} />
                </Panel>
                <Panel title="Fundamental score distribution" subtitle={`${data.totals.scored} IPOs with an overall score`}>
                  <CountBarChart data={data.score_distribution} labelKey="label" valueKey="count" label="IPOs" />
                </Panel>
                <Panel title="Risk distribution" subtitle="Risk levels of scored IPOs">
                  <CountBarChart data={data.risk_distribution.map((r) => ({ ...r, level: titleCase(r.level) }))} labelKey="level" valueKey="count" label="IPOs" color={SERIES[1]} height={180} />
                </Panel>
              </div>

              <div className="grid gap-6 lg:grid-cols-5 [&>*]:min-w-0">
                <Panel className="lg:col-span-3" title="Score vs risk" subtitle="Each dot is one IPO with both scores. Click to open.">
                  {data.scatter.length ? <ScoreRiskScatter points={data.scatter} /> : <EmptyState title="No IPO has both scores yet" />}
                </Panel>
                <Panel className="lg:col-span-2" title="Data health" subtitle="How complete the stored records are — not a confidence level"
                       action={<Link href="/data" className="text-xs font-medium text-brand-ink hover:underline">System health →</Link>}>
                  {data.data_health ? (
                    <>
                      <div className="grid grid-cols-3 gap-2 text-center">
                        {(["ready", "partial", "insufficient"] as const).map((k) => (
                          <div key={k} className="rounded-md border border-line bg-surface-2 px-2 py-2.5">
                            <div className="text-lg font-semibold tabular-nums text-ink">{data.data_health?.readiness[k] ?? 0}</div>
                            <div className="text-[11px] text-ink-3">{k === "ready" ? "Analysis ready" : k === "partial" ? "Partially ready" : "Insufficient data"}</div>
                          </div>
                        ))}
                      </div>
                      <div className="mt-4">
                        <CountBarChart data={data.data_health.distribution} labelKey="bucket" valueKey="count" label="IPOs by completeness" color={SERIES[0]} height={150} />
                      </div>
                      <p className="mt-2 text-xs text-ink-3">Median completeness {fmtPct(data.data_health.median_completeness, 0)} across {data.totals.ipos} IPOs.</p>
                    </>
                  ) : <EmptyState title="Completeness not computed yet" />}
                  <h3 className="mb-2 mt-5 text-[11px] font-medium uppercase tracking-wider text-ink-3">Sources</h3>
                  <ul className="space-y-1.5 text-sm">
                    {data.sources.map((s) => (
                      <li key={s.key} className="flex items-start justify-between gap-3">
                        <span className="min-w-0 truncate text-ink-2" title={s.name}>{s.name}</span>
                        <span className={`shrink-0 text-xs ${s.health_status === "healthy" ? "text-pos-ink" : s.health_status === "manual" ? "text-ink-3" : "text-warn-ink"}`}>
                          {s.health_status}{s.last_success_at ? ` · ${timeAgo(s.last_success_at)}` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs text-ink-3">Last successful sync {fmtDateTime(data.freshness.last_successful_sync_at)} ({data.freshness.last_successful_job ?? "—"}).</p>
                </Panel>
              </div>

              <Panel title="Recently updated" subtitle="Field changes detected by the scheduler (old → new); every change is kept as history">
                {data.recent_changes.length ? (
                  <ul className="divide-y divide-line text-sm">
                    {data.recent_changes.map((c, i) => (
                      <li key={i} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                        <span className="min-w-0"><Link href={`/ipos/${c.ipo_id}`} className="text-ink hover:text-brand-ink">{c.company_name}</Link> <span className="text-ink-3">· {c.field.replace(/_/g, " ")}</span></span>
                        <span className="text-xs text-ink-3">{String(c.old_value ?? "—")} → <span className="text-ink">{String(c.new_value ?? "—")}</span> · {timeAgo(c.changed_at)}</span>
                      </li>
                    ))}
                  </ul>
                ) : <EmptyState title="No changes recorded yet" />}
              </Panel>

              {user && (
                <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
                  <Panel title="Watchlist"><Watchlist items={data.watchlist} signedIn /></Panel>
                  <Panel title="Recent reports">
                    {data.recent_reports.length ? (
                      <ul className="space-y-2 text-sm">{data.recent_reports.map((r) => <li key={r.id}><Link href={`/reports/${r.id}`} className="text-brand-ink hover:underline">{r.title}</Link> <span className="text-xs text-ink-3">{fmtDateTime(r.created_at)}</span></li>)}</ul>
                    ) : <EmptyState title="No reports yet" body="Generate one from any IPO page." />}
                  </Panel>
                </div>
              )}
              <p className="text-xs text-ink-3">Open + upcoming issue size: {fmtCr(data.totals.issue_size_open_upcoming_cr, 0)} (sum of stored sizes; estimates included).</p>
            </>
          )}
        </div>
      )}
    </>
  );
}
