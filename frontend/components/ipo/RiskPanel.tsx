"use client";

import { DataStatusBadge, EmptyState, Notice, Panel, RiskBadge, ScoreBar } from "@/components/kcp/ui";
import { fmtCr, fmtInt, fmtNum, titleCase } from "@/lib/format";
import type { IpoDetail, ScoreResult } from "@/lib/types";

const FACT_LABEL: Record<string, string> = {
  pre_issue_shares: "Equity shares outstanding before the issue",
  customer_concentration_pct: "Revenue share of top customers",
  auditor_qualifications: "Auditor qualifications not given effect to",
  contingent_liabilities_cr: "Contingent liabilities",
};

export default function RiskPanel({ d, r }: { d: IpoDetail; r: ScoreResult }) {
  const facts = Object.entries(d.document_facts ?? {}).filter(([k]) => k !== "lender_kpis" && k !== "business_overview");
  const gov = r.risk.governance_disclosure;
  const kinds = ["disclosed fact", "derived from financials", "derived from issue terms", "data quality"] as const;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Risk score" subtitle={r.risk.formula} className="lg:col-span-1">
          <div className="flex items-baseline gap-3">
            <span className="text-5xl font-bold tabular-nums text-ink">{fmtNum(r.risk.score, 1)}</span>
            <RiskBadge level={r.risk.level} />
          </div>
          <p className="mt-3 text-xs leading-5 text-ink-3">0–29 low · 30–49 moderate · 50–69 elevated · 70+ high. Weight computable: {fmtNum(r.risk.weight_coverage, 0)}%.
            Missing information is excluded from the score; it is never treated as evidence of a problem.</p>
          {gov && (
            <div className="mt-4 border-t border-line pt-4">
              <ScoreBar label="Governance & disclosure risk" value={gov.score} invert hint={gov.reason ?? `${gov.available} of ${gov.of} disclosure-based components available`} />
              <p className="mt-2 text-[11px] leading-4 text-ink-3">{gov.formula}</p>
            </div>
          )}
        </Panel>
        <Panel title="Components" className="lg:col-span-2">
          <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
            {kinds.map((k) => {
              const cs = r.risk.components.filter((c) => c.kind === k);
              if (!cs.length) return null;
              return (
                <div key={k}>
                  <h3 className="mb-2 text-xs uppercase tracking-wider text-ink-3">{k}</h3>
                  <div className="space-y-3">
                    {cs.map((c) => <ScoreBar key={c.key} label={`${c.label} (w ${c.weight})`} value={c.points} invert
                                            hint={c.applicable === false ? (c.detail ?? "not applicable") : c.available ? (c.detail ?? undefined) : "not available"} />)}
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      </div>

      <Panel title="Facts read from the offer document" subtitle="Each value links to the page it was read from.">
        {facts.length ? (
          <dl className="divide-y divide-line text-sm">
            {facts.map(([k, f]) => f && (
              <div key={k} className="grid gap-1 py-3 sm:grid-cols-3">
                <dt className="text-ink-2">{FACT_LABEL[k] ?? titleCase(k)}</dt>
                <dd className="text-ink">
                  {k === "pre_issue_shares" ? fmtInt(Number(f.value)) : k === "customer_concentration_pct" ? `${fmtNum(Number(f.value), 2)}%` : k === "contingent_liabilities_cr" ? fmtCr(Number(f.value)) : String(f.value)}
                  {f.basis && <span className="ml-2 text-xs text-ink-3">{f.basis}</span>}
                </dd>
                <dd className="text-xs leading-5 text-ink-3">
                  “{f.text.slice(0, 160)}{f.text.length > 160 ? "…" : ""}” — <a className="text-brand-ink hover:underline" href={`/api/documents/${f.document_id}/file#page=${f.page}`} target="_blank" rel="noopener noreferrer">p{f.page}</a>
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <EmptyState title="No document facts yet" body="Read automatically from the offer document after it is downloaded." />
        )}
      </Panel>

      <Panel title="Recorded disclosures" subtitle="Confirmed disclosures are stated in official documents; unresolved concerns are flagged for follow-up.">
        {!d.disclosures.length && <Notice>No individual disclosures are recorded. This is not evidence that none exist — read the offer document&apos;s risk factors and litigation sections.</Notice>}
        {d.disclosures.length > 0 && (
          <ul className="divide-y divide-line">
            {d.disclosures.map((x) => (
              <li key={x.id} className="py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-ink">{x.title}</span>
                  <span className={`text-xs uppercase ${x.severity === "high" ? "text-neg-ink" : x.severity === "medium" ? "text-warn-ink" : "text-ink-2"}`}>{x.severity}</span>
                  <span className="text-xs text-ink-3">{titleCase(x.category)} · {x.status === "confirmed_disclosure" ? "confirmed" : "unresolved"}</span>
                  <DataStatusBadge status={x.data_status} compact />
                </div>
                <p className="mt-1 leading-6 text-ink-2">{x.description}</p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
