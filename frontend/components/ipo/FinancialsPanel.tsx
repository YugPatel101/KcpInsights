"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert, FileSearch } from "lucide-react";
import { FinancialBarsChart } from "@/components/charts/Charts";
import { DataStatusBadge, EmptyState, ErrorState, LoadingBlock, Notice, Panel, Spinner, buttonClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Financials, Statement, StatementProvenance } from "@/lib/types";

type Row = { key: string; label: string; strong?: boolean; perShare?: boolean };
const SECTIONS: { title: string; rows: Row[] }[] = [
  { title: "Profit and loss", rows: [
    { key: "revenue", label: "Revenue from operations", strong: true }, { key: "other_income", label: "Other income" }, { key: "total_income", label: "Total income" },
    { key: "cost_of_materials", label: "Cost of materials consumed" }, { key: "employee_expenses", label: "Employee benefits expense" },
    { key: "other_expenses", label: "Other expenses" }, { key: "total_expenses", label: "Total expenses" },
    { key: "ebitda", label: "EBITDA (derived)", strong: true }, { key: "depreciation", label: "Depreciation & amortisation" },
    { key: "ebit", label: "EBIT (derived)" }, { key: "interest_expense", label: "Finance costs" }, { key: "pbt", label: "Profit before tax" },
    { key: "tax_expense", label: "Tax expense" }, { key: "pat", label: "Profit after tax", strong: true },
    { key: "eps_basic", label: "EPS — basic (₹)", perShare: true }, { key: "eps_diluted", label: "EPS — diluted (₹)", perShare: true },
  ] },
  { title: "Balance sheet", rows: [
    { key: "non_current_assets", label: "Non-current assets" }, { key: "current_assets", label: "Current assets" }, { key: "inventory", label: "Inventories" },
    { key: "trade_receivables", label: "Trade receivables" }, { key: "cash_and_equivalents", label: "Cash and cash equivalents" },
    { key: "total_assets", label: "Total assets", strong: true }, { key: "share_capital", label: "Equity share capital" },
    { key: "other_equity", label: "Other equity / reserves" }, { key: "total_equity", label: "Total equity", strong: true },
    { key: "borrowings_non_current", label: "Borrowings — non-current" }, { key: "borrowings_current", label: "Borrowings — current" },
    { key: "total_debt", label: "Total borrowings (derived)" }, { key: "lease_liabilities", label: "Lease liabilities" },
    { key: "non_current_liabilities", label: "Non-current liabilities" }, { key: "current_liabilities", label: "Current liabilities" },
    { key: "total_liabilities", label: "Total liabilities", strong: true },
  ] },
  { title: "Cash flow", rows: [
    { key: "operating_cash_flow", label: "Net cash from operating activities", strong: true }, { key: "investing_cash_flow", label: "Net cash from investing activities" },
    { key: "financing_cash_flow", label: "Net cash from financing activities" }, { key: "capex", label: "Capital expenditure" },
  ] },
];

