"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Notice, Panel, RiskBadge, ScoreBar, ScoreValue } from "@/components/kcp/ui";
import { fmtDateTime, fmtNum, fmtPct } from "@/lib/format";
import type { ComponentKey, ScoreResult } from "@/lib/types";

const ORDER: ComponentKey[] = ["profitability", "growth", "financial_health", "cash_flow", "valuation"];
const ITEM_LABEL: Record<string, string> = {
  roe: "Return on equity", roce: "Return on capital employed", roa: "Return on assets", net_margin: "Net profit margin", ebitda_margin: "EBITDA margin",
  gnpa_pct: "Gross NPA ratio", nnpa_pct: "Net NPA ratio", crar_pct: "Capital adequacy (CRAR)", solvency_ratio: "Solvency ratio",
  revenue_growth: "Revenue growth", pat_growth: "PAT growth", growth_consistency: "Growth consistency",
  current_ratio: "Current ratio", debt_to_equity: "Debt/Equity", interest_coverage: "Interest coverage",
  ocf_to_pat: "OCF/PAT", fcf: "Free cash flow", cash_flow_consistency: "Cash-flow consistency",
  pe: "P/E", pb: "P/B", ev_ebitda: "EV/EBITDA",
};
// metric shown next to each scored item (growth items fall back to YoY when a CAGR is not meaningful)
const ITEM_METRIC: Record<string, string[]> = {
  revenue_growth: ["revenue_cagr", "revenue_yoy"], pat_growth: ["pat_cagr", "pat_yoy"], fcf: ["fcf_margin"],
};

