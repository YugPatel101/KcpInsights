"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { Brain, FileText, Star } from "lucide-react";
import DocumentsPanel from "@/components/ipo/DocumentsPanel";
import FinancialsPanel from "@/components/ipo/FinancialsPanel";
import ScenarioPanel from "@/components/ipo/ScenarioPanel";
import ScoreBreakdown from "@/components/ipo/ScoreBreakdown";
import SourcesPanel from "@/components/ipo/SourcesPanel";
import {
  DataStatusBadge,
  Disclaimer,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Notice,
  PageHeader,
  Panel,
  RiskBadge,
  ScoreValue,
  Spinner,
  Stat,
  StatusBadge,
  Tabs,
  buttonClass,
  inputClass,
} from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtCr, fmtDate, fmtDateTime, fmtInr, fmtInt, fmtNum, fmtPct, priceBand, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { IpoDetail, Prediction, ScoreResult } from "@/lib/types";

type Tab = "overview" | "financials" | "scores" | "scenarios" | "risks" | "documents" | "sources";

export default function IpoPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const ipoId = Number(id);
  const router = useRouter();
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const detail = useApi<IpoDetail>(Number.isInteger(ipoId) && ipoId > 0 ? `/api/ipos/${ipoId}?u=${user?.id ?? 0}` : null);
  const scores = useApi<ScoreResult>(tab === "scores" ? `/api/ipos/${ipoId}/scores` : null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  if (!Number.isInteger(ipoId) || ipoId <= 0) return <ErrorState message="Invalid IPO id" />;
  if (detail.error) return <ErrorState message={detail.error} onRetry={detail.reload} />;
  if (detail.loading && !detail.data) return <LoadingBlock rows={8} />;
  const d = detail.data;
  if (!d) return null;
  const s = d.scores;

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
    setActionMsg("Generating report… with a local model this can take up to a minute.");
    try {
      const r = await api<{ id: number }>("/api/reports/generate", { body: { ipo_id: ipoId, use_ai: true } });
      router.push(`/reports/${r.id}`);
    } catch (e) {
      setActionMsg(errorMessage(e));
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow={<Link href="/ipos" className="hover:text-slate-300">← IPOs</Link>}
        title={d.company_name}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {d.sector}{d.industry ? ` · ${d.industry}` : ""} · {d.exchange} · {d.issue_type === "sme" ? "SME" : "Mainboard"}
            <StatusBadge status={d.status} />
            <DataStatusBadge status={d.data_status} />
          </span>
        }
        actions={
          <>
            <button onClick={toggleWatch} className={buttonClass.secondary} disabled={busy === "watch"} aria-pressed={d.watchlisted}>
              <Star className={`size-4 ${d.watchlisted ? "fill-amber-300 text-amber-300" : ""}`} aria-hidden /> {d.watchlisted ? "Watching" : "Watch"}
            </button>
            <Link href={`/workspace?ipo=${ipoId}`} className={buttonClass.secondary}><Brain className="size-4" aria-hidden /> Ask AI</Link>
            <button onClick={generateReport} className={buttonClass.primary} disabled={busy === "report"}>
              {busy === "report" ? <Spinner /> : <FileText className="size-4" aria-hidden />} Generate report
            </button>
          </>
        }
      />
      {actionMsg && <div className="mb-4"><Notice>{actionMsg}</Notice></div>}
      {d.data_mode === "demo" && (
        <div className="mb-6">
          <Notice tone="synthetic">
            <strong>Synthetic demonstration IPO.</strong> The company, financials, peers and disclosures are fictional. Use it to explore the
            product; do not treat any figure as a real fact.
          </Notice>
        </div>
      )}

      <div className="mb-8 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Research score" value={<ScoreValue value={s.composite} />} hint={s.status === "complete" ? `config v${s.config_version}` : "incomplete"} />
        <Stat label="Quality" value={<ScoreValue value={s.quality} />} />
        <Stat label="Valuation" value={<ScoreValue value={s.valuation} />} hint={s.valuation_multiple ? `${s.valuation_multiple} ${fmtNum(s.ipo_multiple)}x` : "unavailable"} />
        <Stat label="Risk" value={fmtNum(s.risk, 1)} hint={<RiskBadge level={s.risk_level} />} />
        <Stat label="Evidence coverage" value={fmtPct(s.coverage, 0)} hint="not a probability" />
        <Stat label="Price band" value={priceBand(d.price_band_low, d.price_band_high)} hint={d.lot_size ? `lot ${d.lot_size} · min ${fmtInr(d.min_investment_inr, 0)}` : undefined} />
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "financials", label: "Financials" },
          { id: "scores", label: "Quant scores" },
          { id: "scenarios", label: "Scenarios" },
          { id: "risks", label: "Risks & disclosures" },
          { id: "documents", label: `Documents (${d.documents.length})` },
          { id: "sources", label: "Sources" },
        ]}
      />

      {tab === "overview" && <Overview d={d} onSaved={detail.reload} />}
      {tab === "financials" && <FinancialsPanel ipoId={ipoId} />}
      {tab === "scores" && (scores.error ? <ErrorState message={scores.error} onRetry={scores.reload} /> : scores.data ? <ScoreBreakdown r={scores.data} /> : <LoadingBlock rows={6} />)}
      {tab === "scenarios" && <ScenarioPanel ipoId={ipoId} />}
      {tab === "risks" && <Risks d={d} />}
      {tab === "documents" && <DocumentsPanel ipoId={ipoId} documents={d.documents} onChange={detail.reload} />}
      {tab === "sources" && <SourcesPanel ipoId={ipoId} />}

      <Disclaimer className="mt-10" />
    </>
  );
}

