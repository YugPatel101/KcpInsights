"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { PeerDistributionChart } from "@/components/charts/Charts";
import { DataStatusBadge, Notice, Panel, RiskBadge, ScoreBar, ScoreValue, Stat } from "@/components/kcp/ui";
import { fmtCr, fmtDateTime, fmtInr, fmtMetric, fmtNum, fmtPct, fmtScore, titleCase } from "@/lib/format";
import type { Component, ScoreResult } from "@/lib/types";

function ComponentTable({ comp, risk = false }: { comp: Component; risk?: boolean }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
            <th className="py-2 pr-3">Input</th>
            <th className="py-2 pr-3 text-right">Value</th>
            <th className="py-2 pr-3 text-right">Weight</th>
            <th className="py-2 pr-3 text-right">{risk ? "Risk pts" : "Score"}</th>
            <th className="py-2">How it was derived</th>
          </tr>
        </thead>
        <tbody>
          {comp.items.map((it) => {
            const m = it.metric;
            const norm = it.normalization;
            const normText = norm
              ? norm.direction === "target"
                ? `target ${norm.lo}–${norm.hi}${norm.unit === "x" ? "x" : ""}`
                : `${norm.direction} is better: ${norm.a} → ${norm.b}`
              : null;
            return (
              <tr key={it.key} className="border-t border-white/5 align-top">
                <td className="py-2 pr-3 text-slate-200">{m?.label ?? titleCase(it.key)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                  {m ? fmtMetric(m.value, m.unit) : it.value === undefined || it.value === null ? "—" : typeof it.value === "number" ? fmtNum(it.value) : String(it.value)}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums text-slate-400">{(it.weight * 100).toFixed(0)}%</td>
                <td className="py-2 pr-3 text-right"><ScoreValue value={it.score} className={risk ? "text-slate-100" : undefined} /></td>
                <td className="py-2 text-xs leading-5 text-slate-400">
                  {m && <div className="font-mono text-[11px] text-slate-500">{m.formula}{m.periods.length ? ` · ${m.periods.join(", ")}` : ""}</div>}
                  {normText && <div>Normalisation: {normText}</div>}
                  {m?.reason && <div className="text-amber-300/90">{m.reason}</div>}
                  {it.evidence && <div>{it.evidence}</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {comp.reason && <p className="mt-2 text-xs text-slate-500">{comp.reason}</p>}
    </div>
  );
}

function ComponentList({ comps, risk = false }: { comps: Record<string, Component>; risk?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="divide-y divide-white/5">
      {Object.entries(comps).map(([name, c]) => (
        <Fragment key={name}>
          <button
            className="flex w-full items-center gap-3 py-3 text-left"
            aria-expanded={open === name}
            onClick={() => setOpen(open === name ? null : name)}
          >
            {open === name ? <ChevronDown className="size-4 text-slate-400" /> : <ChevronRight className="size-4 text-slate-400" />}
            <div className="flex-1">
              <ScoreBar label={`${titleCase(name)} · weight ${(c.weight * 100).toFixed(0)}%`} value={c.score} invert={risk} />
            </div>
          </button>
          {open === name && (
            <div className="pb-4 pl-7">
              {c.status !== "ok" && <p className="mb-2 text-sm text-amber-300">Unavailable: {c.reason}</p>}
              <ComponentTable comp={c} risk={risk} />
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}

export default function ScoreBreakdown({ r }: { r: ScoreResult }) {
  const v = r.valuation;
  return (
    <div className="space-y-6">
      {r.warnings.map((w) => (
        <Notice key={w} tone={w.startsWith("SYNTHETIC") ? "synthetic" : "warn"}>{w}</Notice>
      ))}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Research score" value={<ScoreValue value={r.composite} />} hint={r.status === "complete" ? r.composite_formula : "incomplete — see below"} className="lg:col-span-1" />
        <Stat label="Quality Q" value={<ScoreValue value={r.quality.score} />} />
        <Stat label="Valuation V" value={<ScoreValue value={v.score} />} hint={v.multiple_label ? `on ${v.multiple_label}` : undefined} />
        <Stat label="Risk R" value={<span className="tabular-nums">{fmtScore(r.risk.score)}</span>} hint={<RiskBadge level={r.risk.level} />} />
        <Stat label="Evidence coverage C" value={fmtPct(r.coverage, 1)} hint={`input completeness ${fmtPct(r.evidence.input_completeness, 0)}`} />
      </div>

      {r.status === "incomplete" && (
        <Notice tone="warn">
          <strong>Composite not calculated.</strong> Missing components are never silently re-weighted:
          <ul className="mt-1 list-disc pl-5">
            {r.missing_components.map((m) => (
              <li key={m.component}>
                {titleCase(m.component)} — {m.reason}
              </li>
            ))}
          </ul>
        </Notice>
      )}

      <div className="grid gap-6 2xl:grid-cols-2">
        <Panel title="Fundamental quality" subtitle={r.quality.formula}>
          <ComponentList comps={r.quality.components} />
          <p className="mt-3 text-xs text-slate-500">Annual periods used: {r.quality.annual_periods_used.join(", ") || "none"}{r.quality.excluded_periods.length ? ` · excluded: ${r.quality.excluded_periods.map((p) => `${p.label} (${p.reason})`).join(", ")}` : ""}</p>
        </Panel>
        <Panel title="Risk" subtitle={`${r.risk.formula}. Higher means riskier.`}>
          <ComponentList comps={r.risk.components} risk />
        </Panel>
      </div>

      <Panel title="Relative valuation" subtitle={v.formula}>
        {v.status === "ok" && v.peers && v.ipo_multiple !== undefined ? (
          <div className="grid gap-6 lg:grid-cols-5">
            <div className="space-y-3 text-sm lg:col-span-2">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
                <dt className="text-slate-400">Multiple</dt><dd className="text-right text-slate-200">{v.multiple_label}</dd>
                <dt className="text-slate-400">IPO multiple</dt><dd className="text-right tabular-nums text-slate-200">{fmtNum(v.ipo_multiple)}x</dd>
                <dt className="text-slate-400">Peer p{v.low_percentile} / median / p{v.high_percentile}</dt><dd className="text-right tabular-nums text-slate-200">{fmtNum(v.peer_low)} / {fmtNum(v.peer_median)} / {fmtNum(v.peer_high)}</dd>
                <dt className="text-slate-400">Premium to median</dt><dd className="text-right tabular-nums text-slate-200">{fmtPct(v.premium_to_median_pct, 1, true)}</dd>
                <dt className="text-slate-400">Price used</dt><dd className="text-right tabular-nums text-slate-200">{fmtInr(v.price_used)} ({v.price_basis})</dd>
                <dt className="text-slate-400">Post-issue market cap</dt><dd className="text-right tabular-nums text-slate-200">{fmtCr(v.market_cap_cr)}</dd>
              </dl>
              <p className="text-xs leading-5 text-slate-500">{v.peer_selection}</p>
              <p className="text-xs leading-5 text-slate-500">{v.kind}. A high score means the IPO is priced toward the cheap end of its peer range — not that it is undervalued in any absolute sense.</p>
              {v.flags.map((f) => (
                <p key={f} className="text-xs text-amber-300">{f}</p>
              ))}
            </div>
            <div className="lg:col-span-3">
              <PeerDistributionChart peers={v.peers} ipoMultiple={v.ipo_multiple} low={v.peer_low!} high={v.peer_high!} median={v.peer_median!} label={v.multiple_label!} />
              <table className="mt-2 w-full text-xs">
                <caption className="sr-only">Peer multiples</caption>
                <tbody>
                  {v.peers.map((p) => (
                    <tr key={p.name} className="border-t border-white/5">
                      <td className="py-1.5 text-slate-300">{p.name}</td>
                      <td className="py-1.5 text-right tabular-nums text-slate-300">{p.value === null ? "—" : `${fmtNum(p.value)}x`}</td>
                      <td className="py-1.5 pl-3 text-slate-500">{p.used ? `as of ${p.as_of}` : `excluded: ${p.excluded_reason}`}</td>
                      <td className="py-1.5 text-right"><DataStatusBadge status={p.data_status} compact /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="space-y-2 text-sm">
            <p className="text-amber-300">Valuation score unavailable: {v.reason}</p>
            {v.attempts.length > 0 && (
              <ul className="list-disc pl-5 text-slate-400">
                {v.attempts.map((a) => (
                  <li key={a.multiple}>{a.multiple.toUpperCase()}: {a.reason}</li>
                ))}
              </ul>
            )}
            {v.flags.map((f) => <p key={f} className="text-xs text-amber-300">{f}</p>)}
          </div>
        )}
      </Panel>

      <Panel title="Evidence coverage" subtitle={`${r.evidence.formula}. ${r.evidence.note}`}>
        <div className="grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
          {r.evidence.items.map((i) => (
            <div key={i.key} className="flex items-center justify-between gap-3 border-b border-white/5 py-1.5">
              <span className="text-slate-300">{titleCase(i.key.replace(/^fin_/, "financials: "))}</span>
              <span className="flex items-center gap-2">
                <span className="text-xs tabular-nums text-slate-500">w {i.weight}</span>
                {i.present ? <DataStatusBadge status={i.status} compact /> : <span className="text-xs text-slate-500">missing</span>}
                <span className={`text-xs tabular-nums ${i.credit ? "text-emerald-300" : "text-slate-500"}`}>{i.credit ? "credited" : "no credit"}</span>
              </span>
            </div>
          ))}
        </div>
      </Panel>

      <p className="text-xs leading-5 text-slate-500">
        Config v{r.config_version} · calculated {fmtDateTime(r.calculated_at)} · input fingerprint <span className="font-mono">{r.input_fingerprint.slice(0, 12)}</span>. {r.disclaimer}
      </p>
    </div>
  );
}
