import { ArrowRight } from "lucide-react";

const ipos = [
  {
    company: "Tata Capital",
    sector: "Financial Services",
    score: 8.8,
    risk: "Low",
    opens: "10 Jul",
    status: "Upcoming",
  },
  {
    company: "NSDL",
    sector: "Depository Services",
    score: 8.2,
    risk: "Medium",
    opens: "18 Jul",
    status: "Upcoming",
  },
  {
    company: "Hero FinCorp",
    sector: "NBFC",
    score: 7.6,
    risk: "Medium",
    opens: "25 Jul",
    status: "Upcoming",
  },
];

export default function UpcomingTable() {
  return (
    <section className="mt-14">

      <div className="mb-8 flex items-center justify-between">

        <div>
          <h2 className="text-3xl font-bold">
            Upcoming IPOs
          </h2>

          <p className="mt-2 text-slate-400">
            Highest rated IPOs based on our AI model.
          </p>
        </div>

        <button className="rounded-xl border border-white/10 px-5 py-2 text-sm transition hover:border-slate-500 hover:bg-white/5">
          View All
        </button>

      </div>

      <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02]">

        <table className="w-full">

          <thead className="border-b border-white/10 bg-white/[0.03]">

            <tr className="text-left text-sm uppercase tracking-wider text-slate-500">

              <th className="px-8 py-5">Company</th>
              <th>AI Score</th>
              <th>Risk</th>
              <th>Opens</th>
              <th>Status</th>
              <th></th>

            </tr>

          </thead>

          <tbody>

            {ipos.map((ipo) => (

              <tr
                key={ipo.company}
                className="group border-b border-white/5 transition hover:bg-white/[0.04]"
              >

                <td className="px-8 py-6">

                  <div className="flex items-center gap-4">

                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-800 text-lg font-bold text-white">
                      {ipo.company.charAt(0)}
                    </div>

                    <div>

                      <p className="font-semibold text-white">
                        {ipo.company}
                      </p>

                      <p className="text-sm text-slate-400">
                        {ipo.sector}
                      </p>

                    </div>

                  </div>

                </td>

                <td>

                  <span className="font-bold text-white">
                    {ipo.score}
                  </span>

                  <span className="text-slate-500">
                    /10
                  </span>

                </td>

                <td>

                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      ipo.risk === "Low"
                        ? "bg-emerald-500/10 text-emerald-400"
                        : "bg-yellow-500/10 text-yellow-400"
                    }`}
                  >
                    {ipo.risk}
                  </span>

                </td>

                <td className="text-slate-300">
                  {ipo.opens}
                </td>

                <td>

                  <span className="rounded-full bg-sky-500/10 px-3 py-1 text-xs font-semibold text-sky-400">
                    {ipo.status}
                  </span>

                </td>

                <td className="pr-8">

                  <button className="flex items-center gap-2 rounded-lg border border-white/10 px-4 py-2 text-sm transition hover:border-slate-500 hover:bg-white/5">

                    Details

                    <ArrowRight
                      size={16}
                      className="transition group-hover:translate-x-1"
                    />

                  </button>

                </td>

              </tr>

            ))}

          </tbody>

        </table>

      </div>

    </section>
  );
}