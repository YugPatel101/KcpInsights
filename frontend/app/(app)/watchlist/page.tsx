"use client";

import Link from "next/link";
import IPOCard from "@/components/home/IPOCard";
import RequireAuth from "@/components/kcp/RequireAuth";
import { EmptyState, ErrorState, LoadingBlock, PageHeader, buttonClass } from "@/components/kcp/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { IpoSummary } from "@/lib/types";

function List() {
  const { data, error, loading, reload } = useApi<(IpoSummary & { watched_at: string })[]>("/api/watchlist");
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock />;
  if (!data.length) return <EmptyState title="Your watchlist is empty" body="Use “Watch” on an IPO research page." action={<Link href="/ipos" className="text-sky-300 hover:underline">Browse IPOs</Link>} />;
  return (
    <div className="space-y-3">
      {data.map((i) => (
        <IPOCard key={i.id} ipo={i}>
          <span className="hidden text-xs text-slate-500 md:inline">Opens {fmtDate(i.open_date)}</span>
          <button className={buttonClass.ghost} onClick={async () => { await api(`/api/ipos/${i.id}/watch`, { method: "DELETE" }); reload(); }} aria-label={`Remove ${i.company_name} from watchlist`}>Remove</button>
        </IPOCard>
      ))}
    </div>
  );
}

export default function WatchlistPage() {
  return (
    <>
      <PageHeader eyebrow="Watchlist" title="IPOs you follow" subtitle="Scores refresh automatically when underlying data changes." />
      <RequireAuth what="watchlist"><List /></RequireAuth>
    </>
  );
}
