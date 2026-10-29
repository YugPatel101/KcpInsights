import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { DataStatusBadge, RiskBadge, ScoreValue, StatusBadge } from "@/components/kcp/ui";
import { fmtCr, fmtDate, fmtPct, priceBand } from "@/lib/format";
import type { IpoSummary } from "@/lib/types";

export default function UpcomingTable({ ipos, showListing = false }: { ipos: IpoSummary[]; showListing?: boolean }) {
  return (
    <div className="relative overflow-x-auto rounded-2xl border border-white/10 bg-white/[0.02]">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="border-b border-white/10 bg-white/[0.03]">
          <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
            <th scope="col" className="px-5 py-3">Company</th>
            <th scope="col" className="px-3 py-3">Status</th>
            <th scope="col" className="px-3 py-3">{showListing ? "Listed" : "Opens"}</th>
            <th scope="col" className="px-3 py-3">Price band</th>
            <th scope="col" className="px-3 py-3 text-right">Issue size</th>
            <th scope="col" className="px-3 py-3 text-right">{showListing ? "Listing return" : "Research score"}</th>
            <th scope="col" className="px-3 py-3">Risk</th>
            <th scope="col" className="px-5 py-3"><span className="sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {ipos.map((ipo) => (
            <tr key={ipo.id} className="group border-b border-white/5 transition last:border-0 hover:bg-white/[0.04]">
              <td className="px-5 py-4">
                <div className="flex items-center gap-3">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-800 font-bold text-white">{ipo.company_name.charAt(0)}</div>
                  <div className="min-w-0">
                    <Link href={`/ipos/${ipo.id}`} className="font-semibold text-white hover:underline">{ipo.company_name}</Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                      {ipo.sector} · {ipo.issue_type === "sme" ? "SME" : "Mainboard"}
                      <DataStatusBadge status={ipo.data_status} compact />
                    </div>
                  </div>
                </div>
              </td>
              <td className="px-3"><StatusBadge status={ipo.status} /></td>
              <td className="px-3 text-slate-300">{fmtDate(showListing ? ipo.listing_date : ipo.open_date)}</td>
              <td className="px-3 tabular-nums text-slate-300">{priceBand(ipo.price_band_low, ipo.price_band_high)}</td>
              <td className="px-3 text-right tabular-nums text-slate-300">{fmtCr(ipo.issue_size_cr, 0)}</td>
              <td className="px-3 text-right">
                {showListing ? (
                  <span className={`tabular-nums ${ipo.listing_return_pct !== null && ipo.listing_return_pct < 0 ? "text-rose-300" : "text-emerald-300"}`}>
                    {fmtPct(ipo.listing_return_pct, 1, true)}
                  </span>
                ) : (
                  <ScoreValue value={ipo.scores?.composite} />
                )}
              </td>
              <td className="px-3"><RiskBadge level={ipo.scores?.risk_level ?? null} /></td>
              <td className="px-5 text-right">
                <Link href={`/ipos/${ipo.id}`} className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs transition hover:border-slate-500 hover:bg-white/5" aria-label={`Open ${ipo.company_name}`}>
                  Details <ArrowRight size={14} className="transition group-hover:translate-x-0.5" aria-hidden />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
