"use client";

import Link from "next/link";
import { useState } from "react";
import IpoPicker from "@/components/ipo/IpoPicker";
import { DataStatusBadge, ErrorState, LoadingBlock, Notice, PageHeader, Panel, RiskBadge, ScoreValue, buttonClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtCr, fmtMetric, fmtNum, fmtPct, fmtScore, priceBand, titleCase } from "@/lib/format";
import type { IpoSummary, ScoreSummary } from "@/lib/types";

interface CompareItem {
  ipo: IpoSummary;
  scores: ScoreSummary;
  quality_components: Record<string, number | null>;
  risk_components: Record<string, number | null>;
  valuation: Record<string, number | string | null>;
  metrics: Record<string, { value: number | null; unit: string; status: string }>;
  warnings: string[];
}

const METRICS = ["revenue_cagr", "ebitda_margin", "pat_margin", "roe", "ocf_to_pat", "debt_to_equity", "interest_coverage", "revenue_growth_volatility"];

export default function ComparePage() {
  const [ids, setIds] = useState<(number | null)[]>([null, null, null]);
  const [items, setItems] = useState<CompareItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chosen = ids.filter((x): x is number => x !== null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setItems((await api<{ items: CompareItem[] }>("/api/ipos/compare", { body: { ipo_ids: chosen } })).items);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const row = (label: string, f: (i: CompareItem) => React.ReactNode) => (
    <tr className="border-t border-white/5">
      <th scope="row" className="py-2 pr-4 text-left font-normal text-slate-400">{label}</th>
      {items!.map((i) => <td key={i.ipo.id} className="py-2 pr-4 text-right tabular-nums text-slate-200">{f(i)}</td>)}
    </tr>
  );

  return (
    <>
      <PageHeader eyebrow="Comparison" title="Compare IPOs side by side" subtitle="All scores use the same configuration version, so they are directly comparable. Compare research quality, not predicted returns." />
      <Panel>
        <div className="grid gap-3 sm:grid-cols-3">
          {ids.map((v, k) => (
            <IpoPicker key={k} label={`IPO ${k + 1}${k === 2 ? " (optional)" : ""}`} value={v} allowEmpty={k === 2} exclude={chosen} onChange={(n) => setIds(ids.map((x, j) => (j === k ? n : x)))} />
          ))}
        </div>
        <button className={`${buttonClass.primary} mt-4`} disabled={chosen.length < 2 || busy} onClick={run}>Compare</button>
      </Panel>
      <div className="mt-6">
        {error && <ErrorState message={error} />}
        {busy && <LoadingBlock rows={6} />}
        {items && !busy && (
          <>
            {items.some((i) => i.ipo.data_status === "synthetic") && <div className="mb-4"><Notice tone="synthetic">Includes synthetic demonstration IPOs (fictional data).</Notice></div>}
            <Panel>
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr>
                      <th className="py-2" />
                      {items.map((i) => (
                        <th key={i.ipo.id} scope="col" className="py-2 pr-4 text-right align-bottom">
                          <Link href={`/ipos/${i.ipo.id}`} className="font-semibold text-white hover:underline">{i.ipo.company_name}</Link>
                          <div className="mt-1 flex justify-end gap-1"><DataStatusBadge status={i.ipo.data_status} compact /></div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {row("Sector", (i) => i.ipo.sector)}
                    {row("Status", (i) => titleCase(i.ipo.status))}
                    {row("Price band", (i) => priceBand(i.ipo.price_band_low, i.ipo.price_band_high))}
                    {row("Issue size", (i) => fmtCr(i.ipo.issue_size_cr, 0))}
                    {row("Research score", (i) => <ScoreValue value={i.scores.composite} />)}
                    {row("Quality", (i) => <ScoreValue value={i.scores.quality} />)}
                    {row("Valuation", (i) => <ScoreValue value={i.scores.valuation} />)}
                    {row("Risk", (i) => <span className="inline-flex items-center gap-2">{fmtScore(i.scores.risk)} <RiskBadge level={i.scores.risk_level} /></span>)}
                    {row("Evidence coverage", (i) => fmtPct(i.scores.coverage, 0))}
                    <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-slate-500">Quality components</td></tr>
                    {Object.keys(items[0].quality_components).map((k) => row(titleCase(k), (i) => <ScoreValue value={i.quality_components[k]} />))}
                    <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-slate-500">Risk components (higher = riskier)</td></tr>
                    {Object.keys(items[0].risk_components).map((k) => row(titleCase(k), (i) => fmtScore(i.risk_components[k])))}
                    <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-slate-500">Valuation</td></tr>
                    {row("Multiple used", (i) => (i.valuation.multiple_label as string) ?? "—")}
                    {row("IPO multiple", (i) => (i.valuation.ipo_multiple === null ? "—" : `${fmtNum(i.valuation.ipo_multiple as number)}x`))}
                    {row("Peer median", (i) => (i.valuation.peer_median === null ? "—" : `${fmtNum(i.valuation.peer_median as number)}x`))}
                    {row("Premium to median", (i) => fmtPct(i.valuation.premium_to_median_pct as number | null, 1, true))}
                    <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-slate-500">Metrics</td></tr>
                    {METRICS.map((k) => row(titleCase(k), (i) => fmtMetric(i.metrics[k]?.value ?? null, i.metrics[k]?.unit ?? "")))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </>
        )}
      </div>
    </>
  );
}
