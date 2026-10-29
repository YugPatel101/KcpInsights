"use client";

import { useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ErrorState, LoadingBlock, Notice, Panel, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtCr, fmtInr, fmtNum, fmtPct, titleCase } from "@/lib/format";
import { compactOverrides, scenarioFormSchema, type ScenarioForm } from "@/lib/schemas";
import type { ScenarioResult } from "@/lib/types";

const FIELDS = [
  ["revenue_growth_pct", "Revenue growth %"],
  ["ebitda_margin_pct", "EBITDA margin %"],
  ["multiple", "Valuation multiple (x)"],
  ["market_adjustment_pct", "Market adjustment %"],
] as const;
const NAMES = ["bear", "base", "bull"] as const;

export default function ScenarioPanel({ ipoId }: { ipoId: number }) {
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { register, handleSubmit, reset, formState } = useForm<ScenarioForm>({
    resolver: zodResolver(scenarioFormSchema),
    defaultValues: { bear: {}, base: {}, bull: {} },
  });

  const run = useCallback(
    async (overrides: Record<string, Record<string, number>>) => {
      setBusy(true);
      setError(null);
      try {
        setResult(await api<ScenarioResult>(`/api/ipos/${ipoId}/scenario`, { body: { overrides } }));
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setBusy(false);
      }
    },
    [ipoId],
  );

  useEffect(() => {
    // initial data-derived scenarios; state is only set from the async callbacks
    let alive = true;
    api<ScenarioResult>(`/api/ipos/${ipoId}/scenario`, { body: { overrides: {} } })
      .then((r) => alive && setResult(r))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [ipoId]);

  if (!result && !error) return <LoadingBlock rows={4} />;

  return (
    <div className="space-y-6">
      <Notice tone="warn">{result?.note ?? "Scenario outputs are hypothetical."}</Notice>
      {error && <ErrorState message={error} />}
      {result && result.status === "unavailable" && result.reasons && (
        <Notice tone="warn">Scenario analysis unavailable: {result.reasons.join("; ")}</Notice>
      )}

      {result && (
        <div className="grid gap-4 lg:grid-cols-3">
          {result.scenarios.map((s) => (
            <Panel key={s.name} title={`${titleCase(s.name)} case`} subtitle={s.status === "ok" ? `method: ${String(s.assumptions.method).toUpperCase()}` : "unavailable"}>
              {s.status === "ok" ? (
                <>
                  <div className="text-3xl font-bold tabular-nums text-white">{fmtInr(s.implied_price)}</div>
                  <div className={`mt-1 text-sm tabular-nums ${(s.implied_return_pct ?? 0) < 0 ? "text-rose-300" : "text-emerald-300"}`}>
                    {fmtPct(s.implied_return_pct, 1, true)} vs issue price {fmtInr(result.issue_price)}
                  </div>
                  <dl className="mt-4 grid grid-cols-2 gap-y-1 text-xs">
                    <dt className="text-slate-500">Revenue growth</dt><dd className="text-right tabular-nums text-slate-300">{fmtPct(s.assumptions.revenue_growth_pct as number)}</dd>
                    <dt className="text-slate-500">EBITDA margin</dt><dd className="text-right tabular-nums text-slate-300">{fmtPct(s.assumptions.ebitda_margin_pct as number)}</dd>
                    <dt className="text-slate-500">Multiple</dt><dd className="text-right tabular-nums text-slate-300">{fmtNum(s.assumptions.multiple as number)}x</dd>
                    <dt className="text-slate-500">Multiple source</dt><dd className="text-right text-slate-300">{String(s.assumptions.multiple_source ?? "—")}</dd>
                    <dt className="text-slate-500">Market adj.</dt><dd className="text-right tabular-nums text-slate-300">{fmtPct(s.assumptions.market_adjustment_pct as number)}</dd>
                    {s.steps && (
                      <>
                        <dt className="text-slate-500">Revenue → EBITDA</dt><dd className="text-right tabular-nums text-slate-300">{fmtCr(s.steps.revenue_cr)} → {fmtCr(s.steps.ebitda_cr)}</dd>
                        {s.steps.pat_cr !== undefined && (<><dt className="text-slate-500">PAT</dt><dd className="text-right tabular-nums text-slate-300">{fmtCr(s.steps.pat_cr)}</dd></>)}
                        <dt className="text-slate-500">Equity value</dt><dd className="text-right tabular-nums text-slate-300">{fmtCr(s.steps.equity_value_cr)}</dd>
                      </>
                    )}
                  </dl>
                </>
              ) : (
                <ul className="list-disc pl-5 text-sm text-amber-300">{s.reasons?.map((r) => <li key={r}>{r}</li>)}</ul>
              )}
            </Panel>
          ))}
        </div>
      )}

      <Panel title="Adjust assumptions" subtitle="Leave a field blank to use the data-derived default. Values are validated by the API.">
        <form
          onSubmit={handleSubmit((v) => run(compactOverrides(scenarioFormSchema.parse(v))))}
          className="space-y-4"
          noValidate
        >
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="py-2">Assumption</th>
                  {NAMES.map((n) => <th key={n} className="py-2 pl-3">{titleCase(n)}</th>)}
                </tr>
              </thead>
              <tbody>
                {FIELDS.map(([f, label]) => (
                  <tr key={f}>
                    <td className="py-1.5 pr-3 text-slate-300">{label}</td>
                    {NAMES.map((n) => {
                      const err = formState.errors[n]?.[f]?.message;
                      return (
                        <td key={n} className="py-1.5 pl-3">
                          <input type="number" step="any" aria-label={`${n} ${label}`} className={`${inputClass} ${err ? "border-rose-500/60" : ""}`} placeholder="default" {...register(`${n}.${f}`)} />
                          {err && <div className="mt-0.5 text-[11px] text-rose-300">{err}</div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2">
            <button type="submit" className={buttonClass.primary} disabled={busy}>{busy && <Spinner />}Recalculate</button>
            <button type="button" className={buttonClass.secondary} onClick={() => { reset({ bear: {}, base: {}, bull: {} }); void run({}); }}>Reset to defaults</button>
          </div>
        </form>
        {result?.derivation_notes && (
          <ul className="mt-4 space-y-1 text-xs text-slate-500">
            <li>Base revenue: {fmtCr(result.base_revenue_cr)} ({result.base_period}); post-issue shares: {fmtNum(result.post_issue_shares, 0)}</li>
            {Object.entries(result.derivation_notes).map(([k, v]) => <li key={k}>{titleCase(k)}: {v}</li>)}
            {Object.entries(result.formulas).map(([k, v]) => <li key={k} className="font-mono">{k}: {v}</li>)}
          </ul>
        )}
      </Panel>
    </div>
  );
}
