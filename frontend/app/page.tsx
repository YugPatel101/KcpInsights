"use client";

import Link from "next/link";
import { ArrowRight, BookOpenText, CalendarDays, FileSearch, Gauge, Layers, ShieldCheck } from "lucide-react";
import Navbar from "@/components/layout/Navbar";
import { CompletenessMeter, Disclaimer, RiskBadge, ScoreBar, ScoreValue, StageBadge } from "@/components/kcp/ui";
import { fmtPct, titleCase } from "@/lib/format";
import { timeAgo } from "@/lib/time";
import { useApi } from "@/lib/useApi";
import type { DashboardSummary, FreshnessReport, IpoSummary, MethodologyResponse, Paged } from "@/lib/types";

const CAPABILITIES = [
  { icon: FileSearch, title: "Automatic discovery", body: "Every NSE mainboard and SME issue from NSE's public issue data, plus draft and red herring prospectuses filed with SEBI — refreshed on a schedule, never by hand." },
  { icon: Layers, title: "Prospectus extraction", body: "Restated balance sheet, P&L and cash flow read from the offer document (OCR for scanned pages), converted to ₹ crore and reconciled against accounting identities." },
  { icon: Gauge, title: "Quantitative engine", body: "Profitability, growth, balance-sheet strength, cash flow and valuation ratios with industry-aware applicability — lenders are not judged on current ratios." },
  { icon: ShieldCheck, title: "Provenance for every figure", body: "Each number links to its document, page and the text as printed. Missing data is shown as missing, with the reason — never as zero." },
  { icon: CalendarDays, title: "Calendar & outcomes", body: "Opening, closing, allotment, refund, demat-credit and listing dates with confirmed/estimated status, and listing-day outcomes from the official bhavcopy." },
  { icon: BookOpenText, title: "Published methodology", body: "Weights, reference ranges and thresholds live in a versioned configuration. Scores are reproducible and every input is inspectable." },
];

