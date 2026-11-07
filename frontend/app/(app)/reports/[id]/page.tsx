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
        eyebrow={<Link href="/reports" className="hover:text-ink-2">← Reports</Link>}
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
      <Notice>Every sentence is templated from the quantitative engine&apos;s outputs and stored source data; no language model is involved.</Notice>
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Fundamental score" value={<ScoreValue value={r.scores.composite} />} hint={r.scores.classification ?? r.scores.status} />
        <Stat label="Valuation" value={<ScoreValue value={r.scores.valuation} />} />
        <Stat label="Risk" value={r.scores.risk?.toFixed(1) ?? "—"} hint={<RiskBadge level={r.scores.risk_level} />} />
        <Stat label="Data coverage" value={fmtPct(r.scores.coverage, 0)} />
      </div>
      {r.sections.map((s, n) => (
        <Panel key={s.key} title={`${n + 1}. ${s.title}`}>
          <div className="space-y-2 text-sm leading-6 text-ink-2">
            {s.paragraphs.map((p, i) => <p key={i} className="whitespace-pre-wrap">{p}</p>)}
          </div>
          {s.facts.length > 0 && (
            <dl className="mt-4 grid gap-x-8 sm:grid-cols-2">
              {s.facts.map((f, i) => (
                <div key={i} className="flex justify-between gap-4 border-b border-line py-1.5 text-sm">
                  <dt className="text-ink-2">{f.label}{f.excluded_reason ? <span className="block text-xs text-ink-3">excluded: {f.excluded_reason}</span> : null}{f.reasons ? <span className="block text-xs text-warn-ink">{f.reasons.join("; ")}</span> : null}</dt>
                  <dd className="text-right tabular-nums text-ink">{f.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {s.evidence.length > 0 && <p className="mt-3 text-xs text-ink-3">Evidence: {s.evidence.map((e) => <a key={e} href={`#cite-${e}`} className="mr-1 font-mono text-brand-ink hover:underline">[{e}]</a>)}</p>}
        </Panel>
      ))}
      <Panel title="Citations">
        <ol className="space-y-1 text-sm">
          {r.citations.map((c) => (
            <li key={c.id} id={`cite-${c.id}`} className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-ink-2">[{c.id}]</span>
              {c.url ? <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-brand-ink hover:underline">{c.label}</a> : <span className="text-ink-2">{c.label}</span>}
              <span className="text-xs text-ink-3">{c.kind.replace("_", " ")}{c.ref_id !== null ? ` #${c.ref_id}` : ""}</span>
              {c.data_status && <DataStatusBadge status={c.data_status} compact />}
            </li>
          ))}
        </ol>
      </Panel>
      <p className="text-xs leading-5 text-ink-3">{r.disclaimer}</p>
    </article>
  );
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <RequireAuth what="report"><ReportView id={id} /></RequireAuth>;
}
