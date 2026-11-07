import { fmtDate } from "@/lib/format";

export default function DashboardHeader({ asOf }: { asOf?: string }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-line pb-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">Market overview</h1>
        <p className="mt-1.5 text-sm text-ink-2">Indian IPOs on record — issue stages, prospectus analysis and data health{asOf ? `, as of ${fmtDate(asOf)}` : ""}.</p>
      </div>
    </header>
  );
}
