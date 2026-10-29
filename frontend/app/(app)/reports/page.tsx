"use client";

import Link from "next/link";
import RequireAuth from "@/components/kcp/RequireAuth";
import { DataStatusBadge, EmptyState, ErrorState, LoadingBlock, PageHeader, RiskBadge, ScoreValue, buttonClass } from "@/components/kcp/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Paged, ReportListItem } from "@/lib/types";

function ReportList() {
  const { data, error, loading, reload } = useApi<Paged<ReportListItem>>("/api/reports?page_size=100");
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock />;
  if (!data.items.length) return <EmptyState title="No reports yet" body="Generate a report from any IPO research page, or ask the AI workspace to “generate a research report”." action={<Link className="text-sky-300 hover:underline" href="/ipos">Browse IPOs</Link>} />;
  return (
    <div className="relative overflow-x-auto rounded-2xl border border-white/10">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="bg-white/[0.03] text-left text-xs uppercase tracking-wider text-slate-500">
          <tr><th className="px-4 py-3">Report</th><th className="px-3 py-3">Score</th><th className="px-3 py-3">Risk</th><th className="px-3 py-3">Generator</th><th className="px-3 py-3">Created</th><th className="px-4 py-3"><span className="sr-only">Actions</span></th></tr>
        </thead>
        <tbody>
          {data.items.map((r) => (
            <tr key={r.id} className="border-t border-white/5">
              <td className="px-4 py-3"><Link href={`/reports/${r.id}`} className="font-medium text-white hover:underline">{r.title}</Link>{r.synthetic && <span className="ml-2"><DataStatusBadge status="synthetic" compact /></span>}</td>
              <td className="px-3"><ScoreValue value={r.scores?.composite} /></td>
              <td className="px-3"><RiskBadge level={r.scores?.risk_level ?? null} /></td>
              <td className="px-3 text-slate-400">{r.generator} · v{r.config_version}</td>
              <td className="px-3 text-slate-400">{fmtDateTime(r.created_at)}</td>
              <td className="px-4 text-right">
                <button className={buttonClass.ghost} onClick={async () => { if (confirm("Delete this report?")) { await api(`/api/reports/${r.id}`, { method: "DELETE" }); reload(); } }}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ReportsPage() {
  return (
    <>
      <PageHeader eyebrow="Library" title="Research reports" subtitle="Saved, versioned reports. Each one records the scoring configuration and generator used." />
      <RequireAuth what="reports"><ReportList /></RequireAuth>
    </>
  );
}
