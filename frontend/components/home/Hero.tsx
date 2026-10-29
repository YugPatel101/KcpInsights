import Link from "next/link";
import KcpButton from "@/components/common/KcpButton";

export default function Hero() {
  return (
    <section className="flex min-h-[calc(100vh-80px)] items-center justify-center px-6">
      <div className="mx-auto max-w-4xl text-center">
        <span className="rounded-full border border-slate-700 px-4 py-2 text-sm text-slate-400">
          Educational IPO research · Indian mainboard &amp; SME issues
        </span>

        <h1 className="mt-8 text-5xl font-extrabold leading-tight tracking-tight sm:text-6xl md:text-7xl">
          Analyze IPOs
          <br />
          <span className="text-slate-400">with evidence.</span>
        </h1>

        <p className="mx-auto mt-8 max-w-2xl text-lg leading-8 text-slate-400">
          Study an IPO&apos;s fundamentals, valuation against listed peers, risk disclosures and scenarios — with every
          score traceable to its inputs, formula and source. Runs locally and free, with an optional on-device AI model.
        </p>

        <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <KcpButton asChild>
            <Link href="/ipos">Explore IPOs</Link>
          </KcpButton>

          <KcpButton asChild>
            <Link href="#methodology">How scoring works</Link>
          </KcpButton>
        </div>
      </div>
    </section>
  );
}