export default function Home() {
  const summary = useApi<DashboardSummary>("/api/dashboard/summary");
  const fresh = useApi<FreshnessReport>("/api/data/freshness");
  const method = useApi<MethodologyResponse>("/api/methodology");
  const example = useApi<Paged<IpoSummary>>("/api/ipos?scored_only=true&sort=-completeness&page_size=1&data_mode=source");
  const t = summary.data?.totals;
  const ex = example.data?.items[0];
  const W = method.data?.config.weights.overall;

  return (
    <div className="min-h-screen bg-canvas">
      <Navbar />
      <main id="main">
        {/* proposition */}
        <section className="border-b border-line">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 lg:grid-cols-5 lg:py-20">
            <div className="lg:col-span-3">
              <p className="text-xs font-medium uppercase tracking-[0.16em] text-brand-ink">Indian IPO research · NSE mainboard &amp; SME</p>
              <h1 className="mt-4 text-4xl font-semibold leading-[1.1] tracking-tight text-ink sm:text-5xl">
                IPO analysis built from the prospectus up.
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-7 text-ink-2">
                KcpInsights discovers Indian IPOs automatically, reads the restated financial statements in each offer document, checks them
                against accounting identities and scores them with a published, versioned methodology. Every figure traces back to its page;
                every gap says why it is a gap.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link href="/ipos" className="inline-flex items-center gap-2 rounded-md bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand/85">
                  Explore IPOs <ArrowRight className="size-4" aria-hidden />
                </Link>
                <Link href="/methodology" className="inline-flex items-center gap-2 rounded-md border border-line-strong px-4 py-2.5 text-sm font-medium text-ink hover:bg-surface-3">
                  How the scores work
                </Link>
              </div>
            </div>
            <div className="lg:col-span-2">
              <div className="rounded-xl border border-line bg-surface p-5">
                <p className="text-[11px] font-medium uppercase tracking-wider text-ink-3">From the live database</p>
                <dl className="mt-3 grid grid-cols-2 gap-4">
                  {[
                    ["IPOs on record", t ? String(t.ipos) : "—"],
                    ["Open now", t ? String(t.by_status.open ?? 0) : "—"],
                    ["Prospectuses read", t ? `${t.documents_extracted}/${t.documents}` : "—"],
                    ["IPOs scored", t ? String(t.scored) : "—"],
                  ].map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-xs text-ink-3">{k}</dt>
                      <dd className="mt-0.5 text-2xl font-semibold tabular-nums text-ink">{v}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-4 border-t border-line pt-3 text-xs text-ink-3">
                  {fresh.data?.last_successful_sync_at ? <>Last successful sync {timeAgo(fresh.data.last_successful_sync_at)} · sources: NSE, SEBI</>
                    : summary.error ? "The API is not reachable — start the backend to see live figures." : "Loading…"}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* capabilities */}
        <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">What the platform does</h2>
          <div className="mt-6 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
            {CAPABILITIES.map((c) => (
              <div key={c.title} className="bg-surface p-5">
                <c.icon className="size-5 text-brand-ink" aria-hidden />
                <h3 className="mt-3 text-[15px] font-semibold text-ink">{c.title}</h3>
                <p className="mt-1.5 text-sm leading-6 text-ink-2">{c.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* methodology + example */}
        <section className="border-y border-line bg-surface/40">
          <div className="mx-auto grid max-w-6xl gap-8 px-4 py-14 sm:px-6 lg:grid-cols-2">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-ink">Research methodology</h2>
              <p className="mt-2 text-sm leading-6 text-ink-2">
                The fundamental score Q is a weighted average of five component scores, each built from standard ratios normalised to 0–100.
                Risk is scored separately. Weights below are read from the active configuration{method.data ? ` (v${method.data.active_version})` : ""}.
              </p>
              <div className="mt-5 rounded-lg border border-line bg-canvas p-4 font-mono text-[13px] text-ink">
                Q = {W ? Object.entries(W).map(([k, w]) => `${w.toFixed(2)}·${titleCase(k).replace("Financial Health", "Health").replace("Cash Flow", "CashFlow")}`).join(" + ") : "…"}
              </div>
              <ul className="mt-5 space-y-2 text-sm text-ink-2">
                <li>• Only statements that pass accounting checks are scored; consolidated and standalone figures are never mixed.</li>
                <li>• Ratios that do not fit a business model (e.g. EBITDA for lenders) are marked not applicable, not penalised.</li>
                <li>• A score is issued only when enough inputs exist; otherwise it is shown as incomplete with the reason.</li>
                <li>• Data completeness is reported separately and is never a confidence level or a probability of returns.</li>
              </ul>
              <Link href="/methodology" className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-brand-ink hover:underline">
                Every formula, weight and threshold <ArrowRight className="size-4" aria-hidden />
              </Link>
            </div>
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-ink">Example analysis</h2>
              <p className="mt-2 text-sm leading-6 text-ink-2">The real IPO with the most complete data on record right now — not a curated example.</p>
              {ex ? (
                <Link href={`/ipos/${ex.id}`} className="mt-5 block rounded-xl border border-line bg-surface p-5 transition hover:border-line-strong">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-ink">{ex.company_name}</p>
                      <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-3">{ex.sector} · {ex.issue_type === "sme" ? "SME" : "Mainboard"} <StageBadge stage={ex.stage} /></p>
                    </div>
                    <div className="text-right">
                      <p className="text-[11px] uppercase tracking-wider text-ink-3">Fundamental score</p>
                      <p className="text-2xl"><ScoreValue value={ex.scores?.composite} /></p>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <ScoreBar label="Profitability" value={ex.scores?.profitability} />
                    <ScoreBar label="Growth" value={ex.scores?.growth} />
                    <ScoreBar label="Financial health" value={ex.scores?.financial_health} />
                    <ScoreBar label="Valuation" value={ex.scores?.valuation} />
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3 text-xs text-ink-3">
                    <RiskBadge level={ex.scores?.risk_level ?? null} />
                    <span>Data completeness</span><CompletenessMeter value={ex.completeness_pct} />
                    <span>{ex.scores?.classification ?? ""}</span>
                  </div>
                </Link>
              ) : (
                <p className="mt-5 rounded-xl border border-dashed border-line p-5 text-sm text-ink-3">{example.loading ? "Loading…" : "No scored IPO yet."}</p>
              )}
            </div>
          </div>
        </section>

        {/* data sources */}
        <section id="sources" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">Data sources, stated plainly</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-2">
            Only official sources are read automatically, through their public pages and files, one request at a time. Nothing bypasses
            authentication, CAPTCHAs or rate limits; where a source refuses automated access, that is shown here rather than worked around.
          </p>
          <div className="mt-6 overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-surface-2 text-left text-[11px] uppercase tracking-wider text-ink-3">
                <tr><th className="px-3 py-2.5 font-medium">Source</th><th className="px-3 py-2.5 font-medium">Access</th><th className="px-3 py-2.5 font-medium">Status</th><th className="px-3 py-2.5 font-medium">What it provides</th></tr>
              </thead>
              <tbody>
                {(fresh.data?.sources ?? []).map((s) => (
                  <tr key={s.key} className="border-t border-line align-top">
                    <td className="px-3 py-2.5 font-medium text-ink">{s.name}</td>
                    <td className="px-3 py-2.5 text-ink-2">{s.access_mode === "automatic" ? "Automatic" : "Manual import"}</td>
                    <td className={`px-3 py-2.5 ${s.health_status === "healthy" ? "text-pos-ink" : s.health_status === "manual" ? "text-ink-3" : "text-warn-ink"}`}>
                      {s.health_status}{s.last_success_at ? ` · ${timeAgo(s.last_success_at)}` : ""}
                    </td>
                    <td className="px-3 py-2.5 text-xs leading-5 text-ink-3">{s.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {summary.data && (
            <p className="mt-3 text-xs text-ink-3">
              Median data completeness across IPOs on record: {fmtPct(summary.data.data_health?.median_completeness, 0)}. Details per IPO on each research page.
            </p>
          )}
        </section>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-start justify-between gap-6 px-4 py-8 sm:px-6">
          <Disclaimer className="max-w-2xl" />
          <div className="flex gap-5 text-sm text-ink-2">
            <Link href="/dashboard" className="hover:text-ink">Dashboard</Link>
            <Link href="/methodology" className="hover:text-ink">Methodology</Link>
            <Link href="/data" className="hover:text-ink">System health</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
