"use client";

import Link from "next/link";
import { Fragment, useState } from "react";
import IpoPicker from "@/components/ipo/IpoPicker";
import { CompletenessMeter, DataStatusBadge, ErrorState, LoadingBlock, Notice, PageHeader, Panel, ReadinessBadge, RiskBadge, ScoreValue, buttonClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtCr, fmtInr, fmtInt, fmtMetric, fmtNum, fmtPct, fmtScore, priceBand, titleCase } from "@/lib/format";
import type { ComponentKey, IpoSummary, PeerSummary, ScoreResult, ScoreSummary } from "@/lib/types";

interface CompareItem {
  ipo: IpoSummary;
  scores: ScoreSummary;
  components: Record<ComponentKey, { score: number | null; coverage: number }>;
  risk_components: Record<string, number | null>;
  metrics: Record<string, { value: number | null; unit: string; status: string; label: string }>;
  peers: PeerSummary | null;
  price: ScoreResult["price"];
  profile: { key: string; label: string } | null;
  governance: { score: number | null } | null;
  completeness_pct: number | null;
  completeness: IpoSummary["completeness"];
  warnings: string[];
}

const METRIC_GROUPS: [string, string[]][] = [
  ["Profitability", ["roe", "roce", "roa", "net_margin", "ebitda_margin"]],
  ["Growth", ["revenue_cagr", "pat_cagr", "ebitda_cagr", "revenue_yoy", "pat_yoy"]],
  ["Liquidity & leverage", ["current_ratio", "quick_ratio", "debt_to_equity", "debt_to_assets", "interest_coverage", "debt_to_ebitda"]],
  ["Cash flow", ["ocf_to_pat", "fcf", "fcf_margin", "cash_conversion"]],
  ["Valuation", ["market_cap", "pe", "pb", "ev_ebitda", "price_to_sales"]],
];
const COMPONENTS: ComponentKey[] = ["profitability", "growth", "financial_health", "cash_flow", "valuation"];

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
    <tr className="border-t border-line">
      <th scope="row" className="py-2 pr-4 text-left font-normal text-ink-2">{label}</th>
      {items!.map((i) => <td key={i.ipo.id} className="py-2 pr-4 text-right tabular-nums text-ink">{f(i)}</td>)}
    </tr>
  );

  return (
    <>
      <PageHeader eyebrow="Comparison" title="Compare IPOs side by side" subtitle="Fundamentals, growth, profitability, leverage, valuation, risk and data completeness side by side. All scores use one configuration version, so they are directly comparable. Compare research characteristics, not predicted returns." />
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
                          <Link href={`/ipos/${i.ipo.id}`} className="font-semibold text-ink hover:underline">{i.ipo.company_name}</Link>
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
                    {row("Face value", (i) => fmtInr(i.ipo.face_value ?? null, 0))}
                    {row("Lot size · one lot at upper band", (i) => i.ipo.lot_size ? `${fmtInt(i.ipo.lot_size)} · ${fmtInr(i.ipo.min_investment_inr, 0)}` : "—")}
                    {row("Promoter holding pre → post", (i) => `${fmtPct(i.ipo.promoter_holding_pre_pct ?? null, 2)} → ${fmtPct(i.ipo.promoter_holding_post_pct ?? null, 2)}`)}
                    {row("Stage", (i) => titleCase(i.ipo.stage))}
                    {row("Fundamental score", (i) => <ScoreValue value={i.scores.composite} />)}
                    {row("Classification", (i) => i.scores.classification ?? "—")}
                    {row("Risk", (i) => <span className="inline-flex items-center gap-2">{fmtScore(i.scores.risk)} <RiskBadge level={i.scores.risk_level} /></span>)}
                    {row("Governance & disclosure risk", (i) => fmtScore(i.governance?.score))}
                    {row("Industry profile", (i) => i.profile?.label ?? "General")}
                    {row("Data completeness", (i) => <span className="inline-flex items-center justify-end gap-2"><CompletenessMeter value={i.completeness_pct} /><ReadinessBadge level={i.completeness?.readiness} /></span>)}
                    {row("Score coverage", (i) => fmtPct(i.scores.coverage, 0))}
                    {row("Financial basis / latest year", (i) => `${i.scores.basis ?? "—"} · ${i.scores.latest_period ?? "—"}`)}
                    <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-ink-3">Component scores</td></tr>
                    {COMPONENTS.map((k) => row(titleCase(k), (i) => <ScoreValue value={i.components[k]?.score} />))}
                    <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-ink-3">Risk components (higher = riskier)</td></tr>
                    {Object.keys(items[0].risk_components).map((k) => row(titleCase(k), (i) => fmtScore(i.risk_components[k])))}
                    <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-ink-3">Valuation context</td></tr>
                    {row("Price used", (i) => `${fmtNum(i.price.price)}${i.price.price_status === "estimated" ? " (upper band)" : ""}`)}
                    {row("Peer median P/E", (i) => (i.peers?.median_pe ? `${fmtNum(i.peers.median_pe)}x` : "—"))}
                    {METRIC_GROUPS.map(([g, keys]) => (
                      <Fragment key={g}>
                        <tr><td colSpan={items.length + 1} className="pt-5 text-xs uppercase tracking-wider text-ink-3">{g}</td></tr>
                        {keys.map((k) => row(items.find((i) => i.metrics[k])?.metrics[k].label ?? titleCase(k), (i) => {
                          const m = i.metrics[k];
                          if (!m) return "—";
                          if (m.status === "not_applicable") return <span className="text-xs text-ink-3">n/a for {i.profile?.label ?? "profile"}</span>;
                          if (m.status === "not_meaningful") return <span className="text-xs text-ink-3">not meaningful</span>;
                          return m.unit === "₹ cr" ? fmtCr(m.value, 0) : fmtMetric(m.value, m.unit);
                        }))}
                      </Fragment>
                    ))}
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
