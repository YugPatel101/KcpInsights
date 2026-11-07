"use client";

import { ErrorState, LoadingBlock, PageHeader, Panel, tableClass } from "@/components/kcp/ui";
import { fmtDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { FieldRegistry, MethodologyResponse } from "@/lib/types";

type Range = Record<string, number | string>;
const label = (k: string) => titleCase(k).replace("Pct", "%").replace("Pp", "pp");
const rng = (r: Range) =>
  r.kind === "linear" ? `0 at ${r.zero} → 100 at ${r.full}` : `100 within ${r.lo}–${r.hi}; 0 at ${r.zero_low} and ${r.zero_high}`;

const RATIO_GROUPS: [string, string[]][] = [
  ["Profitability", ["roe", "roce", "roa", "net_margin", "ebitda_margin", "operating_margin", "gross_margin"]],
  ["Growth", ["revenue_cagr", "pat_cagr", "ebitda_cagr", "eps_cagr", "revenue_yoy", "pat_yoy", "ebitda_growth", "eps_growth", "revenue_volatility", "growth_consistency"]],
  ["Liquidity & leverage", ["current_ratio", "quick_ratio", "cash_ratio", "debt_to_equity", "debt_to_assets", "interest_coverage", "debt_to_ebitda"]],
  ["Efficiency", ["receivable_days", "inventory_days", "capex_intensity"]],
  ["Cash flow", ["ocf_to_pat", "fcf", "fcf_margin", "cash_conversion", "cash_flow_consistency"]],
  ["Valuation", ["eps_post_issue", "bvps_post_issue", "market_cap", "enterprise_value", "pe", "pb", "ev_ebitda", "price_to_sales"]],
];

export default function MethodologyPage() {
  const { data, error, reload } = useApi<MethodologyResponse>("/api/methodology");
  const reg = useApi<FieldRegistry>("/api/fields");
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <LoadingBlock rows={10} />;
  const c = data.config;
  const comps = ["profitability", "growth", "financial_health", "cash_flow", "valuation"];
  return (
    <>
      <PageHeader eyebrow="Reference" title="Methodology"
                  subtitle={<>Everything below is read from the active scoring configuration <strong className="text-ink">v{data.active_version}</strong> and the engine&apos;s formula table, so this page cannot drift from the code. {data.description}</>} />
      <div className="space-y-6">
        <Panel title="1. Fundamental score Q" subtitle="Weighted average of five component scores (0–100, higher = stronger characteristics)">
          <p className="rounded-md border border-line bg-canvas px-4 py-3 font-mono text-[13px] text-ink">{data.formulas.Q}</p>
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            {comps.map((k) => (
              <div key={k} className="rounded-lg border border-line bg-surface-2 p-3">
                <p className="text-xs text-ink-3">{data.component_labels[k]}</p>
                <p className="text-xl font-semibold tabular-nums text-ink">{c.weights.overall[k]?.toFixed(2)}</p>
                <ul className="mt-2 space-y-0.5 text-xs text-ink-2">
                  {Object.entries(c.weights[k] ?? {}).map(([m, w]) => <li key={m} className="flex justify-between gap-2"><span>{label(m)}</span><span className="tabular-nums">{w.toFixed(2)}</span></li>)}
                </ul>
              </div>
            ))}
          </div>
          <ul className="mt-4 space-y-1.5 text-sm leading-6 text-ink-2">
            <li>• Inside a component, weights are rescaled over the inputs that are available, but only if they carry at least {Math.round(c.coverage.component_min * 100)}% of the component&apos;s weight.</li>
            <li>• Q is issued only if {c.coverage.required_components.map((x) => data.component_labels[x]).join(", ")} are available, at least {Math.round(c.coverage.overall_min * 100)}% of the overall weight is computable and at least {c.coverage.min_annual_periods} annual periods exist. Otherwise the score is shown as incomplete with the reason.</li>
            <li>• Statement periods are used only with status {c.usable_statuses.join(", ")}; figures that failed accounting checks or were read by OCR are shown but never scored.</li>
            <li>• Weights are judgemental educational defaults — not fitted or validated predictors of listing gains or returns.</li>
          </ul>
        </Panel>

        <Panel title="2. Normalisation (metric → 0–100)" subtitle="linear: S = 100·clip((x − zero)/(full − zero), 0, 1); band: 100 inside [lo, hi], falling to 0 at the outer bounds">
          <div className={tableClass.wrap}>
            <table className={tableClass.table}>
              <thead className={tableClass.thead}><tr><th className={tableClass.th}>Input</th><th className={tableClass.th}>Range</th><th className={tableClass.th}>Kind</th></tr></thead>
              <tbody>{Object.entries(c.ranges).map(([k, r]) => (
                <tr key={k} className={tableClass.tr}><td className={`${tableClass.td} text-ink`}>{label(k)}</td><td className={`${tableClass.td} tabular-nums`}>{rng(r)}</td><td className={tableClass.td}>{String(r.kind)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-ink-3">Valuation multiples are scored on their premium to the listed-peer median when at least {c.peers.min_peers} peers have a valid multiple (relative premium range), otherwise on the absolute ranges.</p>
        </Panel>

        <Panel title="3. Risk score (0–100, higher = more risk)" subtitle="Weighted average of the available components; a component without data is excluded, never treated as evidence of a problem">
          <div className="grid gap-6 lg:grid-cols-2">
            <ul className="space-y-1 text-sm">
              {Object.entries(c.weights.risk).map(([k, w]) => <li key={k} className="flex justify-between gap-3 border-b border-line py-1.5"><span className="text-ink-2">{label(k)}</span><span className="tabular-nums text-ink">{w.toFixed(2)}</span></li>)}
            </ul>
            <div>
              <ul className="space-y-0.5 text-xs text-ink-2">{Object.entries(c.risk_ranges).map(([k, r]) => <li key={k}>{label(k)}: {rng(r)}</li>)}</ul>
              <p className="mt-3 text-sm text-ink-2">Levels: {c.risk_levels.map(([b, l]) => `${l} ≥ ${b}`).join(" · ")}. Governance &amp; disclosure risk is reported as its own sub-score from the disclosure-based components.</p>
            </div>
          </div>
        </Panel>

        <Panel title="4. Industry profiles (metric applicability)" subtitle="The sector read from the offer document selects a profile; ratios that do not fit the business model are not applicable — not penalised">
          <div className={tableClass.wrap}>
            <table className={tableClass.table}>
              <thead className={tableClass.thead}><tr><th className={tableClass.th}>Profile</th><th className={tableClass.th}>Not applicable</th><th className={tableClass.th}>Own weights / ranges</th></tr></thead>
              <tbody>{Object.entries(c.profiles).map(([k, p]) => (
                <tr key={k} className={`${tableClass.tr} align-top`}>
                  <td className={`${tableClass.td} text-ink`}>{p.label}</td>
                  <td className={`${tableClass.td} text-xs leading-5`}>{p.not_applicable.length ? p.not_applicable.map(label).join(", ") : "—"}{p.not_applicable_components?.length ? ` · component: ${p.not_applicable_components.map(label).join(", ")}` : ""}</td>
                  <td className={`${tableClass.td} text-xs leading-5`}>{Object.entries(p.weights ?? {}).map(([g, ws]) => `${label(g)}: ${Object.entries(ws).map(([m, w]) => `${label(m)} ${w}`).join(", ")}`).join("; ") || "—"}
                    {Object.keys(p.ranges ?? {}).length ? ` · ranges: ${Object.entries(p.ranges).map(([m, r]) => `${label(m)} ${rng(r as Range)}`).join("; ")}` : ""}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-ink-3">Lender asset-quality and capital ratios (GNPA, NNPA, CRAR) are printed in KPI tables that cannot be reconciled against the statements, so they are displayed as reported but not scored; a lender&apos;s Q therefore stays incomplete rather than being computed on the wrong ratios.</p>
        </Panel>

        <Panel title="5. Formulas" subtitle="Single source: the quant engine. Annual (12-month) periods of one reporting basis; zero or negative denominators give 'not meaningful', never a forced number">
          <div className="grid gap-6 lg:grid-cols-2">
            {RATIO_GROUPS.map(([g, keys]) => (
              <div key={g}>
                <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-ink-3">{g}</h3>
                <ul className="space-y-1.5 text-sm leading-6 text-ink-2">{keys.filter((k) => data.formulas[k]).map((k) => <li key={k}>{data.formulas[k]}</li>)}</ul>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="6. Classes, completeness and limits">
          <ul className="space-y-1.5 text-sm leading-6 text-ink-2">
            <li>• Classes (descriptive only): {c.classification.map(([b, l]) => `${b}+ ${l.toLowerCase()}`).join("; ")}.</li>
            <li>• Data completeness = share of the expected fields on record (estimated or unverified fields count half). It is reported separately and is not a confidence level.</li>
            <li>• Listing gain = (listing-day open − final issue price) ÷ final issue price × 100; closing return uses the listing-day close. Score-versus-outcome analysis uses only scores whose inputs predate the listing.</li>
            <li>• Offer-document extraction: parser v{data.parser_version}. Periods must have month-end dates in a plausible order; balance sheets must balance and PAT must equal PBT − tax.</li>
          </ul>
          <p className="mt-4 text-xs leading-5 text-ink-3">{data.disclaimer}</p>
        </Panel>

        <Panel title="7. Field registry" subtitle="Primary and fallback source, normalisation, validation, refresh and staleness for every field the completeness check looks for">
          {reg.data ? (
            <div className={tableClass.wrap}>
              <table className={`${tableClass.table} min-w-[1000px]`}>
                <thead className={tableClass.thead}><tr>
                  <th className={tableClass.th}>Field</th><th className={tableClass.th}>Group</th><th className={tableClass.th}>Primary source</th><th className={tableClass.th}>Fallback</th>
                  <th className={tableClass.th}>Validation</th><th className={tableClass.th}>Refresh</th>
                </tr></thead>
                <tbody>{reg.data.fields.map((f) => (
                  <tr key={f.key} className={`${tableClass.tr} align-top`}>
                    <td className={`${tableClass.td} text-ink`}>{f.label}{f.unit ? <span className="block text-[11px] text-ink-3">{f.unit}</span> : null}</td>
                    <td className={`${tableClass.td} text-xs`}>{f.group_label}</td>
                    <td className={`${tableClass.td} text-xs`}>{f.primary}</td>
                    <td className={`${tableClass.td} text-xs`}>{f.secondary.length ? f.secondary.join("; ") : f.fallback}</td>
                    <td className={`${tableClass.td} text-xs`}>{f.validation || "—"}</td>
                    <td className={`${tableClass.td} text-xs`}>{f.refresh || "—"}{f.stale_after_hours ? ` · stale after ${f.stale_after_hours} h` : ""}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <LoadingBlock rows={4} />}
        </Panel>

        <Panel title="Configuration history">
          <ul className="space-y-1 text-sm">
            {data.versions.map((v) => <li key={v.version} className="flex flex-wrap justify-between gap-2"><span className="text-ink">v{v.version}{v.is_active && <span className="ml-2 text-xs text-pos-ink">active</span>}</span><span className="text-xs text-ink-3">{fmtDateTime(v.created_at)}</span></li>)}
          </ul>
          <p className="mt-2 text-xs text-ink-3">Every score row stores the configuration version and an input fingerprint, so a score can always be reproduced.</p>
        </Panel>
      </div>
    </>
  );
}
