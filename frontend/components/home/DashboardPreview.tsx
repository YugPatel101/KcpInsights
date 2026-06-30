import IPOCard from "./IPOCard";

export default function DashboardPreview() {
  return (
    <section className="mx-auto mt-24 max-w-6xl px-6">
      <div className="rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">

        {/* Header */}
        <div className="mb-10 flex items-center justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-slate-400">
              PRODUCT PREVIEW
            </p>

            <h2 className="mt-2 text-4xl font-bold text-white">
              Upcoming IPO Dashboard
            </h2>
          </div>

          <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-400">
            LIVE
          </span>
        </div>

        {/* IPO Cards */}
        <div className="space-y-5">
          <IPOCard
            company="Tata Capital"
            sector="Financial Services"
            score={8.8}
            risk="Low"
          />

          <IPOCard
            company="NSDL"
            sector="Depository Services"
            score={8.2}
            risk="Medium"
          />

          <IPOCard
            company="Hero FinCorp"
            sector="NBFC"
            score={7.6}
            risk="Medium"
          />
        </div>

        {/* AI Verdict */}
        <div className="mt-10 rounded-2xl border border-white/10 bg-black/30 p-6">
          <h3 className="mb-4 text-xl font-semibold text-white">
            🤖 AI Verdict
          </h3>

          <p className="leading-8 text-slate-300">
            Strong financial fundamentals • Healthy subscription trend •
            Balanced valuation • Suitable for further analysis.
          </p>
        </div>

      </div>
    </section>
  );
}