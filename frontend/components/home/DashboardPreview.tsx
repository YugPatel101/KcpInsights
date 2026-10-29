import Link from "next/link";

const formulas = [
  { name: "Quality Q", formula: "0.25·P + 0.20·G + 0.20·C + 0.20·B + 0.15·R", body: "Profitability, growth, cash-flow quality, balance-sheet strength and revenue stability — each from documented metrics with bounded linear normalisation." },
  { name: "Valuation V", formula: "100 · clip((V_high − V_IPO) / (V_high − V_low))", body: "The IPO's multiple versus the 25th–75th percentile of a stated peer set. Unavailable when peers or earnings make the comparison unsuitable." },
  { name: "Risk R", formula: "0.25·R_f + 0.20·R_v + 0.20·R_g + 0.20·R_m + 0.15·R_d", body: "Financial distress flags, valuation premium, confirmed disclosures, market structure and data-quality uncertainty. Missing data is never treated as misconduct." },
];

const modes = [
  { name: "Demo", body: "Clearly labelled synthetic companies to explore the product offline." },
  { name: "Imported", body: "Upload CSV/JSON research from offer documents; validated with provenance." },
  { name: "Source-connected", body: "Fetch permitted official documents (SEBI/NSE/BSE) with caching and rate limits." },
];

export default function DashboardPreview() {
  return (
    <section id="methodology" className="mx-auto mt-12 max-w-6xl scroll-mt-24 px-6 pb-24">
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 shadow-2xl backdrop-blur-xl sm:p-8">
        <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-slate-400">METHODOLOGY</p>
            <h2 className="mt-2 text-3xl font-bold text-white sm:text-4xl">A research score you can audit</h2>
          </div>
          <span className="rounded-full border border-sky-500/20 bg-sky-500/10 px-4 py-2 font-mono text-sm text-sky-300">
            S = 0.45·Q + 0.30·V + 0.25·(100 − R)
          </span>
        </div>

        <div className="grid gap-5 md:grid-cols-3">
          {formulas.map((f) => (
            <div key={f.name} className="rounded-2xl border border-white/10 bg-black/30 p-6">
              <h3 className="text-xl font-bold text-white">{f.name}</h3>
              <p className="mt-2 font-mono text-xs text-slate-400">{f.formula}</p>
              <p className="mt-4 text-sm leading-6 text-slate-300">{f.body}</p>
            </div>
          ))}
        </div>

        <div className="mt-8 rounded-2xl border border-white/10 bg-black/30 p-6">
          <h3 className="mb-4 text-xl font-semibold text-white">Three data modes, clearly separated</h3>
          <div className="grid gap-4 sm:grid-cols-3">
            {modes.map((m) => (
              <div key={m.name}>
                <p className="font-medium text-slate-200">{m.name}</p>
                <p className="mt-1 text-sm leading-6 text-slate-400">{m.body}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="mt-8 text-sm leading-6 text-slate-500">
          Weights are configurable educational defaults, not statistically validated coefficients. The research score is not a
          probability of listing gains and nothing here is investment advice.{" "}
          <Link href="/analysis" className="text-slate-300 underline-offset-4 hover:underline">
            Read the full methodology
          </Link>
          .
        </p>
      </div>
    </section>
  );
}