function Overview({ d, onSaved }: { d: IpoDetail; onSaved: () => void }) {
  const prediction = useApi<Prediction>(`/api/ipos/${d.id}/prediction`);
  const subs = d.subscription;
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Panel title="Business">
          <p className="text-sm leading-7 text-slate-300">{d.description ?? <span className="text-slate-500">Business description unavailable.</span>}</p>
          <p className="mt-3 text-sm leading-7 text-slate-300"><span className="text-slate-500">Business model: </span>{d.business_model ?? "unavailable"}</p>
          {d.revenue_sources && d.revenue_sources.length > 0 && (
            <div className="mt-4">
              <h3 className="mb-2 text-xs uppercase tracking-wider text-slate-500">Revenue sources</h3>
              <div className="space-y-2">
                {d.revenue_sources.map((r) => (
                  <div key={r.segment} className="flex items-center gap-3 text-sm">
                    <span className="w-48 shrink-0 truncate text-slate-300">{r.segment}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-white/[0.06]"><div className="h-1.5 rounded-full bg-[#3987e5]" style={{ width: `${r.share_pct}%` }} /></div>
                    <span className="w-12 text-right tabular-nums text-slate-400">{r.share_pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {d.customer_concentration_pct !== null && (
            <p className="mt-4 text-sm text-slate-400">Disclosed customer concentration: <span className="text-slate-200">{fmtPct(d.customer_concentration_pct, 0)}</span> of revenue from top customers.</p>
          )}
        </Panel>

        <Panel title="Issue structure">
          <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
            {[
              ["Opens / closes", `${fmtDate(d.open_date)} – ${fmtDate(d.close_date)}`],
              ["Listing date", fmtDate(d.listing_date)],
              ["Issue size", fmtCr(d.issue_size_cr)],
              ["Fresh issue / OFS", `${fmtCr(d.fresh_issue_cr)} / ${fmtCr(d.ofs_cr)}`],
              ["Final issue price", fmtInr(d.final_issue_price)],
              ["Face value", fmtInr(d.face_value)],
              ["Pre / post-issue shares", `${fmtInt(d.pre_issue_shares)} / ${fmtInt(d.post_issue_shares)}`],
              ["Dilution from fresh issue", fmtPct(d.dilution_pct, 2)],
              ["Promoter holding pre → post", `${fmtPct(d.promoter_holding_pre_pct)} → ${fmtPct(d.promoter_holding_post_pct)}`],
              ["Listing price", d.listing_price !== null ? `${fmtInr(d.listing_price)} (${fmtPct(d.listing_return_pct, 1, true)})` : "—"],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 border-b border-white/5 py-1.5"><dt className="text-slate-400">{k}</dt><dd className="text-right tabular-nums text-slate-200">{v}</dd></div>
            ))}
          </dl>
          {d.use_of_proceeds && d.use_of_proceeds.length > 0 && (
            <div className="mt-5">
              <h3 className="mb-2 text-xs uppercase tracking-wider text-slate-500">Use of fresh-issue proceeds</h3>
              <ul className="space-y-1 text-sm">
                {d.use_of_proceeds.map((u) => (
                  <li key={u.purpose} className="flex justify-between gap-4"><span className="text-slate-300">{u.purpose}</span><span className="tabular-nums text-slate-400">{fmtCr(u.amount_cr)}</span></li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
        <ResearchNotes d={d} onSaved={onSaved} />
      </div>

      <div className="space-y-6">
        <Panel title="Subscription" subtitle={subs ? `as of ${fmtDateTime(subs.as_of)}` : undefined}>
          {subs ? (
            <dl className="space-y-1.5 text-sm">
              {Object.entries(subs.categories).map(([k, v]) => (
                <div key={k} className="flex justify-between"><dt className="text-slate-400">{k === "nii" ? "NII" : k === "qib" ? "QIB" : titleCase(k)}</dt><dd className="tabular-nums text-slate-200">{fmtNum(v, 2)}x</dd></div>
              ))}
              <div className="pt-2"><DataStatusBadge status={subs.data_status[0]} /></div>
            </dl>
          ) : (
            <p className="text-sm text-slate-500">No subscription data stored. Figures are only shown when sourced.</p>
          )}
        </Panel>

        <Panel title="Grey-market premium">
          <p className="mb-3 text-xs leading-5 text-amber-200/80">{d.grey_market.caveat}</p>
          {d.grey_market.observations.length ? (
            <ul className="space-y-1 text-sm">
              {d.grey_market.observations.map((g) => (
                <li key={g.observed_at} className="flex items-center justify-between gap-2"><span className="text-slate-400">{fmtDateTime(g.observed_at)}</span><span className="tabular-nums text-slate-200">{fmtInr(g.premium_inr, 0)}</span><DataStatusBadge status={g.data_status} compact /></li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">None stored.</p>
          )}
        </Panel>

        <Panel title="Listing-outcome model">
          {prediction.data?.available ? (
            <div className="text-sm text-slate-300">
              <p>P(listing return &gt; threshold): <span className="tabular-nums text-white">{fmtPct((prediction.data.probability_positive ?? 0) * 100, 0)}</span></p>
              <p>Expected return: {fmtPct(prediction.data.expected_return_pct, 1, true)} · model {prediction.data.model_version}</p>
            </div>
          ) : (
            <p className="text-sm text-slate-400">{prediction.data?.reason ?? "Checking…"}</p>
          )}
          <p className="mt-3 text-xs leading-5 text-slate-500">{prediction.data?.warning}</p>
        </Panel>

        {d.source && (
          <Panel title="Primary source">
            <p className="text-sm text-slate-300">{d.source.url ? <a className="text-sky-300 hover:underline" href={d.source.url} target="_blank" rel="noopener noreferrer">{d.source.title}</a> : d.source.title}</p>
            <p className="mt-1 text-xs text-slate-500">Retrieved {fmtDateTime(d.source.retrieved_at)} · last updated {fmtDateTime(d.last_updated)}</p>
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
      <Panel title="Research notes"><p className="whitespace-pre-wrap text-sm leading-6 text-slate-300">{d.research_notes}</p></Panel>
    ) : null;
  }
  return (
    <Panel title="Research notes" subtitle="Editable because you imported this IPO. Changes are audit-logged.">
      <textarea className={`${inputClass} min-h-28`} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={5000} aria-label="Research notes" />
      <label className="mt-3 flex items-center gap-2 text-sm text-slate-300">
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
        {msg && <span className="text-sm text-slate-400" role="status">{msg}</span>}
      </div>
    </Panel>
  );
}

function Risks({ d }: { d: IpoDetail }) {
  const confirmed = d.disclosures.filter((x) => x.status === "confirmed_disclosure");
  const unresolved = d.disclosures.filter((x) => x.status !== "confirmed_disclosure");
  const sev = (s: string) => (s === "high" ? "text-rose-300" : s === "medium" ? "text-amber-300" : "text-slate-300");
  return (
    <div className="space-y-6">
      {!d.risk_disclosures_reviewed && !d.disclosures.length && (
        <Notice tone="warn">Risk disclosures have not been reviewed for this IPO. The absence of recorded risks is <strong>not</strong> evidence that none exist.</Notice>
      )}
      {[["Confirmed disclosures", confirmed, "Stated in the offer document or official filings."], ["Unresolved concerns", unresolved, "Flagged for follow-up; not confirmed. Weighted at half severity in the risk score."]].map(([title, list, sub]) => (
        <Panel key={title as string} title={title as string} subtitle={sub as string}>
          {(list as IpoDetail["disclosures"]).length ? (
            <ul className="divide-y divide-white/5">
              {(list as IpoDetail["disclosures"]).map((x) => (
                <li key={x.id} className="py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-100">{x.title}</span>
                    <span className={`text-xs uppercase ${sev(x.severity)}`}>{x.severity}</span>
                    <span className="text-xs text-slate-500">{titleCase(x.category)}</span>
                    <DataStatusBadge status={x.data_status} compact />
                  </div>
                  <p className="mt-1 leading-6 text-slate-400">{x.description}</p>
                  {x.amount_cr !== null && <p className="text-xs text-slate-500">Amount: {fmtCr(x.amount_cr)}</p>}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="None recorded" />
          )}
        </Panel>
      ))}
    </div>
  );
}
