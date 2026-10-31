"use client";

import Link from "next/link";
import { PeerMultipleChart } from "@/components/charts/Charts";
import { CompletenessMeter, DataStatusBadge, EmptyState, ErrorState, LoadingBlock, Notice, Panel, ScoreValue, tableClass } from "@/components/kcp/ui";
import { fmtCr, fmtDate, fmtNum, fmtPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { PeerAnalysis, Quartiles } from "@/lib/types";

function QuartileRow({ label, q, ipo, unit }: { label: string; q: Quartiles | null | undefined; ipo: number | null; unit: string }) {
  if (!q) return (
    <tr className={tableClass.tr}><td className={`${tableClass.td} text-ink`}>{label}</td><td className={tableClass.td} colSpan={6}><span className="text-ink-3">insufficient peers</span></td></tr>
  );
  return (
    <tr className={tableClass.tr}>
      <td className={`${tableClass.td} text-ink`}>{label}</td>
      {(["min", "q1", "median", "q3", "max"] as const).map((k) => <td key={k} className={`${tableClass.td} ${tableClass.num}`}>{fmtNum(q[k], 2)}{unit}</td>)}
      <td className={`${tableClass.td} ${tableClass.num} text-ink`}>{ipo !== null ? `${fmtNum(ipo, 2)}${unit}` : "—"}</td>
    </tr>
  );
}

/** The issuer's own listed-peer set with quartile benchmarks, staleness and similar IPOs on record. */
export default function PeersPanel({ ipoId }: { ipoId: number }) {
  const { data, error, loading, reload } = useApi<PeerAnalysis>(`/api/ipos/${ipoId}/peers`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading && !data) return <LoadingBlock rows={6} />;
  if (!data) return null;
  const b = data.benchmarks;
  const chart = data.peers.filter((p) => p.used_in_median).map((p) => ({ name: p.name, value: p.pe as number }));
  return (
    <div className="space-y-6">
      {data.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="IPO vs peer median" subtitle={data.ipo_multiples.price_basis ?? "issue price not yet published"}>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-3"><dt className="text-ink-3">IPO P/E</dt><dd className="tabular-nums text-ink">{fmtNum(data.ipo_multiples.pe, 2)}x</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-3">Peer median P/E</dt><dd className="tabular-nums text-ink">{fmtNum(b?.median_pe, 2)}x</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-3">Premium / (discount)</dt>
              <dd className={`tabular-nums ${data.ipo_multiples.pe_vs_median_pct !== null && data.ipo_multiples.pe_vs_median_pct > 0 ? "text-warn-ink" : "text-pos-ink"}`}>{fmtPct(data.ipo_multiples.pe_vs_median_pct, 1, true)}</dd></div>
            <div className="flex justify-between gap-3 border-t border-line pt-3"><dt className="text-ink-3">IPO P/B</dt><dd className="tabular-nums text-ink">{fmtNum(data.ipo_multiples.pb, 2)}x</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-3">Peer median P/B</dt><dd className="tabular-nums text-ink">{fmtNum(b?.median_pb, 2)}x</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-3">Premium / (discount)</dt><dd className="tabular-nums text-ink">{fmtPct(data.ipo_multiples.pb_vs_median_pct, 1, true)}</dd></div>
          </dl>
          <p className="mt-4 text-xs leading-5 text-ink-3">{b ? `${b.with_pe} of ${b.count} verified peers have a positive P/E${b.excluded_loss_making ? `; ${b.excluded_loss_making} excluded (loss-making or not disclosed)` : ""}. Basis: ${b.basis.join(", ") || "not stated"}; period: ${b.periods.join(", ") || "not stated"}.` : ""}</p>
        </Panel>
        <Panel title="Benchmark distribution" subtitle="Quartiles of the verified peer set (inclusive method)" className="lg:col-span-2">
          <div className={tableClass.wrap}>
            <table className={tableClass.table}>
              <thead className={tableClass.thead}><tr>
                <th className={tableClass.th}>Multiple</th><th className={`${tableClass.th} text-right`}>Min</th><th className={`${tableClass.th} text-right`}>Q1</th>
                <th className={`${tableClass.th} text-right`}>Median</th><th className={`${tableClass.th} text-right`}>Q3</th><th className={`${tableClass.th} text-right`}>Max</th>
                <th className={`${tableClass.th} text-right`}>This IPO</th>
              </tr></thead>
              <tbody>
                <QuartileRow label="P/E" q={b?.pe_quartiles} ipo={data.ipo_multiples.pe} unit="x" />
                <QuartileRow label="P/B" q={b?.pb_quartiles} ipo={data.ipo_multiples.pb} unit="x" />
                <QuartileRow label="RoNW" q={b?.ronw_quartiles} ipo={null} unit="%" />
              </tbody>
            </table>
          </div>
          {chart.length >= 2 && <div className="mt-4"><PeerMultipleChart peers={chart} ipo={data.ipo_multiples.pe} median={b?.median_pe ?? null} label="P/E" /></div>}
        </Panel>
      </div>

      <Panel title="Listed peers named in the offer document" subtitle={data.selection_rationale}>
        {data.peers.length ? (
          <div className={tableClass.wrap}>
            <table className={`${tableClass.table} min-w-[900px]`}>
              <thead className={tableClass.thead}><tr>
                <th className={tableClass.th}>Company</th><th className={`${tableClass.th} text-right`}>Revenue (₹ cr)</th><th className={`${tableClass.th} text-right`}>Price (₹)</th>
                <th className={tableClass.th}>Price date</th><th className={`${tableClass.th} text-right`}>EPS dil.</th><th className={`${tableClass.th} text-right`}>P/E</th>
                <th className={`${tableClass.th} text-right`}>P/B</th><th className={`${tableClass.th} text-right`}>RoNW</th><th className={`${tableClass.th} text-right`}>Latest close</th><th className={tableClass.th}>Status</th>
              </tr></thead>
              <tbody>
                {data.peers.map((p) => (
                  <tr key={p.id} className={`${tableClass.tr} align-top`}>
                    <td className={`${tableClass.td} text-ink`}>{p.name}{p.check_note && <div className={`text-[11px] ${p.check_note.startsWith("P/E consistent") ? "text-ink-3" : "text-warn-ink"}`}>{p.check_note}</div>}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{fmtNum(p.revenue_cr, 0)}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{fmtNum(p.closing_price ?? null, 2)}</td>
                    <td className={`${tableClass.td} whitespace-nowrap text-xs`}>{fmtDate(p.as_of)}{p.stale && <span className="block text-warn-ink">{p.price_age_days} days before opening</span>}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{fmtNum(p.eps_diluted ?? null, 2)}</td>
                    <td className={`${tableClass.td} ${tableClass.num} text-ink`}>{fmtNum(p.pe, 2)}{!p.used_in_median && p.pe !== null && <span className="block text-[11px] text-ink-3">not in median</span>}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{fmtNum(p.pb, 2)}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{p.ronw_pct !== null && p.ronw_pct !== undefined ? `${fmtNum(p.ronw_pct, 2)}%` : "—"}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{p.latest_price ? <>{fmtNum(p.latest_price, 2)}<span className="block text-[11px] text-ink-3">{p.nse_symbol} · {fmtDate(p.latest_price_date)}{p.pe_at_latest_price ? ` · P/E ${fmtNum(p.pe_at_latest_price, 1)}x` : ""}</span></> : "—"}</td>
                    <td className={tableClass.td}><DataStatusBadge status={p.data_status} compact />{p.page && p.document_id ? <a className="ml-2 text-xs text-brand-ink hover:underline" href={`/api/documents/${p.document_id}/file#page=${p.page}`} target="_blank" rel="noopener noreferrer">p{p.page}</a> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No listed-peer table read" body="Peers come from the offer document's 'Basis for Issue Price' section. Without at least two consistent peers, valuation uses absolute ranges and this is flagged." />}
        <p className="mt-2 text-xs text-ink-3">{data.note} Latest-close P/E uses the EPS printed in the offer document (same period as the printed P/E), so it shows the price move, not new earnings.</p>
      </Panel>

      <Panel title="Similar IPOs on record" subtitle={data.similar_basis ?? "Available once this IPO's sector is classified from its offer document"}>
        {data.similar_ipos.length ? (
          <div className={tableClass.wrap}>
            <table className={tableClass.table}>
              <thead className={tableClass.thead}><tr>
                <th className={tableClass.th}>Company</th><th className={tableClass.th}>Opened</th><th className={`${tableClass.th} text-right`}>Issue size</th>
                <th className={`${tableClass.th} text-right`}>P/E</th><th className={`${tableClass.th} text-right`}>Score</th><th className={`${tableClass.th} text-right`}>Risk</th><th className={tableClass.th}>Data</th>
              </tr></thead>
              <tbody>
                {data.similar_ipos.map((s) => (
                  <tr key={s.id} className={tableClass.tr}>
                    <td className={tableClass.td}><Link href={`/ipos/${s.id}`} className="text-ink hover:text-brand-ink">{s.company_name}</Link> <span className="text-xs text-ink-3">{s.issue_type === "sme" ? "SME" : ""}</span></td>
                    <td className={tableClass.td}>{fmtDate(s.open_date)}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{fmtCr(s.issue_size_cr, 0)}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{s.pe !== null ? `${fmtNum(s.pe, 1)}x` : "—"}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}><ScoreValue value={s.composite} /></td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{fmtNum(s.risk, 1)}</td>
                    <td className={tableClass.td}><CompletenessMeter value={s.completeness_pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No other IPOs in this sector yet" />}
      </Panel>
    </div>
  );
}
