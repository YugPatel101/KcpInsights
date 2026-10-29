"use client";

import { FinancialBarsChart, MarginChart } from "@/components/charts/Charts";
import { DataStatusBadge, EmptyState, ErrorState, LoadingBlock, Panel } from "@/components/kcp/ui";
import { fmtMetric, fmtNum } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { FinField, Financials } from "@/lib/types";

const ROWS: [FinField, string][] = [
  ["revenue", "Revenue"],
  ["ebitda", "EBITDA"],
  ["ebit", "EBIT"],
  ["pat", "Profit after tax"],
  ["operating_cash_flow", "Operating cash flow"],
  ["capex", "Capital expenditure"],
  ["interest_expense", "Interest expense"],
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["total_debt", "Total debt"],
  ["cash_and_equivalents", "Cash & equivalents"],
  ["total_equity", "Total equity"],
  ["current_assets", "Current assets"],
  ["current_liabilities", "Current liabilities"],
];

const DERIVED: [string, string, string][] = [
  ["ebitda_margin_pct", "EBITDA margin", "%"],
  ["pat_margin_pct", "PAT margin", "%"],
  ["debt_to_equity", "Debt / equity", "x"],
  ["current_ratio", "Current ratio", "x"],
  ["working_capital_cr", "Working capital (₹ cr)", ""],
  ["free_cash_flow_cr", "Free cash flow (₹ cr)", ""],
  ["ocf_to_pat", "OCF / PAT", "x"],
];

export default function FinancialsPanel({ ipoId }: { ipoId: number }) {
  const { data, error, loading, reload } = useApi<Financials>(`/api/ipos/${ipoId}/financials`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock rows={5} />;
  if (!data.statements.length) {
    return <EmptyState title="No financial statements stored" body="Import restated financials from the offer document on the Import page." />;
  }
  const st = data.statements;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Revenue, EBITDA and PAT" subtitle="INR crore per reporting period">
          <FinancialBarsChart statements={st} />
        </Panel>
        <Panel title="Margins" subtitle="Derived from the same statements (separate chart, no second axis)">
          <MarginChart statements={st} />
        </Panel>
      </div>

      <Panel title="Financial statements" subtitle={data.note}>
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
                <th scope="col" className="py-2 pr-4">₹ crore</th>
                {st.map((s) => (
                  <th key={s.id} scope="col" className="py-2 pr-4 text-right">
                    <div>{s.period_label}</div>
                    <div className="font-normal normal-case text-slate-600">{s.period_months}m · {s.period_end}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([k, label]) => (
                <tr key={k} className="border-t border-white/5">
                  <th scope="row" className="py-1.5 pr-4 text-left font-normal text-slate-300">{label}</th>
                  {st.map((s) => (
                    <td key={s.id} className={`py-1.5 pr-4 text-right tabular-nums ${s[k] === null ? "text-slate-600" : "text-slate-200"}`}>{fmtNum(s[k], 1)}</td>
                  ))}
                </tr>
              ))}
              <tr><td colSpan={st.length + 1} className="pt-4 text-xs uppercase tracking-wider text-slate-500">Derived</td></tr>
              {DERIVED.map(([k, label, unit]) => (
                <tr key={k} className="border-t border-white/5">
                  <th scope="row" className="py-1.5 pr-4 text-left font-normal text-slate-400">{label}</th>
                  {st.map((s) => (
                    <td key={s.id} className="py-1.5 pr-4 text-right tabular-nums text-slate-300">{unit ? fmtMetric(s.derived[k], unit) : fmtNum(s.derived[k], 1)}</td>
                  ))}
                </tr>
              ))}
              <tr className="border-t border-white/5">
                <th scope="row" className="py-2 pr-4 text-left font-normal text-slate-400">Source / status</th>
                {st.map((s) => (
                  <td key={s.id} className="py-2 pr-4 text-right">
                    <DataStatusBadge status={s.data_status} compact />
                    {s.source && <div className="mt-1 truncate text-[11px] text-slate-500" title={s.source.title}>{s.source.url ? <a className="hover:underline" href={s.source.url} target="_blank" rel="noopener noreferrer">{s.source.title}</a> : s.source.title}</div>}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Multi-year metrics" subtitle="Deterministic ratios used by the quality score">
        <div className="grid gap-x-8 sm:grid-cols-2">
          {Object.values(data.metrics).map((m) => (
            <div key={m.key} className="flex items-start justify-between gap-4 border-b border-white/5 py-2 text-sm">
              <div>
                <div className="text-slate-200">{m.label}</div>
                <div className="font-mono text-[11px] text-slate-500">{m.formula}</div>
                {m.reason && <div className="text-xs text-amber-300/90">{m.reason}</div>}
              </div>
              <div className="shrink-0 tabular-nums text-slate-100">{fmtMetric(m.value, m.unit)}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
