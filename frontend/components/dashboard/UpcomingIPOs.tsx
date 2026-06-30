import IPOCard from "@/components/home/IPOCard";

export default function UpcomingIPOs() {
  return (
    <section className="mt-12">

      <div className="mb-6 flex items-center justify-between">

        <div>
          <h2 className="text-3xl font-bold text-white">
            Upcoming IPOs
          </h2>

          <p className="mt-1 text-slate-400">
            AI-ranked IPOs expected to launch soon.
          </p>
        </div>

        <button className="rounded-xl border border-white/10 px-4 py-2 text-sm text-slate-300 transition hover:border-white/30 hover:text-white">
          View All
        </button>

      </div>

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

    </section>
  );
}