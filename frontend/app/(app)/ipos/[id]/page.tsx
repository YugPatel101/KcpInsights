"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Star } from "lucide-react";
import CompletenessPanel from "@/components/ipo/CompletenessPanel";
import DocumentsPanel from "@/components/ipo/DocumentsPanel";
import PeersPanel from "@/components/ipo/PeersPanel";
import KeyDates from "@/components/live/KeyDates";
import ProvenancePanel from "@/components/live/ProvenancePanel";
import SubscriptionTable from "@/components/live/SubscriptionTable";
import FinancialsPanel from "@/components/ipo/FinancialsPanel";
import IssueFactsPanel from "@/components/ipo/IssueFactsPanel";
import RatiosPanel from "@/components/ipo/RatiosPanel";
import RiskPanel from "@/components/ipo/RiskPanel";
import ScoreBreakdown from "@/components/ipo/ScoreBreakdown";
import ValuationPanel from "@/components/ipo/ValuationPanel";
import SourcesPanel from "@/components/ipo/SourcesPanel";
import {
  DataStatusBadge,
  Disclaimer,
  KV,
  ErrorState,
  LoadingBlock,
  Notice,
  PageHeader,
  Panel,
  ReadinessBadge,
  RiskBadge,
  ScoreValue,
  Spinner,
  Stat,
  StageBadge,
  Tabs,
  buttonClass,
  inputClass,
} from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PROFILE_LABEL, fmtCr, fmtDate, fmtDateTime, fmtInr, fmtNum, fmtPct, returnTone } from "@/lib/format";
import { timeAgo } from "@/lib/time";
import { useApi } from "@/lib/useApi";
import type { IpoDetail, ScoreResult } from "@/lib/types";

type Tab = "overview" | "financials" | "ratios" | "valuation" | "peers" | "risk" | "scores" | "completeness" | "documents" | "sources";