/** Full transparency view: overall score, each component, each scored input with its value, weight and score. */
export default function ScoreBreakdown({ r }: { r: ScoreResult }) {
  const [open, setOpen] = useState<ComponentKey | null>("profitability");
  const f = r.fundamental;
  const metric = (key: string) => {
    for (const k of ITEM_METRIC[key] ?? [key]) if (r.metrics[k]?.status === "ok") return r.metrics[k];
    return r.metrics[(ITEM_METRIC[key] ?? [key])[0]];
  };
  return (
    <div className="space-y-6">
      {r.warnings.map((w) => <Notice key={w} tone={w.includes("SYNTHETIC") ? "synthetic" : "warn"}>{w}</Notice>)}

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Overall fundamental score" subtitle={f.formula} className="lg:col-span-2">
          <div className="flex flex-wrap items-end gap-6">
            <div>
              <div className="text-5xl font-bold tabular-nums"><ScoreValue value={f.score} /></div>
              <div className="mt-1 text-sm text-ink-2">{f.classification ?? <span className="text-ink-3">No overall score: {f.reason}</span>}</div>
            </div>
            <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
              <div><dt className="text-xs text-ink-3">Data coverage</dt><dd className="tabular-nums text-ink">{fmtPct(r.coverage, 0)}</dd></div>
              <div><dt className="text-xs text-ink-3">Model weight computable</dt><dd className="tabular-nums text-ink">{fmtPct(f.weight_coverage, 0)}</dd></div>
              <div><dt className="text-xs text-ink-3">Financial basis</dt><dd className="text-ink">{r.basis ?? "—"}</dd></div>
              <div><dt className="text-xs text-ink-3">Periods used</dt><dd className="text-ink">{r.periods_used.join(", ") || "—"}</dd></div>
              <div><dt className="text-xs text-ink-3">Configuration</dt><dd className="text-ink">v{r.config_version}</dd></div>
              <div><dt className="text-xs text-ink-3">Calculated</dt><dd className="text-ink">{fmtDateTime(r.calculated_at)}</dd></div>
              <div><dt className="text-xs text-ink-3">Industry profile</dt><dd className="text-ink">{r.profile?.label ?? "General"}</dd></div>
            </dl>
          </div>
          {f.note && <p className="mt-4 text-xs text-warn-ink">{f.note}</p>}
          <div className="mt-6 grid gap-4 sm:grid-cols-5">
            {ORDER.map((k) => (
              <button key={k} onClick={() => setOpen(open === k ? null : k)} aria-expanded={open === k}
                      className={`rounded-lg border p-3 text-left transition hover:border-line-strong ${open === k ? "border-brand/60 bg-surface-2" : "border-line bg-surface"}`}>
                <div className="text-xs text-ink-3">{r.components[k].label} · {fmtNum(f.weights[k], 2)}</div>
                <div className="mt-1 text-xl">{r.components[k].applicable === false ? <span className="text-sm text-ink-3">not applicable</span> : <ScoreValue value={r.components[k].score} />}</div>
                <div className="text-[11px] text-ink-3">{r.components[k].applicable === false ? "excluded for this industry" : `coverage ${fmtPct(r.components[k].coverage, 0)}`}</div>
              </button>
            ))}
          </div>
          <p className="mt-4 text-xs leading-5 text-ink-3">
            Classes: 80–100 strong, 65–79 relatively positive, 50–64 mixed, 35–49 weak, below 35 significant concerns. They describe financial
            characteristics only — not recommendations and not listing-gain probabilities. Weights are judgemental educational defaults.
          </p>
        </Panel>

        <Panel title="Risk score" subtitle="Separate from Q. Higher means more risk.">
          <div className="flex items-baseline gap-3">
            <span className="text-4xl font-bold tabular-nums text-ink">{fmtNum(r.risk.score, 1)}</span>
            <RiskBadge level={r.risk.level} />
          </div>
          <div className="mt-4 space-y-3">
            {r.risk.components.map((c) => (
              <ScoreBar key={c.key} label={c.label} value={c.points} invert
                        hint={c.applicable === false ? (c.detail ?? "not applicable") : c.available ? `${c.kind}${c.detail ? ` · ${c.detail}` : ""}` : "not available — excluded, not penalised"} />
            ))}
          </div>
        </Panel>
      </div>

      {ORDER.filter((k) => open === k).map((k) => {
        const c = r.components[k];
        return (
          <Panel key={k} title={`${c.label} — how it was scored`} subtitle={c.reason ?? `Score = weighted average of the available inputs (weights rescaled when an input is unavailable). Coverage ${fmtPct(c.coverage, 0)}.`}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-ink-3">
                    <th className="py-2">Input</th><th className="py-2 text-right">Value</th><th className="py-2">Period</th><th className="py-2 text-right">Weight</th><th className="py-2 text-right">Score</th><th className="py-2 pl-4">Formula / note</th>
                  </tr>
                </thead>
                <tbody>
                  {c.items.map((it) => {
                    const m = metric(it.key);
                    return (
                      <tr key={it.key} className={`border-t border-line align-top ${it.applicable === false ? "opacity-60" : ""}`}>
                        <td className="py-2 text-ink">{ITEM_LABEL[it.key] ?? it.key}{it.applicable === false && <span className="block text-[11px] text-ink-3">not applicable — excluded</span>}</td>
                        <td className="py-2 text-right tabular-nums text-ink">{m?.status === "ok" ? (m.value === null ? (m.note ?? "—") : `${fmtNum(m.value, 2)}${m.unit === "%" ? "%" : m.unit === "x" ? "x" : ` ${m.unit}`}`) : <span className="text-ink-3">{m?.reason ?? "unavailable"}</span>}</td>
                        <td className="py-2 text-ink-2">{m?.period ?? "—"}</td>
                        <td className="py-2 text-right tabular-nums text-ink-2">{fmtNum(it.weight, 2)}</td>
                        <td className="py-2 text-right"><ScoreValue value={it.score} /></td>
                        <td className="py-2 pl-4 text-xs leading-5 text-ink-3">{m?.formula}{it.note ? ` · ${it.note}` : ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        );
      })}

      {r.applicability && r.applicability.length > 0 && (
        <Panel title={`Not applicable for ${r.profile?.label ?? "this industry"}`} subtitle="Shown for reference where computable; never scored and never counted as missing.">
          <ul className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {r.applicability.map((a) => <li key={a.key} className="text-ink-2">{a.label} <span className="text-xs text-ink-3">— {a.reason}</span></li>)}
          </ul>
        </Panel>
      )}

      {r.missing.length > 0 && (
        <Panel title="Missing or not meaningful inputs" subtitle="Nothing is filled in or set to zero; these lower coverage instead.">
          <details>
            <summary className="flex cursor-pointer items-center gap-1 text-sm text-ink-2"><ChevronDown className="size-4" aria-hidden /> {r.missing.length} item(s)</summary>
            <ul className="mt-3 space-y-1 text-sm text-ink-2">{r.missing.map((m) => <li key={m}>• {m}</li>)}</ul>
          </details>
        </Panel>
      )}
      <p className="text-xs leading-5 text-ink-3">{r.disclaimer}</p>
    </div>
  );
}
