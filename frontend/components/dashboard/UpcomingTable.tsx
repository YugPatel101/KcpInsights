import Link from "next/link";
import { CompletenessMeter, DataStatusBadge, RiskBadge, ScoreValue, StageBadge, tableClass } from "@/components/kcp/ui";
import { fmtCr, fmtDate, fmtPct, priceBand, returnTone } from "@/lib/format";
import { timeAgo } from "@/lib/time";
import type { IpoSummary } from "@/lib/types";

/** Compact IPO table used on the dashboard (open/upcoming, awaiting, recently closed or listed). */
export default function UpcomingTable({ ipos, showListing = false, dateField = "open_date" }: {
  ipos: IpoSummary[]; showListing?: boolean; dateField?: "open_date" | "close_date" | "listing_date";
}) {
  const dateLabel = showListing ? "Listed" : dateField === "close_date" ? "Closed" : dateField === "listing_date" ? "Lists" : "Opens";
  return (
    <div className={tableClass.wrap}>
      <table className={`${tableClass.table} min-w-[820px]`}>
        <thead className={tableClass.thead}>
          <tr>
            <th scope="col" className={tableClass.th}>Company</th>
            <th scope="col" className={tableClass.th}>Stage</th>
            <th scope="col" className={tableClass.th}>{dateLabel}</th>
            <th scope="col" className={tableClass.th}>Price band</th>
            <th scope="col" className={`${tableClass.th} text-right`}>Issue size</th>
            <th scope="col" className={`${tableClass.th} text-right`}>{showListing ? "Listing gain" : "Score"}</th>
            <th scope="col" className={tableClass.th}>Risk</th>
            <th scope="col" className={tableClass.th}>Data</th>
          </tr>
        </thead>
        <tbody>
          {ipos.map((ipo) => (
            <tr key={ipo.id} className={tableClass.tr}>
              <td className={`${tableClass.td} min-w-56`}>
                <Link href={`/ipos/${ipo.id}`} className="font-medium text-ink hover:text-brand-ink">{ipo.company_name}</Link>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-ink-3">
                  {ipo.issue_type === "sme" ? "SME" : "Mainboard"}
                  {ipo.sector !== "Unclassified" && <span>· {ipo.sector}</span>}
                  {ipo.data_mode === "demo" && <DataStatusBadge status="synthetic" compact />}
                  <span className={ipo.freshness?.is_stale ? "text-warn-ink" : ""} title={ipo.freshness?.stale_reasons?.join("; ") || "Last time the record was confirmed against its source"}>
                    · updated {timeAgo(ipo.freshness?.last_verified_at ?? ipo.last_updated)}
                  </span>
                </div>
              </td>
              <td className={tableClass.td}><StageBadge stage={ipo.stage} /></td>
              <td className={`${tableClass.td} whitespace-nowrap`}>
                {fmtDate(showListing ? ipo.listing_date : ipo[dateField])}
                {dateField === "listing_date" && ipo.listing_date_status === "expected" && <span className="ml-1 text-xs text-ink-3">(exp.)</span>}
              </td>
              <td className={`${tableClass.td} whitespace-nowrap tabular-nums`}>{priceBand(ipo.price_band_low, ipo.price_band_high)}</td>
              <td className={`${tableClass.td} ${tableClass.num}`}>{fmtCr(ipo.issue_size_cr, 0)}</td>
              <td className={`${tableClass.td} ${tableClass.num}`}>
                {showListing ? (
                  <span className={returnTone(ipo.listing_return_pct)}>{fmtPct(ipo.listing_return_pct, 1, true)}</span>
                ) : (
                  <span title={ipo.scores?.classification ?? "No overall score (insufficient verified financials)"}><ScoreValue value={ipo.scores?.composite} /></span>
                )}
              </td>
              <td className={tableClass.td}><RiskBadge level={ipo.scores?.risk_level ?? null} /></td>
              <td className={tableClass.td}><CompletenessMeter value={ipo.completeness_pct} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
