"use client";

import Link from "next/link";
import { useState } from "react";
import { DivergingBarChart, OutcomeScatter } from "@/components/charts/Charts";
import { EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Panel, ScoreValue, Stat, inputClass, tableClass } from "@/components/kcp/ui";
import { fmtCr, fmtDate, fmtInr, fmtNum, fmtPct, returnTone } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { HistoryResponse, OutcomeStats } from "@/lib/types";

function StatsLine({ s }: { s: OutcomeStats }) {
  return <>{s.n ? `mean ${fmtPct(s.mean, 1, true)} · median ${fmtPct(s.median, 1, true)} · ${fmtPct(s.positive_share, 0)} positive (n=${s.n})` : "no observations"}</>;
}

export default function HistoryPage() {
  const [issueType, setIssueType] = useState("");
  const [since, setSince] = useState("");
  const qs = new URLSearchParams({ ...(issueType ? { issue_type: issueType } : {}), ...(since ? { since } : {}) }).toString();
  const { data, error, loading, reload } = useApi<HistoryResponse>(`/api/history${qs ? `?${qs}` : ""}`);

  return (
    <>
      <PageHeader
        eyebrow="Research"
        title="Listing history"
        subtitle="Listing-day outcomes of IPOs on record: final issue price from NSE, listing-day open, high, low and close from the official NSE bhavcopy. Past outcomes do not indicate future performance."
        actions={
          <div className="flex flex-wrap gap-2">
            <select className={`${inputClass} w-40`} value={issueType} onChange={(e) => setIssueType(e.target.value)} aria-label="Issue type">
              <option value="">All issues</option><option value="mainboard">Mainboard</option><option value="sme">SME</option>
            </select>
            <input type="date" className={`${inputClass} w-44`} value={since} onChange={(e) => setSince(e.target.value)} aria-label="Listed since" />
          </div>
        }
      />
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingBlock rows={8} />}
      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Listed IPOs on record" value={String(data.count)} hint={`${data.with_listing_price} with a verified listing price`} />
            <Stat label="Median listing gain" value={fmtPct(data.summary.listing_gain.median, 1, true)} hint={data.formulas.listing_gain} />
            <Stat label="Median close-day return" value={fmtPct(data.summary.listing_close_return.median, 1, true)} hint={data.formulas.listing_close_return} />
            <Stat label="Listed above issue price" value={fmtPct(data.summary.listing_gain.positive_share, 0)} hint={`of ${data.summary.listing_gain.n} with prices`} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
            <Panel title="Median listing gain by sector" subtitle={<StatsLine s={data.summary.listing_gain} />}>
              {data.by_sector.length ? (
                <>
                  <DivergingBarChart data={data.by_sector.filter((g) => g.median !== null && g.n >= 2).slice(0, 14)
                                       .map((g) => ({ name: `${g.group} (n=${g.n})`, value: g.median as number, n: g.n }))}
                                     label="Median listing gain" height={Math.max(180, Math.min(14, data.by_sector.filter((g) => g.n >= 2).length) * 30)} />
                  <p className="mt-2 text-xs text-ink-3">Sectors with at least two listings; sector names follow NSE&apos;s label where it publishes one, otherwise the offer-document classification.</p>
                </>
              ) : <EmptyState title="No listing prices yet" />}
            </Panel>
            <Panel title="By issue size and type" subtitle="Median listing gain per group">
              <div className={tableClass.wrap}>
                <table className={`${tableClass.table} min-w-[420px]`}>
                  <thead className={tableClass.thead}><tr><th className={tableClass.th}>Group</th><th className={`${tableClass.th} text-right`}>n</th><th className={`${tableClass.th} text-right`}>Median</th><th className={`${tableClass.th} text-right`}>Mean</th><th className={`${tableClass.th} text-right`}>Positive</th></tr></thead>
                  <tbody>
                    {[...data.by_issue_type.map((g) => ({ ...g, group: g.group === "sme" ? "SME" : "Mainboard" })), ...data.by_issue_size].map((g) => (
                      <tr key={g.group} className={tableClass.tr}>
                        <td className={`${tableClass.td} text-ink`}>{g.group}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{g.n}</td>
                        <td className={`${tableClass.td} ${tableClass.num} ${returnTone(g.median)}`}>{fmtPct(g.median, 1, true)}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{fmtPct(g.mean, 1, true)}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{fmtPct(g.positive_share, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>

          <Panel title="Pre-listing score vs listing gain"
                 subtitle={`n = ${data.score_vs_outcome.n}${data.score_vs_outcome.spearman_rho !== null ? ` · Spearman rank correlation ${fmtNum(data.score_vs_outcome.spearman_rho, 2)}` : ""}`}>
            <Notice>{data.score_vs_outcome.note} Only scores whose inputs were all public before the listing date are included (point-in-time check on each offer document&apos;s publication date).</Notice>
            <div className="mt-4">
              {data.score_vs_outcome.pairs.length ? (
                <OutcomeScatter points={data.items.filter((r) => r.pre_listing_score !== null && r.listing_gain_pct !== null)
                  .map((r) => ({ id: r.id, name: r.company_name, score: r.pre_listing_score as number, gain: r.listing_gain_pct as number }))} />
              ) : <EmptyState title="No listed IPO has both a point-in-time score and a listing price yet" />}
            </div>
          </Panel>

          <Panel title="Listed IPOs" subtitle={data.source}>
            {data.items.length ? (
              <div className={tableClass.wrap}>
                <table className={`${tableClass.table} min-w-[1100px]`}>
                  <thead className={tableClass.thead}><tr>
                    <th className={tableClass.th}>Company</th><th className={tableClass.th}>Listed</th><th className={`${tableClass.th} text-right`}>Issue size</th>
                    <th className={`${tableClass.th} text-right`}>Issue price</th><th className={`${tableClass.th} text-right`}>Open</th><th className={`${tableClass.th} text-right`}>High / low</th>
                    <th className={`${tableClass.th} text-right`}>Close</th><th className={`${tableClass.th} text-right`}>Listing gain</th><th className={`${tableClass.th} text-right`}>Close return</th>
                    <th className={`${tableClass.th} text-right`}>Subscribed</th><th className={`${tableClass.th} text-right`}>Pre-listing score</th>
                  </tr></thead>
                  <tbody>
                    {data.items.map((r) => (
                      <tr key={r.id} className={tableClass.tr}>
                        <td className={tableClass.td}><Link href={`/ipos/${r.id}`} className="text-ink hover:text-brand-ink">{r.company_name}</Link>
                          <span className="block text-xs text-ink-3">{r.issue_type === "sme" ? "SME" : "Mainboard"} · {r.sector}</span></td>
                        <td className={`${tableClass.td} whitespace-nowrap`}>{fmtDate(r.listing_date)}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{fmtCr(r.issue_size_cr, 0)}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{fmtInr(r.final_issue_price)}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{fmtInr(r.listing_open)}</td>
                        <td className={`${tableClass.td} ${tableClass.num} whitespace-nowrap`}>{r.listing_high !== null ? `${fmtNum(r.listing_high, 2)} / ${fmtNum(r.listing_low, 2)}` : "—"}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{fmtInr(r.listing_close)}</td>
                        <td className={`${tableClass.td} ${tableClass.num} ${returnTone(r.listing_gain_pct)}`}>{fmtPct(r.listing_gain_pct, 1, true)}</td>
                        <td className={`${tableClass.td} ${tableClass.num} ${returnTone(r.listing_close_return_pct)}`}>{fmtPct(r.listing_close_return_pct, 1, true)}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`}>{r.subscription_total !== null ? `${fmtNum(r.subscription_total, 1)}x` : "—"}</td>
                        <td className={`${tableClass.td} ${tableClass.num}`} title={r.point_in_time_note ?? undefined}>
                          {r.pre_listing_score !== null ? <ScoreValue value={r.pre_listing_score} /> : <span className="text-xs text-ink-3">{r.score_available ? "excluded" : "—"}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState title="No listed IPOs on record" body="Run `python -m app.cli backfill-history --days 365` to import past issues and their listing-day prices." />}
            <p className="mt-2 text-xs text-ink-3">“Excluded” scores rely on a document whose publication date could not be confirmed as before the listing. Subscription is the last consolidated figure NSE published while bidding was open.</p>
          </Panel>
        </div>
      )}
    </>
  );
}
