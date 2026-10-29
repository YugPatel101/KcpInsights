import Link from "next/link";
import { DataStatusBadge, RiskBadge, StatusBadge } from "@/components/kcp/ui";
import { fmtScore } from "@/lib/format";
import type { IpoSummary } from "@/lib/types";

export default function IPOCard({ ipo, children }: { ipo: IpoSummary; children?: React.ReactNode }) {
  const s = ipo.scores;
  return (
    <div className="group flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-black/30 p-5 transition-all duration-300 hover:border-slate-500 hover:bg-white/[0.03]">
      {/* Left */}
      <div className="min-w-0">
        <Link href={`/ipos/${ipo.id}`} className="text-lg font-bold text-white transition-colors duration-300 group-hover:text-blue-300">
          {ipo.company_name}
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-400">
          {ipo.sector}
          <StatusBadge status={ipo.status} />
          <DataStatusBadge status={ipo.data_status} compact />
        </div>
      </div>

      {/* Middle */}
      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Research score</p>
        <p className="mt-1 text-2xl font-bold tabular-nums text-white">
          {fmtScore(s?.composite)}
          <span className="ml-1 text-sm font-medium text-slate-500">/100</span>
        </p>
      </div>

      {/* Right */}
      <div className="flex items-center gap-3">
        <RiskBadge level={s?.risk_level ?? null} />
        {children}
      </div>
    </div>
  );
}
