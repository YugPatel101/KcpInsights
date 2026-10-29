"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import IpoPicker from "@/components/ipo/IpoPicker";
import ScoreBreakdown from "@/components/ipo/ScoreBreakdown";
import { ErrorState, LoadingBlock, PageHeader, Panel } from "@/components/kcp/ui";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { ScoreResult } from "@/lib/types";

interface ConfigResp {
  version: string;
  description: string;
  config: {
    composite: { weights: Record<string, number> };
    quality: { weights: Record<string, number>; components: Record<string, Record<string, Record<string, number | string>>>; min_submetric_weight_coverage: number };
    valuation: { low_percentile: number; high_percentile: number; min_peers: number; peer_max_age_days: number; multiple_preference: Record<string, string[]> };
    risk: { weights: Record<string, number>; levels: { low_below: number; high_at_or_above: number } };
    evidence: { status_weights: Record<string, number>; inputs: Record<string, number>; financials_max_age_months: number };
  };
  created_at: string;
}

function Methodology() {
  const { data, error } = useApi<ConfigResp>("/api/scoring/config");
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingBlock />;
  const c = data.config;
  const w = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ");
  return (
    <Panel title={`Methodology — configuration v${data.version}`} subtitle={data.description}>
      <div className="grid gap-6 text-sm leading-6 text-slate-300 lg:grid-cols-2">
        <div className="space-y-3">
          <p><strong className="text-white">Normalisation.</strong> Each metric x maps to N(x) = 100·clip(z, 0, 1). Higher-is-better: z = (x − a)/(b − a). Lower-is-better: z = (b − x)/(b − a). Target-range metrics score 100 inside the range and decay linearly outside. Thresholds a, b are listed per metric in the breakdown.</p>
          <p><strong className="text-white">Composite.</strong> S = 0.45·Q + 0.30·V + 0.25·(100 − R) (weights: {w(c.composite.weights)}). If any component is unavailable, S is not calculated — it is never re-normalised.</p>
          <p><strong className="text-white">Quality.</strong> {w(c.quality.weights)}. Inside a component, available sub-metrics are re-weighted only when they carry ≥ {c.quality.min_submetric_weight_coverage * 100}% of the component weight.</p>
          <p><strong className="text-white">Valuation.</strong> IPO multiple at the upper price band (or final price) on post-issue diluted shares, versus peers&apos; p{c.valuation.low_percentile}–p{c.valuation.high_percentile}. Needs ≥ {c.valuation.min_peers} peers with snapshots within {c.valuation.peer_max_age_days} days. Multiple preference: {Object.entries(c.valuation.multiple_preference).map(([g, l]) => `${g}: ${l.join(" → ")}`).join("; ")}. P/E is never computed on zero or negative earnings.</p>
        </div>
        <div className="space-y-3">
          <p><strong className="text-white">Risk.</strong> {w(c.risk.weights)}. Level: low &lt; {c.risk.levels.low_below} ≤ moderate &lt; {c.risk.levels.high_at_or_above} ≤ high. Each metric feeds exactly one risk component. Unreviewed disclosures are left out rather than penalised.</p>
          <p><strong className="text-white">Evidence coverage.</strong> C = 100·ΣwᵢIᵢ / Σwᵢ with status credits {w(c.evidence.status_weights)}; financials older than {c.evidence.financials_max_age_months} months earn no credit. Coverage measures completeness of admissible evidence — it is not the probability that a score is right.</p>
          <p><strong className="text-white">What the score is not.</strong> The weights are educational defaults, not fitted coefficients. The research score is not a probability of listing gains, not a price target and not advice.</p>
          <p className="text-xs text-slate-500">Active since {fmtDateTime(data.created_at)}. Administrators can publish a new immutable version via the API (POST /api/scoring/configs).</p>
        </div>
      </div>
    </Panel>
  );
}

function Analysis() {
  const sp = useSearchParams();
  const [id, setId] = useState<number | null>(sp.get("ipo") ? Number(sp.get("ipo")) : null);
  const r = useApi<ScoreResult>(id ? `/api/ipos/${id}/scores` : null);
  return (
    <div className="space-y-8">
      <div className="max-w-md"><IpoPicker value={id} onChange={setId} /></div>
      {id === null ? null : r.error ? <ErrorState message={r.error} onRetry={r.reload} /> : r.data ? <ScoreBreakdown r={r.data} /> : <LoadingBlock rows={8} />}
      <Methodology />
    </div>
  );
}

export default function AnalysisPage() {
  return (
    <>
      <PageHeader eyebrow="Quantitative analysis" title="Score breakdown & methodology" subtitle="Every score below can be traced from raw input → metric → normalised score → weighted component. Expand any component to see the formula, thresholds and data periods." />
      <Suspense fallback={<LoadingBlock />}>
        <Analysis />
      </Suspense>
    </>
  );
}
