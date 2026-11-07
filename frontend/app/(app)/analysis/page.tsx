"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import FinancialsPanel from "@/components/ipo/FinancialsPanel";
import IpoPicker from "@/components/ipo/IpoPicker";
import RatiosPanel from "@/components/ipo/RatiosPanel";
import ScoreBreakdown from "@/components/ipo/ScoreBreakdown";
import { EmptyState, ErrorState, LoadingBlock, PageHeader, Panel, Tabs, tableClass } from "@/components/kcp/ui";
import { PROFILE_LABEL, fmtMetric } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { IndustriesResponse, IpoDetail, ScoreResult } from "@/lib/types";

type View = "statements" | "ratios" | "benchmarks" | "score";
const BENCH: [string, string, string][] = [
  ["roe", "ROE", "%"], ["roce", "ROCE", "%"], ["roa", "ROA", "%"], ["net_margin", "Net margin", "%"], ["ebitda_margin", "EBITDA margin", "%"],
  ["revenue_cagr", "Revenue CAGR", "%"], ["pat_cagr", "PAT CAGR", "%"], ["current_ratio", "Current ratio", "x"], ["debt_to_equity", "Debt/Equity", "x"],
  ["interest_coverage", "Interest cover", "x"], ["ocf_to_pat", "OCF/PAT", "x"], ["receivable_days", "Receivable days", "days"], ["inventory_days", "Inventory days", "days"],
  ["pe", "P/E", "x"], ["pb", "P/B", "x"],
];

function Benchmarks({ ipoId }: { ipoId: number }) {
  const ind = useApi<IndustriesResponse>("/api/industries");
  const d = useApi<IpoDetail>(`/api/ipos/${ipoId}`);
  const r = useApi<ScoreResult>(`/api/ipos/${ipoId}/scores`);
  if (ind.error || d.error || r.error) return <ErrorState message={ind.error ?? d.error ?? r.error ?? ""} />;
  if (!ind.data || !d.data || !r.data) return <LoadingBlock rows={6} />;
  const sector = ind.data.sectors.find((s) => s.sector === d.data?.sector);
  const profile = ind.data.profiles.find((p) => p.key === (d.data?.industry_profile ?? "general"));
  return (
    <div className="space-y-6">
      <Panel title={`${d.data.company_name} vs ${d.data.sector} IPOs on record`}
             subtitle={sector ? `${sector.scored} scored IPO(s) in this sector${sector.indicative_only ? " — fewer than three, so the benchmark is indicative only" : ""}. ${ind.data.note}` : "This IPO's sector has no other scored IPOs yet."}>
        <div className={tableClass.wrap}>
          <table className={tableClass.table}>
            <thead className={tableClass.thead}><tr>
              <th className={tableClass.th}>Metric</th><th className={`${tableClass.th} text-right`}>This IPO</th><th className={`${tableClass.th} text-right`}>Sector median</th>
              <th className={`${tableClass.th} text-right`}>n</th><th className={tableClass.th}>Applicability</th>
            </tr></thead>
            <tbody>
              {BENCH.map(([k, label, unit]) => {
                const m = r.data?.metrics[k];
                const b = sector?.benchmarks[k];
                const na = profile?.not_applicable.includes(k);
                return (
                  <tr key={k} className={tableClass.tr}>
                    <td className={`${tableClass.td} text-ink`}>{label}</td>
                    <td className={`${tableClass.td} ${tableClass.num} text-ink`}>{m && m.value !== null && m.status !== "unavailable" ? fmtMetric(m.value, unit === "days" ? "" : unit) + (unit === "days" ? " d" : "") : <span className="text-ink-3">{m?.status === "not_meaningful" ? "n/m" : "—"}</span>}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{b ? fmtMetric(b.median, unit === "days" ? "" : unit) + (unit === "days" ? " d" : "") : "—"}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{b?.n ?? 0}</td>
                    <td className={`${tableClass.td} text-xs`}>{na ? <span className="text-ink-3">not applicable — {profile?.reasons[k] ?? "outside this profile"}</span> : <span className="text-ink-3">scored where weighted</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Industry analysis profiles" subtitle="Which ratios apply depends on the business model. A ratio marked not applicable is shown for reference but never scored or counted as missing.">
        <div className="grid gap-4 md:grid-cols-2">
          {ind.data.profiles.map((p) => (
            <div key={p.key} className={`rounded-lg border p-3.5 ${p.key === profile?.key ? "border-brand/60 bg-surface-2" : "border-line"}`}>
              <p className="text-sm font-medium text-ink">{p.label}{p.key === profile?.key && <span className="ml-2 text-xs text-brand-ink">this IPO</span>}</p>
              <p className="mt-1 text-xs leading-5 text-ink-3">
                {p.not_applicable.length ? `Not applicable: ${p.not_applicable.slice(0, 10).map((x) => x.replace(/_/g, " ")).join(", ")}${p.not_applicable.length > 10 ? "…" : ""}.` : "All standard ratios apply."}
                {p.not_applicable_components.length ? ` Components excluded: ${p.not_applicable_components.join(", ").replace(/_/g, " ")}.` : ""}
                {Object.keys(p.weights).length ? ` Own weights for ${Object.keys(p.weights).join(", ").replace(/_/g, " ")}.` : ""}
              </p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Workspace() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [id, setIdState] = useState<number | null>(sp.get("ipo") ? Number(sp.get("ipo")) : null);
  const [view, setView] = useState<View>((sp.get("view") as View) || "statements");
  const r = useApi<ScoreResult>(id && view === "score" ? `/api/ipos/${id}/scores` : null);
  const setId = (v: number | null) => {
    setIdState(v);
    router.replace(v ? `${pathname}?ipo=${v}` : pathname);
  };
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full max-w-md"><IpoPicker value={id} onChange={setId} /></div>
        {id && <Link href={`/ipos/${id}`} className="pb-2 text-sm text-brand-ink hover:underline">Open the full research page →</Link>}
      </div>
      {id === null ? (
        <EmptyState title="Choose an IPO to analyse" body="Balance sheet, profit and loss, cash flow, ratio trends, industry benchmarks and the score derivation for any IPO on record." />
      ) : (
        <>
          <Tabs<View> value={view} onChange={setView} tabs={[
            { id: "statements", label: "Financial statements" }, { id: "ratios", label: "Ratio analysis & trends" },
            { id: "benchmarks", label: "Industry benchmarks" }, { id: "score", label: "Score derivation" },
          ]} />
          {view === "statements" && <FinancialsPanel ipoId={id} />}
          {view === "ratios" && <RatiosPanel ipoId={id} />}
          {view === "benchmarks" && <Benchmarks ipoId={id} />}
          {view === "score" && (r.error ? <ErrorState message={r.error} onRetry={r.reload} /> : r.data ? <ScoreBreakdown r={r.data} /> : <LoadingBlock rows={8} />)}
        </>
      )}
      <p className="text-xs text-ink-3">Profiles: {Object.values(PROFILE_LABEL).join(" · ")}. Full formulas and weights: <Link href="/methodology" className="text-brand-ink hover:underline">Methodology</Link>.</p>
    </div>
  );
}

export default function AnalysisPage() {
  return (
    <>
      <PageHeader eyebrow="Research" title="Financial analysis"
                  subtitle="Restated statements from the offer document, every standard ratio across periods, the IPO against its sector on record, and how each score was derived — prospectus figure → ratio → normalised score → weighted component → Q." />
      <Suspense fallback={<LoadingBlock />}>
        <Workspace />
      </Suspense>
    </>
  );
}
