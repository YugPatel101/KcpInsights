"use client";

import { RatioTrendChart } from "@/components/charts/Charts";
import { EmptyState, ErrorState, LoadingBlock, Panel } from "@/components/kcp/ui";
import { fmtNum } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Financials, Metric } from "@/lib/types";

const GROUPS: { title: string; keys: string[]; trend?: { unit: "%" | "x"; series: { key: string; label: string }[] } }[] = [
  { title: "Profitability", keys: ["roe", "roce", "net_margin", "ebitda_margin", "operating_margin"],
    trend: { unit: "%", series: [{ key: "roe", label: "ROE" }, { key: "roce", label: "ROCE" }, { key: "net_margin", label: "Net margin" }, { key: "ebitda_margin", label: "EBITDA margin" }] } },
  { title: "Growth", keys: ["revenue_cagr", "pat_cagr", "revenue_yoy", "pat_yoy", "ebitda_growth", "eps_growth", "revenue_volatility", "growth_consistency"],
    trend: { unit: "%", series: [{ key: "revenue_yoy", label: "Revenue growth" }, { key: "pat_yoy", label: "PAT growth" }] } },
  { title: "Liquidity & leverage", keys: ["current_ratio", "quick_ratio", "cash_ratio", "debt_to_equity", "interest_coverage", "debt_to_ebitda"],
    trend: { unit: "x", series: [{ key: "current_ratio", label: "Current ratio" }, { key: "debt_to_equity", label: "Debt/Equity" }] } },
  { title: "Cash flow", keys: ["ocf_to_pat", "fcf", "fcf_margin", "cash_conversion", "cash_flow_consistency"],
    trend: { unit: "x", series: [{ key: "ocf_to_pat", label: "OCF/PAT" }] } },
  { title: "Valuation (at the issue price)", keys: ["market_cap", "eps_post_issue", "pe", "bvps_post_issue", "pb", "enterprise_value", "ev_ebitda"] },
];

function value(m: Metric): string {
  if (m.status !== "ok") return "—";
  if (m.value === null) return m.note ? "∞" : "—";
  const u = m.unit === "%" ? "%" : m.unit === "x" ? "x" : m.unit === "pp" ? " pp" : m.unit === "score" ? "" : "";
  const prefix = m.unit === "₹ cr" || m.unit === "₹" ? "₹" : "";
  const suffix = m.unit === "₹ cr" ? " cr" : "";
  return `${prefix}${fmtNum(m.value, 2)}${u}${suffix}`;
}

export default function RatiosPanel({ ipoId }: { ipoId: number }) {
  const { data, error, loading, reload } = useApi<Financials>(`/api/ipos/${ipoId}/financials`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock rows={8} />;
  if (!Object.keys(data.metrics).length) {
    return <EmptyState title="No ratios yet" body="Ratios are calculated once verified annual financial statements are stored for this company." />;
  }
  return (
    <div className="space-y-6">
      {GROUPS.map((g) => {
        const ms = g.keys.map((k) => data.metrics[k]).filter(Boolean);
        if (!ms.length) return null;
        const rows = data.ratio_history.map((r) => ({ ...r }));
        const hasTrend = g.trend && rows.length >= 2 && g.trend.series.some((s) => rows.some((r) => typeof r[s.key] === "number"));
        return (
          <Panel key={g.title} title={g.title} subtitle={`Latest annual period, ${data.basis_used ?? "—"} basis. Hover a value for its formula.`}>
            <div className={`grid gap-6 ${hasTrend ? "lg:grid-cols-2" : ""}`}>
              <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
                {ms.map((m) => (
                  <div key={m.key} className="flex items-baseline justify-between gap-3 border-b border-line py-2" title={m.formula}>
                    <dt className="min-w-0 text-sm text-ink-2">
                      {m.label}
                      {m.period && <span className="ml-1 text-[11px] text-ink-3">{m.period}</span>}
                    </dt>
                    <dd className="text-right">
                      <span className={`tabular-nums ${m.status === "ok" ? "text-ink" : "text-ink-3"}`}>{value(m)}</span>
                      {m.status !== "ok" && <div className="max-w-56 text-[11px] leading-4 text-ink-3">{m.reason}</div>}
                      {m.note && <div className="max-w-56 text-[11px] leading-4 text-warn-ink">{m.note}</div>}
                    </dd>
                  </div>
                ))}
              </dl>
              {hasTrend && g.trend && (
                <div>
                  <div className="mb-2 text-xs uppercase tracking-wider text-ink-3">Trend by fiscal year</div>
                  <RatioTrendChart rows={rows} series={g.trend.series} unit={g.trend.unit} />
                </div>
              )}
            </div>
          </Panel>
        );
      })}
      <details className="rounded-xl border border-line p-4 text-sm">
        <summary className="cursor-pointer text-ink-2">All formulas</summary>
        <dl className="mt-3 space-y-1">
          {Object.entries(data.formulas).map(([k, f]) => <div key={k} className="text-ink-2"><span className="font-mono text-xs text-ink-3">{k}</span> — {f}</div>)}
        </dl>
      </details>
    </div>
  );
}