export default function IpoPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const ipoId = Number(id);
  const router = useRouter();
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [pollMs, setPollMs] = useState<number>(180_000);
  // database polling only: open issues refresh every minute, others every 3 minutes
  const detail = useApi<IpoDetail>(Number.isInteger(ipoId) && ipoId > 0 ? `/api/ipos/${ipoId}?u=${user?.id ?? 0}` : null, { refreshMs: pollMs });
  const scores = useApi<ScoreResult>(["scores", "valuation", "risk"].includes(tab) ? `/api/ipos/${ipoId}/scores` : null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  if (!Number.isInteger(ipoId) || ipoId <= 0) return <ErrorState message="Invalid IPO id" />;
  if (detail.error) return <ErrorState message={detail.error} onRetry={detail.reload} />;
  if (detail.loading && !detail.data) return <LoadingBlock rows={8} />;
  const d = detail.data;
  if (!d) return null;
  const s = d.scores;
  const wantPoll = d.status === "open" ? 60_000 : 180_000;
  if (wantPoll !== pollMs) setPollMs(wantPoll);

  const toggleWatch = async () => {
    if (!user) return router.push(`/login?next=/ipos/${ipoId}`);
    setBusy("watch");
    try {
      await api(`/api/ipos/${ipoId}/watch`, { method: d.watchlisted ? "DELETE" : "POST" });
      detail.setData({ ...d, watchlisted: !d.watchlisted });
    } catch (e) {
      setActionMsg(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const generateReport = async () => {
    if (!user) return router.push(`/login?next=/ipos/${ipoId}`);
    setBusy("report");
    setActionMsg("Generating report…");
    try {
      const r = await api<{ id: number }>("/api/reports/generate", { body: { ipo_id: ipoId } });
      router.push(`/reports/${r.id}`);
    } catch (e) {
      setActionMsg(errorMessage(e));
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow={<Link href="/ipos" className="hover:text-ink-2">← IPOs</Link>}
        title={d.company_name}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {d.sector} · {d.exchange} · {d.issue_type === "sme" ? "SME" : "Mainboard"}
            <StageBadge stage={d.stage} />
            <DataStatusBadge status={d.data_status} />
          </span>
        }
        actions={
          <>
            <button onClick={toggleWatch} className={buttonClass.secondary} disabled={busy === "watch"} aria-pressed={d.watchlisted}>
              <Star className={`size-4 ${d.watchlisted ? "fill-amber-300 text-warn-ink" : ""}`} aria-hidden /> {d.watchlisted ? "Watching" : "Watch"}
            </button>
            <button onClick={generateReport} className={buttonClass.primary} disabled={busy === "report"}>
              {busy === "report" ? <Spinner /> : <FileText className="size-4" aria-hidden />} Generate report
            </button>
          </>
        }
      />
      {actionMsg && <div className="mb-4"><Notice>{actionMsg}</Notice></div>}
      {d.freshness.live && (
        <p className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
          <span className="inline-flex items-center gap-1.5"><span className={`size-2 rounded-full ${d.freshness.is_stale ? "bg-warn" : "bg-pos"}`} aria-hidden />
            Record from {d.source?.url ? <a href={d.source.url} target="_blank" rel="noopener noreferrer" className="text-brand-ink hover:underline">NSE</a> : "NSE"}{d.nse_symbol ? ` (${d.nse_symbol})` : ""}</span>
          <span>last verified {timeAgo(d.freshness.last_verified_at)}</span>
          {detail.refreshing && <span>refreshing…</span>}
        </p>
      )}
      {d.freshness.is_stale && <div className="mb-4"><Notice tone="warn">Possibly out of date: {d.freshness.stale_reasons.join("; ")}. Showing the last known values.</Notice></div>}
      {d.data_mode === "demo" && (
        <div className="mb-6">
          <Notice tone="synthetic">
            <strong>Synthetic demonstration IPO.</strong> The company, financials, peers and disclosures are fictional. Use it to explore the
            product; do not treat any figure as a real fact.
          </Notice>
        </div>
      )}

      {d.status === "pipeline" && (
        <div className="mb-4"><Notice>Offer document filed with SEBI; NSE has not announced issue dates or a price band yet. Financial analysis is built from the filed document.</Notice></div>
      )}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Fundamental score" value={<ScoreValue value={s.composite} />} hint={s.classification ?? (s.status === "insufficient" ? "insufficient data" : "—")} />
        <Stat label="Profitability · Growth" value={<span className="flex gap-2"><ScoreValue value={s.profitability} /><span className="text-ink-3">·</span><ScoreValue value={s.growth} /></span>} />
        <Stat label="Health · Cash flow" value={<span className="flex gap-2"><ScoreValue value={s.financial_health} /><span className="text-ink-3">·</span><ScoreValue value={s.cash_flow} /></span>} />
        <Stat label="Valuation" value={<ScoreValue value={s.valuation} />} hint={s.pe !== null ? `P/E ${fmtNum(s.pe, 1)}x${s.price_status === "estimated" ? " (upper band)" : ""}` : "unavailable"} />
        <Stat label="Risk" value={fmtNum(s.risk, 1)} hint={<RiskBadge level={s.risk_level} />} />
        <Stat label="Data completeness" value={d.completeness_pct !== null && d.completeness_pct !== undefined ? `${Math.round(d.completeness_pct)}%` : "—"}
              hint={<span className="flex flex-wrap items-center gap-1.5"><ReadinessBadge level={d.completeness?.readiness} />{s.latest_period ? <span>{s.basis} · {s.latest_period}</span> : null}</span>} />
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "financials", label: "Financial statements" },
          { id: "ratios", label: "Ratios & trends" },
          { id: "valuation", label: "Valuation" },
          { id: "peers", label: `Peers (${d.peers.length})` },
          { id: "risk", label: "Risk" },
          { id: "scores", label: "Score breakdown" },
          { id: "completeness", label: "Data completeness" },
          { id: "documents", label: `Documents (${d.documents.length})` },
          { id: "sources", label: "Sources" },
        ]}
      />

      {tab === "overview" && <Overview d={d} onSaved={detail.reload} />}
      {tab === "financials" && <FinancialsPanel ipoId={ipoId} />}
      {tab === "ratios" && <RatiosPanel ipoId={ipoId} />}
      {["scores", "valuation", "risk"].includes(tab) && scores.error && <ErrorState message={scores.error} onRetry={scores.reload} />}
      {["scores", "valuation", "risk"].includes(tab) && !scores.error && !scores.data && <LoadingBlock rows={6} />}
      {tab === "scores" && scores.data && <ScoreBreakdown r={scores.data} />}
      {tab === "valuation" && scores.data && <ValuationPanel d={d} r={scores.data} />}
      {tab === "risk" && scores.data && <RiskPanel d={d} r={scores.data} />}
      {tab === "peers" && <PeersPanel ipoId={ipoId} />}
      {tab === "completeness" && <CompletenessPanel ipoId={ipoId} />}
      {tab === "documents" && <DocumentsPanel ipoId={ipoId} documents={d.documents} onChange={detail.reload} />}
      {tab === "sources" && (
        <div className="space-y-6">
          <ProvenancePanel ipoId={ipoId} />
          <SourcesPanel ipoId={ipoId} />
        </div>
      )}

      <Disclaimer className="mt-10" />
    </>
  );
}

