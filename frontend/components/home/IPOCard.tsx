import Link from "next/link";
import { CompletenessMeter, DataStatusBadge, RiskBadge, StageBadge } from "@/components/kcp/ui";
import { fmtCr, fmtDate, fmtScore, priceBand } from "@/lib/format";
import type { IpoSummary } from "@/lib/types";

export default function IPOCard({ ipo, children }: { ipo: IpoSummary; children?: React.ReactNode }) {
  const s = ipo.scores;
  return (
    <div className="group flex flex-wrap items-center justify-between gap-4 rounded-lg border border-line bg-surface p-4 transition hover:border-line-strong">
      {/* Left */}
      <div className="min-w-0">
        <Link href={`/ipos/${ipo.id}`} className="text-lg font-bold text-ink transition-colors duration-300 group-hover:text-brand-ink">
          {ipo.company_name}
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-2">
          {ipo.issue_type === "sme" ? "SME" : "Mainboard"}
          <StageBadge stage={ipo.stage} />
          <DataStatusBadge status={ipo.data_status} compact />
        </div>
        <div className="mt-2 text-xs text-ink-3">
          {fmtDate(ipo.open_date)} – {fmtDate(ipo.close_date)} · {priceBand(ipo.price_band_low, ipo.price_band_high)} · {fmtCr(ipo.issue_size_cr, 0)}
          {ipo.listing_date && ` · lists ${fmtDate(ipo.listing_date)}${ipo.listing_date_status === "expected" ? " (expected)" : ""}`}
        </div>
      </div>

      {/* Middle */}
      <div className="text-center">
        <p className="text-[11px] font-medium uppercase tracking-wider text-ink-3">Fundamental score</p>
        <p className="mt-1 text-2xl font-bold tabular-nums text-ink">
          {fmtScore(s?.composite)}
          <span className="ml-1 text-sm font-medium text-ink-3">/100</span>
        </p>
        <p className="max-w-44 text-[11px] leading-4 text-ink-3">{s?.classification ?? "not enough verified financials"}</p>
      </div>

      {/* Right */}
      <div className="flex items-center gap-3">
        <CompletenessMeter value={ipo.completeness_pct} />
        <RiskBadge level={s?.risk_level ?? null} />
        {children}
      </div>
    </div>
  );
}
