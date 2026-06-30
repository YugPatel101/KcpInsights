import KcpButton from "@/components/common/KcpButton";

export default function Hero() {
  return (
    <section className="flex min-h-[calc(100vh-64px)] items-center justify-center px-6">
      <div className="mx-auto max-w-4xl text-center">
        <span className="rounded-full border border-slate-700 px-4 py-2 text-sm text-slate-400">
          🚀 AI-powered IPO Research Platform
        </span>

        <h1 className="mt-8 text-6xl font-extrabold leading-tight tracking-tight md:text-7xl">
          Analyze IPOs
          <br />
          <span className="text-slate-400">
            with Confidence.
          </span>
        </h1>

        <p className="mx-auto mt-8 max-w-2xl text-lg leading-8 text-slate-400">
          Make smarter decisions by understanding IPO fundamentals,
          financials, risk factors, and AI-generated insights — all for
          educational purposes.
        </p>

        <div className="mt-10 flex items-center justify-center gap-4">
  <div className="mt-10 flex items-center justify-center gap-4">
  <KcpButton>
  Explore IPOs
</KcpButton>

<KcpButton>
  Learn More
</KcpButton>
</div>
</div>
      </div>
    </section>
  );
}