function Overview({ d, onSaved }: { d: IpoDetail; onSaved: () => void }) {
  const objects = (d.document_facts as Record<string, { page?: number | null; document_id?: number | null } | undefined>).objects_of_issue;
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Panel title="Business" subtitle={d.document_facts.business_overview ? "The company's own description, quoted from its offer document" : undefined}>
          {d.document_facts.business_overview ? (
            <blockquote className="border-l-2 border-line-strong pl-4 text-sm leading-7 text-ink-2">
              {String(d.document_facts.business_overview.value)}
              <footer className="mt-1 text-xs text-ink-3">— offer document, <a className="text-brand-ink hover:underline" href={`/api/documents/${d.document_facts.business_overview.document_id}/file#page=${d.document_facts.business_overview.page}`} target="_blank" rel="noopener noreferrer">p{d.document_facts.business_overview.page}</a></footer>
            </blockquote>
          ) : (
            <p className="text-sm leading-7 text-ink-2">{d.description ?? <span className="text-ink-3">No business description on record: the offer document&apos;s overview could not be located automatically.</span>}</p>
          )}
          {d.business_model && <p className="mt-3 text-sm leading-7 text-ink-2"><span className="text-ink-3">Business model: </span>{d.business_model}</p>}
          {d.revenue_sources && d.revenue_sources.length > 0 && (
            <div className="mt-4">
              <h3 className="mb-2 text-xs uppercase tracking-wider text-ink-3">Revenue sources</h3>
              <div className="space-y-2">
                {d.revenue_sources.map((r) => (
                  <div key={r.segment} className="flex items-center gap-3 text-sm">
                    <span className="w-48 shrink-0 truncate text-ink-2">{r.segment}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-surface-3"><div className="h-1.5 rounded-full bg-[#3987e5]" style={{ width: `${r.share_pct}%` }} /></div>
                    <span className="w-12 text-right tabular-nums text-ink-2">{r.share_pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {d.customer_concentration_pct !== null && (
            <p className="mt-4 text-sm text-ink-2">Disclosed customer concentration: <span className="text-ink">{fmtPct(d.customer_concentration_pct, 0)}</span> of revenue from top customers.</p>
          )}
        </Panel>

        <Panel title="Industry classification" subtitle="NSE publishes no sector; it is read from the offer document's business sections">
          {d.classification ? (
            <>
              <KV rows={[
                ["Sector", d.classification.status === "extracted" ? d.classification.sector : "Unclassified"],
                ["Analysis profile", PROFILE_LABEL[d.industry_profile ?? "general"] ?? d.industry_profile],
                ["Lead over runner-up", d.classification.runner_up ? `${Math.round(d.classification.confidence * 100)}% of the top-two evidence (vs ${d.classification.runner_up})` : "—"],
              ]} />
              {d.classification.note && <p className="mt-2 text-xs text-ink-3">{d.classification.note}</p>}
              {d.classification.evidence.length > 0 && (
                <p className="mt-3 text-xs leading-5 text-ink-3">
                  Evidence: {d.classification.evidence.slice(0, 4).map((e) => `“${e.phrase}” ×${e.count}${e.pages.length ? ` (p${e.pages.slice(0, 3).join(", ")})` : ""}`).join(" · ")}
                </p>
              )}
              <p className="mt-2 text-xs text-ink-3">The profile decides which ratios apply — for lenders, current ratio, EBITDA and cash-flow ratios are marked not applicable instead of being scored.</p>
            </>
          ) : <p className="text-sm text-ink-3">{d.sector === "Unclassified" ? "Not classified yet: the offer document has not been read." : `${d.sector} (from ${d.data_mode === "demo" ? "the synthetic fixture" : "an import"}).`}</p>}
          {d.document_facts.lender_kpis && (
            <div className="mt-4">
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-ink-3">Lender KPIs as printed (unverified, not scored)</h3>
              <ul className="space-y-1 text-sm">
                {Object.entries(d.document_facts.lender_kpis.value).map(([k, v]) => (
                  <li key={k} className="flex flex-wrap justify-between gap-2"><span className="text-ink-2">{v.label}</span>
                    <span className="tabular-nums text-ink">{v.values_as_printed.join(" · ")} <a className="ml-1 text-xs text-brand-ink hover:underline" href={`/api/documents/${d.document_facts.lender_kpis?.document_id}/file#page=${v.page}`} target="_blank" rel="noopener noreferrer">p{v.page}</a></span></li>
                ))}
              </ul>
            </div>
          )}
        </Panel>

        {d.issue_facts ? <IssueFactsPanel d={d} /> : null}

        <Panel title="Objects of the issue"
               subtitle={objects ? <>As listed in the offer document{objects.page ? <>, <a className="text-brand-ink hover:underline" href={`/api/documents/${objects.document_id}/file#page=${objects.page}`} target="_blank" rel="noopener noreferrer">p{objects.page}</a></> : null}; amounts in ₹ crore where the table prints one</> : undefined}>
          {d.use_of_proceeds && d.use_of_proceeds.length > 0 ? (
            <ol className="space-y-2 text-sm">
              {d.use_of_proceeds.map((u, i) => (
                <li key={`${i}-${u.purpose}`} className="flex justify-between gap-4 border-b border-line pb-2 last:border-0">
                  <span className="text-ink-2"><span className="mr-2 text-ink-3">{i + 1}.</span>{u.purpose}</span>
                  <span className="shrink-0 tabular-nums text-ink">{u.amount_cr !== null ? fmtCr(u.amount_cr, 2) : <span className="text-xs text-ink-3">not fixed yet</span>}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-ink-3">
              {d.status === "pipeline" || d.documents.length === 0 ? "Read from the offer document once it is available."
                : "Not found in a readable form in the offer document's 'Objects of the Issue' chapter."}
            </p>
          )}
        </Panel>
        <ResearchNotes d={d} onSaved={onSaved} />
      </div>

      <div className="space-y-6">
        <KeyDates ipoId={d.id} dates={d.key_dates} />
        <SubscriptionTable ipoId={d.id} live={d.status === "open"} />

        <Panel title="Listing outcome" subtitle={d.status === "listed" ? "From the NSE bhavcopy on the listing day" : "Available after listing"}>
          {d.status === "listed" && d.listing_price !== null ? (
            <dl className="space-y-1.5 text-sm">
              <div className="flex justify-between"><dt className="text-ink-2">Listing date</dt><dd className="text-ink">{fmtDate(d.listing_date)}</dd></div>
              <div className="flex justify-between"><dt className="text-ink-2">Final issue price</dt><dd className="tabular-nums text-ink">{fmtInr(d.final_issue_price)}</dd></div>
              <div className="flex justify-between"><dt className="text-ink-2">Listing-day open</dt><dd className="tabular-nums text-ink">{fmtInr(d.listing_price)}</dd></div>
              <div className="flex justify-between"><dt className="text-ink-2">Listing-day close</dt><dd className="tabular-nums text-ink">{fmtInr(d.listing_close_price ?? null)}</dd></div>
              <div className="flex justify-between"><dt className="text-ink-2">Listing-day high / low</dt><dd className="tabular-nums text-ink">{fmtInr(d.listing_high_price ?? null)} / {fmtInr(d.listing_low_price ?? null)}</dd></div>
              <div className="flex justify-between"><dt className="text-ink-2">Listing gain (open vs issue)</dt><dd className={`tabular-nums ${returnTone(d.listing_return_pct)}`}>{fmtPct(d.listing_return_pct, 2, true)}</dd></div>
              <div className="flex justify-between"><dt className="text-ink-2">Listing-day close return</dt><dd className={`tabular-nums ${returnTone(d.listing_close_return_pct)}`}>{fmtPct(d.listing_close_return_pct ?? null, 2, true)}</dd></div>
            </dl>
          ) : <p className="text-sm text-ink-3">{d.status === "listed" ? "Listing price not yet available from the bhavcopy." : "The issue has not listed yet."}</p>}
        </Panel>

        <Panel title="Grey-market premium">
          <p className="mb-3 text-xs leading-5 text-warn-ink">{d.grey_market.caveat}</p>
          {d.grey_market.observations.length ? (
            <ul className="space-y-1 text-sm">
              {d.grey_market.observations.map((g) => (
                <li key={g.observed_at} className="flex items-center justify-between gap-2"><span className="text-ink-2">{fmtDateTime(g.observed_at)}</span><span className="tabular-nums text-ink">{fmtInr(g.premium_inr, 0)}</span><DataStatusBadge status={g.data_status} compact /></li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-3">None stored.</p>
          )}
        </Panel>

        {d.source && (
          <Panel title="Primary source">
            <p className="text-sm text-ink-2">{d.source.url ? <a className="text-brand-ink hover:underline" href={d.source.url} target="_blank" rel="noopener noreferrer">{d.source.title}</a> : d.source.title}</p>
            <p className="mt-1 text-xs text-ink-3">Retrieved {fmtDateTime(d.source.retrieved_at)} · last updated {fmtDateTime(d.last_updated)}</p>
          </Panel>
        )}
      </div>
    </div>
  );
}

function ResearchNotes({ d, onSaved }: { d: IpoDetail; onSaved: () => void }) {
  const [notes, setNotes] = useState(d.research_notes ?? "");
  const [reviewed, setReviewed] = useState(d.risk_disclosures_reviewed);
  const [msg, setMsg] = useState<string | null>(null);
  if (!d.can_edit) {
    return d.research_notes ? (
      <Panel title="Research notes"><p className="whitespace-pre-wrap text-sm leading-6 text-ink-2">{d.research_notes}</p></Panel>
    ) : null;
  }
  return (
    <Panel title="Research notes" subtitle="Editable because you imported this IPO. Changes are audit-logged.">
      <textarea className={`${inputClass} min-h-28`} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={5000} aria-label="Research notes" />
      <label className="mt-3 flex items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} /> I have reviewed the offer document&apos;s risk-factor section
      </label>
      <div className="mt-3 flex items-center gap-3">
        <button
          className={buttonClass.primary}
          onClick={async () => {
            try {
              await api(`/api/ipos/${d.id}`, { method: "PATCH", body: { research_notes: notes, risk_disclosures_reviewed: reviewed } });
              setMsg("Saved. Scores were recalculated.");
              onSaved();
            } catch (e) {
              setMsg(errorMessage(e));
            }
          }}
        >
          Save
        </button>
        {msg && <span className="text-sm text-ink-2" role="status">{msg}</span>}
      </div>
    </Panel>
  );
}