export default function FinancialsPanel({ ipoId }: { ipoId: number }) {
  const { data, error, loading, reload } = useApi<Financials>(`/api/ipos/${ipoId}/financials`);
  const [basis, setBasis] = useState<string | null>(null);
  const [prov, setProv] = useState<StatementProvenance | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock rows={8} />;
  if (!data.statements.length) {
    return <EmptyState title="No financial statements stored yet" body="They are extracted automatically from the offer document once it is published and downloaded. Scanned (image-only) prospectuses cannot be read." />;
  }
  const bases = [...new Set(data.statements.map((s) => s.basis))];
  const active = basis ?? data.basis_used ?? bases[0];
  const stmts = data.statements.filter((s) => s.basis === active).sort((a, b) => b.period_end.localeCompare(a.period_end));
  const annual = stmts.filter((s) => s.period_months === 12).slice().reverse();
  const v = (s: Statement, k: string) => (typeof s[k] === "number" ? (s[k] as number) : null);

  const showProv = async (id: number) => {
    setBusy(id);
    setMsg(null);
    try {
      setProv(await api<StatementProvenance>(`/api/ipos/${ipoId}/financials/${id}/provenance`));
    } catch (e) {
      setMsg(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <Notice>
        {data.note} Basis used for ratios and scores: <strong>{data.basis_used ?? "none"}</strong>.
        Figures marked <em>unverified</em> or <em>needs review</em> are shown but not scored.
      </Notice>
      {bases.length > 1 && (
        <div className="flex gap-2" role="group" aria-label="Reporting basis">
          {bases.map((b) => (
            <button key={b} onClick={() => setBasis(b)} className={b === active ? buttonClass.primary : buttonClass.secondary}>{b}</button>
          ))}
        </div>
      )}

      {annual.length > 0 && (
        <Panel title="Revenue, EBITDA and profit" subtitle={`Annual periods, ₹ crore, ${active} basis`}>
          <FinancialBarsChart rows={annual.map((s) => ({ period: s.period_label, revenue: v(s, "revenue"), ebitda: v(s, "ebitda"), pat: v(s, "pat") }))} />
        </Panel>
      )}

      <Panel title="Restated financial statements" subtitle="₹ crore unless stated. Click a period to see where each figure was read in the prospectus.">
        {msg && <div className="mb-3"><ErrorState message={msg} /></div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="align-bottom text-xs text-ink-3">
                <th className="sticky left-0 bg-[#0b0b0c] py-2 text-left font-medium uppercase tracking-wider">Line item</th>
                {stmts.map((s) => (
                  <th key={s.id} className="px-3 py-2 text-right font-medium">
                    <button onClick={() => showProv(s.id)} className="inline-flex flex-col items-end gap-1 hover:text-ink" title="Show provenance">
                      <span className="text-sm text-ink">{s.period_label}{s.period_months !== 12 && <span className="ml-1 text-[10px] text-warn-ink">not annualised</span>}</span>
                      <span className="flex items-center gap-1">{busy === s.id ? <Spinner className="size-3" /> : <FileSearch className="size-3" aria-hidden />}<DataStatusBadge status={s.data_status} compact /></span>
                      <span className="flex items-center gap-1 text-[11px]">
                        {s.validation_status === "passed" ? <CheckCircle2 className="size-3 text-pos-ink" aria-hidden /> : <CircleAlert className="size-3 text-warn-ink" aria-hidden />}
                        checks {s.validation_status.replace("_", " ")}
                      </span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            {SECTIONS.map((sec) => (
              <tbody key={sec.title}>
                <tr><td colSpan={stmts.length + 1} className="pb-1 pt-4 text-xs font-semibold uppercase tracking-wider text-ink-2">{sec.title}</td></tr>
                {sec.rows.filter((r) => stmts.some((s) => v(s, r.key) !== null)).map((r) => (
                  <tr key={r.key} className="border-t border-line">
                    <td className={`sticky left-0 bg-[#0b0b0c] py-1.5 pr-3 ${r.strong ? "font-medium text-ink" : "text-ink-2"}`}>{r.label}</td>
                    {stmts.map((s) => {
                      const x = v(s, r.key);
                      return <td key={s.id} className={`px-3 py-1.5 text-right tabular-nums ${r.strong ? "text-ink" : "text-ink-2"} ${x !== null && x < 0 ? "text-neg-ink" : ""}`}>{x === null ? "—" : fmtNum(x, r.perShare ? 2 : 2)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      </Panel>

      {prov && (
        <Panel title={`Provenance — ${prov.period_label} (${prov.basis})`} subtitle="Every figure as printed in the offer document, with its page. Derived figures show their formula."
               action={<button className={buttonClass.ghost} onClick={() => setProv(null)}>Close</button>}>
          <div className="mb-4 flex flex-wrap gap-2 text-xs">
            {prov.checks.map((c) => (
              <span key={c.check} title={c.formula} className={`rounded-md border px-2 py-1 ${c.passed ? "border-pos/30 text-pos-ink" : c.hard ? "border-neg/40 text-neg-ink" : "border-warn/30 text-warn-ink"}`}>
                {c.passed ? "✓" : "✗"} {c.formula}{!c.passed && c.difference ? ` (difference ${fmtNum(c.difference, 2)})` : ""}
              </span>
            ))}
            {!prov.checks.length && <span className="text-ink-3">No accounting check could be applied to this period.</span>}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wider text-ink-3"><th className="py-2">Field</th><th className="py-2">Label in document</th><th className="py-2 text-right">As printed</th><th className="py-2">Unit</th><th className="py-2 text-right">₹ crore</th><th className="py-2 text-right">Page</th></tr></thead>
              <tbody>
                {prov.items.map((i) => (
                  <tr key={`${i.field}-${i.status}`} className="border-t border-line">
                    <td className="py-1.5 text-ink-2">{i.field.replace(/_/g, " ")}</td>
                    <td className="py-1.5 text-xs text-ink-2">{i.status === "derived" ? <em>derived: {i.raw_label}</em> : i.raw_label}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-ink-2">{i.raw_text || "—"}</td>
                    <td className="py-1.5 text-xs text-ink-3">{i.unit}</td>
                    <td className="py-1.5 text-right tabular-nums text-ink">{fmtNum(i.value, 2)}</td>
                    <td className="py-1.5 text-right">
                      {i.page && prov.document_id ? <a className="text-brand-ink hover:underline" href={`/api/documents/${prov.document_id}/file#page=${i.page}`} target="_blank" rel="noopener noreferrer">p{i.page}</a> : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {data.superseded.length > 0 && (
        <Panel title="History" subtitle="Earlier values are kept when a newer document changes a period.">
          <ul className="space-y-1 text-sm text-ink-2">
            {data.superseded.map((h) => <li key={h.id}>{h.period_label} ({h.basis}) — superseded record from {fmtDateTime(h.created_at)} <DataStatusBadge status={h.data_status} compact /></li>)}
          </ul>
        </Panel>
      )}
    </div>
  );
}
