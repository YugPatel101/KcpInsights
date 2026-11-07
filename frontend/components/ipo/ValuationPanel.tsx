"use client";

import { EmptyState, ErrorState, LoadingBlock, Notice, Panel, ScoreValue } from "@/components/kcp/ui";
import { fmtCr, fmtInr, fmtInt, fmtNum } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { IpoDetail, ScoreResult, SensitivityRow } from "@/lib/types";

/** Issue-price multiples, listed-peer comparison (from the prospectus) and price-band sensitivity. */
export default function ValuationPanel({ d, r }: { d: IpoDetail; r: ScoreResult }) {
  const sens = useApi<{ rows: SensitivityRow[]; note: string }>(`/api/ipos/${d.id}/valuation-sensitivity`);
  const pb = r.metrics.pb;
  const ps = r.peers;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Price and share count used" className="lg:col-span-1">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-ink-2">Issue price</dt><dd className="tabular-nums text-ink">{fmtInr(r.price.price)}</dd></div>
            <div className="text-xs text-ink-3">{r.price.price_basis ?? "price not yet published"}</div>
            <div className="flex justify-between gap-4"><dt className="text-ink-2">Post-issue shares</dt><dd className="tabular-nums text-ink">{fmtInt(r.price.post_issue_shares)}</dd></div>
            <div className="text-xs text-ink-3">{r.price.post_issue_shares_formula ?? "from stored issue data"}{r.price.post_issue_shares_status ? ` · ${r.price.post_issue_shares_status}` : ""}</div>
            <div className="flex justify-between gap-4"><dt className="text-ink-2">Market cap at issue</dt><dd className="tabular-nums text-ink">{fmtCr(r.price.market_cap_cr)}</dd></div>
          </dl>
          {r.price.price_status === "estimated" && <p className="mt-3 text-xs text-warn-ink">Estimated: recalculated automatically when NSE publishes the final issue price.</p>}
        </Panel>
        <Panel title="Multiples" subtitle="Latest annual period, post-issue basis" className="lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {["pe", "pb", "ev_ebitda", "price_to_sales"].map((k) => {
              const m = r.metrics[k];
              const item = r.components.valuation.items.find((i) => i.key === k);
              return (
                <div key={k} className="rounded-xl border border-line bg-surface p-4" title={m?.formula}>
                  <div className="text-xs text-ink-3">{m?.label ?? k}</div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{m?.status === "ok" && m.value !== null ? `${fmtNum(m.value, 1)}x` : "—"}</div>
                  <div className="mt-1 text-xs text-ink-3">{m?.status === "ok" ? (item?.note ?? "") : m?.reason}</div>
                  <div className="mt-2 text-xs">{item ? <>score <ScoreValue value={item.score} /></> : <span className="text-ink-3">shown, not scored</span>}</div>
                </div>
              );
            })}
          </div>
          <p className="mt-4 text-xs text-ink-3">Valuation score V = {Object.entries(r.components.valuation.weights ?? { pe: 0.4, pb: 0.3, ev_ebitda: 0.3 }).map(([k, w]) => `${w.toFixed(2)}·S(${r.metrics[k]?.label ?? k})`).join(" + ")} over the multiples that are meaningful; a multiple below the peer median scores higher. Loss-making companies have no meaningful P/E, so it is left out rather than forced.</p>
        </Panel>
      </div>

      <Notice>
        Peer comparison — the issuer&apos;s listed peers with quartile benchmarks, price dates and similar IPOs on record — is on the <strong>Peers</strong> tab.
        {ps?.median_pe ? ` Peer median P/E ${fmtNum(ps.median_pe, 2)}x · median P/B ${fmtNum(ps.median_pb, 2)}x.` : " Peer valuation is unavailable for this issue."}
      </Notice>

      <Panel title="Price-band sensitivity" subtitle={sens.data?.note}>
        {sens.error ? <ErrorState message={sens.error} onRetry={sens.reload} /> : !sens.data ? <LoadingBlock rows={2} /> : sens.data.rows.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wider text-ink-3"><th className="py-2">Price</th><th className="py-2 text-right">₹</th><th className="py-2 text-right">Market cap</th><th className="py-2 text-right">P/E</th><th className="py-2 text-right">P/B</th><th className="py-2 text-right">EV/EBITDA</th><th className="py-2 text-right">P/S</th><th className="py-2 text-right">Valuation score</th><th className="py-2 text-right">Q</th></tr></thead>
              <tbody>
                {sens.data.rows.map((x) => (
                  <tr key={x.label} className="border-t border-line">
                    <td className="py-2 text-ink-2">{x.label}</td><td className="py-2 text-right tabular-nums">{fmtNum(x.price, 2)}</td><td className="py-2 text-right tabular-nums">{fmtCr(x.market_cap_cr)}</td>
                    <td className="py-2 text-right tabular-nums">{fmtNum(x.pe, 2)}</td><td className="py-2 text-right tabular-nums">{fmtNum(x.pb, 2)}</td><td className="py-2 text-right tabular-nums">{fmtNum(x.ev_ebitda, 2)}</td><td className="py-2 text-right tabular-nums">{fmtNum(x.price_to_sales ?? null, 2)}</td>
                    <td className="py-2 text-right"><ScoreValue value={x.valuation_score} /></td><td className="py-2 text-right"><ScoreValue value={x.fundamental_score} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="Price band not yet published" />}
      </Panel>
      {pb && pb.status !== "ok" && <p className="text-xs text-ink-3">P/B: {pb.reason}</p>}
    </div>
  );
}
