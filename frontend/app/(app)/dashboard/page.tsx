"use client";

import Link from "next/link";
import { Activity, CalendarClock, FileText, Landmark } from "lucide-react";
import DashboardHeader from "@/components/dashboard/DashboardHeader";
import MarketOverview from "@/components/dashboard/MarketOverview";
import SectionTitle from "@/components/dashboard/SectionTitle";
import StatCard from "@/components/dashboard/StatCard";
import UpcomingTable from "@/components/dashboard/UpcomingTable";
import Watchlist from "@/components/dashboard/Watchlist";
import { QualityRiskScatter } from "@/components/charts/Charts";
import { EmptyState, ErrorState, LoadingBlock, Notice, Panel } from "@/components/kcp/ui";
import { useAuth } from "@/lib/auth";
import { fmtCr, fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { DashboardSummary, ModelsStatus } from "@/lib/types";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  // refetch after sign-in so the user's watchlist and reports appear
  const { data, error, loading, reload } = useApi<DashboardSummary>(authLoading ? null : `/api/dashboard/summary?u=${user?.id ?? 0}`);
  const models = useApi<ModelsStatus>("/api/models/status");

  return (
    <>
      <DashboardHeader asOf={data?.as_of} />
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingBlock rows={6} />}
      {data && (
        <div className="space-y-10">
          {data.totals.ipos === 0 ? (
            <EmptyState
              title="No IPO records yet"
              body={<>Load the synthetic demo with <code className="text-slate-300">python -m app.cli seed-demo</code>, or import real research data.</>}
              action={<Link href="/import" className="text-sky-300 hover:underline">Import data</Link>}
            />
          ) : (
            <>
              {data.synthetic_share > 0 && (
                <Notice tone="synthetic">
                  {Math.round(data.synthetic_share * 100)}% of the IPOs shown are <strong>synthetic demonstration records</strong> about fictional
                  companies. They exercise the pipeline and earn no evidence credit; they are not real market data.
                </Notice>
              )}
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard title="Open now" value={String(data.totals.by_status.open ?? 0)} icon={Activity} />
                <StatCard title="Upcoming" value={String(data.totals.by_status.upcoming ?? 0)} icon={CalendarClock} />
                <StatCard title="Open + upcoming issue size" value={fmtCr(data.totals.issue_size_open_upcoming_cr, 0)} icon={Landmark} hint="Sum of stored issue sizes" />
                <StatCard title="Source documents" value={String(data.totals.documents)} icon={FileText} hint={`${data.totals.ipos} IPO records in total`} />
              </div>

              <section>
                <SectionTitle title="Open & upcoming IPOs" subtitle="Ordered by status, then opening date" href="/ipos?status=open,upcoming" />
                {data.upcoming.length ? <UpcomingTable ipos={data.upcoming} /> : <EmptyState title="No open or upcoming issues stored" />}
              </section>

              <section>
                <SectionTitle title="Recently listed" subtitle="Listings in the last 120 days. Returns compare listing open with issue price." href="/ipos?status=listed" />
                {data.recently_listed.length ? <UpcomingTable ipos={data.recently_listed} showListing /> : <EmptyState title="No recent listings stored" />}
              </section>

              <div className="grid gap-6 lg:grid-cols-5 [&>*]:min-w-0">
                <Panel className="lg:col-span-3" title="Quality vs risk" subtitle="Each dot is one IPO with both scores available. Dashed lines mark the low / high risk bands. Click to open.">
                  {data.scatter.length ? <QualityRiskScatter points={data.scatter} /> : <EmptyState title="No IPO has both scores yet" />}
                </Panel>
                <Panel className="lg:col-span-2" title="Data freshness & AI status">
                  <dl className="space-y-3 text-sm">
                    <div className="flex justify-between gap-4"><dt className="text-slate-400">Latest record update</dt><dd className="text-slate-200">{fmtDateTime(data.freshness.latest_record_update)}</dd></div>
                    <div className="flex justify-between gap-4"><dt className="text-slate-400">Stale financials</dt><dd className="text-right text-slate-200">{data.freshness.stale_financials.length ? data.freshness.stale_financials.join(", ") : "none"}</dd></div>
                    <div className="flex justify-between gap-4"><dt className="text-slate-400">Data modes</dt><dd className="text-right text-slate-200">{Object.entries(data.data_modes).filter(([, n]) => n).map(([m, n]) => `${m} ${n}`).join(" · ") || "—"}</dd></div>
                    <div className="flex justify-between gap-4"><dt className="text-slate-400">Research agent</dt><dd className="text-right text-slate-200">{models.data ? (models.data.ai.generative_available ? `local model (${models.data.ai.ollama.model})` : "deterministic engine") : "…"}</dd></div>
                    <div className="flex justify-between gap-4"><dt className="text-slate-400">Scoring config</dt><dd className="text-slate-200">v{models.data?.scoring.active_version ?? "…"}</dd></div>
                    <div className="flex justify-between gap-4"><dt className="text-slate-400">Listing model</dt><dd className="text-right text-slate-200">{models.data ? (models.data.listing_model.models.some((m) => m.dataset_kind === "real" && m.status === "evaluated") ? "evaluated model available" : "none validated") : "…"}</dd></div>
                  </dl>
                  <Link href="/settings" className="mt-4 inline-block text-sm text-sky-300 hover:underline">Model & provider details</Link>
                </Panel>
              </div>

              <MarketOverview data={data} />

              <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
                <section>
                  <SectionTitle title="Watchlist" href={user ? "/watchlist" : undefined} />
                  <Watchlist items={data.watchlist} signedIn={!!user} />
                </section>
                <section>
                  <SectionTitle title="Recent research reports" href={user ? "/reports" : undefined} />
                  {!user ? (
                    <EmptyState title="Sign in to save reports" />
                  ) : data.recent_reports.length ? (
                    <ul className="divide-y divide-white/5 rounded-2xl border border-white/10">
                      {data.recent_reports.map((r) => (
                        <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                          <Link href={`/reports/${r.id}`} className="truncate text-slate-200 hover:underline">{r.title}</Link>
                          <span className="shrink-0 text-xs text-slate-500">{fmtDateTime(r.created_at)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState title="No reports yet" body="Generate one from any IPO page or ask the AI research workspace." />
                  )}
                </section>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}
