"use client";

import Link from "next/link";
import { use } from "react";
import RequireAuth from "@/components/kcp/RequireAuth";
import { DataStatusBadge, ErrorState, LoadingBlock, Notice, PageHeader, Panel, RiskBadge, ScoreValue, Stat, buttonClass } from "@/components/kcp/ui";
import { fmtDateTime, fmtPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Report } from "@/lib/types";

function ReportView({ id }: { id: string }) {
  const { data: r, error, loading, reload } = useApi<Report>(`/api/reports/${encodeURIComponent(id)}`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !r) return <LoadingBlock rows={10} />;
  return (
    <article className="space-y-6 print:text-black">
      <PageHeader
        eyebrow={<Link href="/reports" className="hover:text-slate-300">← Reports</Link>}
        title={r.title}
        subtitle={`Generated ${fmtDateTime(r.created_at ?? r.generated_at)} · ${r.generator} · scoring config v${r.config_version}`}
        actions={
          <>
            <Link href={`/ipos/${r.ipo_id}`} className={buttonClass.secondary}>Open IPO</Link>
            <button className={buttonClass.secondary} onClick={() => window.print()}>Print / PDF</button>
          </>
        }
      />
      {r.synthetic && <Notice tone="synthetic">This report is about a <strong>synthetic demonstration IPO</strong>. All figures are fictional.</Notice>}
      <Notice>
        {r.llm.used ? `Narrative paragraphs marked “Model narrative” were written by ${r.llm.model} from engine facts and number-checked. ` : `Generated without a language model${r.llm.reason ? ` (${r.llm.reason})` : ""}: every sentence is templated from engine outputs. `}
        Numbers come from the deterministic scoring engine.
      </Notice>
      <div className="grid gap-3 sm:grid-cols-5">
        <Stat label="Research score" value={<ScoreValue value={r.scores.composite} />} hint={r.scores.status} />
        <Stat label="Quality" value={<ScoreValue value={r.scores.quality} />} />
        <Stat label="Valuation" value={<ScoreValue value={r.scores.valuation} />} />
        <Stat label="Risk" value={r.scores.risk?.toFixed(1) ?? "—"} hint={<RiskBadge level={r.scores.risk_level} />} />
        <Stat label="Evidence coverage" value={fmtPct(r.scores.coverage, 0)} />
      </div>
      {r.sections.map((s, n) => (
        <Panel key={s.key} title={`${n + 1}. ${s.title}`}>
          {s.narrative && (
            <div className="mb-3 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-sm leading-6 text-sky-100">
              <div className="mb-1 text-[11px] uppercase tracking-wider text-sky-300">Model narrative</div>
              {s.narrative}
            </div>
          )}
          <div className="space-y-2 text-sm leading-6 text-slate-300">
            {s.paragraphs.map((p, i) => <p key={i} className="whitespace-pre-wrap">{p}</p>)}
          </div>
          {s.facts.length > 0 && (
            <dl className="mt-4 grid gap-x-8 sm:grid-cols-2">
              {s.facts.map((f, i) => (
                <div key={i} className="flex justify-between gap-4 border-b border-white/5 py-1.5 text-sm">
                  <dt className="text-slate-400">{f.label}{f.excluded_reason ? <span className="block text-xs text-slate-600">excluded: {f.excluded_reason}</span> : null}{f.reasons ? <span className="block text-xs text-amber-300/80">{f.reasons.join("; ")}</span> : null}</dt>
                  <dd className="text-right tabular-nums text-slate-200">{f.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {s.evidence.length > 0 && <p className="mt-3 text-xs text-slate-500">Evidence: {s.evidence.map((e) => <a key={e} href={`#cite-${e}`} className="mr-1 font-mono text-sky-300 hover:underline">[{e}]</a>)}</p>}
        </Panel>
      ))}
      <Panel title="Citations">
        <ol className="space-y-1 text-sm">
          {r.citations.map((c) => (
            <li key={c.id} id={`cite-${c.id}`} className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-slate-400">[{c.id}]</span>
              {c.url ? <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-sky-300 hover:underline">{c.label}</a> : <span className="text-slate-300">{c.label}</span>}
              <span className="text-xs text-slate-500">{c.kind.replace("_", " ")}{c.ref_id !== null ? ` #${c.ref_id}` : ""}</span>
              {c.data_status && <DataStatusBadge status={c.data_status} compact />}
            </li>
          ))}
        </ol>
      </Panel>
      <p className="text-xs leading-5 text-slate-500">{r.disclaimer}</p>
    </article>
  );
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <RequireAuth what="report"><ReportView id={id} /></RequireAuth>;
}
