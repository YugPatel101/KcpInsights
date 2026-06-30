interface IPOCardProps {
  company: string;
  sector: string;
  score: number;
  risk: "Low" | "Medium" | "High";
}

export default function IPOCard({
  company,
  sector,
  score,
  risk,
}: IPOCardProps) {
  return (
    <div className="group flex items-center justify-between rounded-2xl border border-white/10 bg-black/30 p-6 transition-all duration-300 hover:-translate-y-1 hover:border-slate-500 hover:bg-white/[0.03] hover:shadow-2xl hover:shadow-blue-500/5 cursor-pointer">

      {/* Left */}
      <div>
        <h3 className="text-2xl font-bold text-white transition-colors duration-300 group-hover:text-blue-300">
          {company}
        </h3>

        <p className="mt-2 text-sm text-slate-400">
          {sector}
        </p>
      </div>

      {/* Middle */}
      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">
          AI SCORE
        </p>

        <p className="mt-2 text-3xl font-bold text-white">
          {score}
          <span className="ml-1 text-base font-medium text-slate-500">
            /10
          </span>
        </p>
      </div>

      {/* Right */}
      <div className="flex items-center gap-3">

        <div
          className={`h-3 w-3 rounded-full ${
            risk === "Low"
              ? "bg-emerald-400"
              : risk === "Medium"
              ? "bg-yellow-400"
              : "bg-red-500"
          }`}
        />

        <span className="min-w-[70px] text-left text-lg font-semibold text-slate-200">
          {risk}
        </span>

        <span className="translate-x-0 text-2xl text-slate-500 transition-all duration-300 group-hover:translate-x-2 group-hover:text-white">
          →
        </span>

      </div>

    </div>
  );
}