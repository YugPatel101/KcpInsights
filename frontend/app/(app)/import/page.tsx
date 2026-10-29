"use client";

import Link from "next/link";
import { useState } from "react";
import { CheckCircle2, Download } from "lucide-react";
import RequireAuth from "@/components/kcp/RequireAuth";
import { ErrorState, Notice, PageHeader, Panel, Spinner, buttonClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { ImportResponse } from "@/lib/types";

function Importer() {
  const { user } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const history = useApi<{ id: number; filename: string; kind: string; status: string; record_counts: Record<string, number>; warnings: number; created_at: string }[]>(user ? "/api/imports" : null);

  const submit = async (dryRun: boolean) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("dry_run", String(dryRun));
    setBusy(true);
    setError(null);
    try {
      const r = await api<ImportResponse>("/api/imports/financials", { form: fd });
      setResult(r);
      if (r.committed) history.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const rep = result?.report;
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Panel title="1. Choose a file" subtitle="JSON research bundle (company, issue, financials, peers, disclosures, sources) or a CSV of financial statements for an existing company. Max 20 MB, UTF-8.">
          <input
            type="file"
            accept=".json,.csv"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }}
            className="block w-full text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-slate-200"
            aria-label="Import file"
          />
          <div className="mt-4 flex flex-wrap gap-2">
            <button className={buttonClass.secondary} disabled={!file || busy} onClick={() => submit(true)}>{busy && <Spinner />}Validate (dry run)</button>
            <button className={buttonClass.primary} disabled={!file || busy || !rep?.ok || result?.committed} onClick={() => submit(false)}>Commit import</button>
          </div>
          <p className="mt-2 text-xs text-slate-500">Commit is enabled after a dry run with no blocking errors.</p>
        </Panel>

        {error && <ErrorState message={error} />}
        {result && rep && (
          <Panel title={result.committed ? "Import committed" : "2. Validation report"} subtitle={`${rep.errors.length} error(s) · ${rep.warnings.length} warning(s) · ${rep.info.length} note(s)`}>
            {result.committed && (
              <Notice><CheckCircle2 className="mr-1 inline size-4" /> Dataset #{result.dataset_id} saved: {Object.entries(result.counts ?? {}).map(([k, v]) => `${k} ${v}`).join(", ")}. Scores recalculate automatically. <Link href="/ipos?data_mode=imported" className="underline">View imported IPOs</Link></Notice>
            )}
            {result.preview?.ipos && <p className="mt-3 text-sm text-slate-300">IPOs in bundle: {result.preview.ipos.join(", ")}</p>}
            {result.preview?.row_count !== undefined && <p className="mt-3 text-sm text-slate-300">{result.preview.row_count} valid financial row(s).</p>}
            {(["errors", "warnings", "info"] as const).map((k) =>
              rep[k].length ? (
                <div key={k} className="mt-4">
                  <h3 className={`mb-1 text-xs font-semibold uppercase tracking-wider ${k === "errors" ? "text-rose-300" : k === "warnings" ? "text-amber-300" : "text-slate-400"}`}>{k}</h3>
                  <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
                    {rep[k].map((m, i) => (
                      <li key={i} className="text-slate-300"><span className="font-mono text-xs text-slate-500">{m.where}</span> — {m.message}</li>
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
          </Panel>
        )}
      </div>

      <div className="space-y-6">
        <Panel title="Templates">
          <div className="space-y-2">
            <a className={`${buttonClass.secondary} w-full`} href="/api/imports/templates/bundle_json"><Download className="size-4" /> Research bundle (JSON)</a>
            <a className={`${buttonClass.secondary} w-full`} href="/api/imports/templates/financials_csv"><Download className="size-4" /> Financial statements (CSV)</a>
          </div>
        </Panel>
        <Panel title="Rules">
          <ul className="list-disc space-y-1.5 pl-4 text-xs leading-5 text-slate-400">
            <li>Every record references a source with a title, URL and status. Use official documents (SEBI, NSE, BSE, the company).</li>
            <li>Units: crore, lakh, million, billion, thousand or rupees. Amounts are converted to INR crore; raw values are kept.</li>
            <li>Status: imported or estimated. Only administrators can mark data verified; synthetic data cannot be imported.</li>
            <li>A verified period is never overwritten by unverified data. Changed values create a new version instead of overwriting.</li>
            <li>Missing fields stay missing — they produce warnings, not zeros.</li>
          </ul>
        </Panel>
        <Panel title="Recent imports">
          {history.data?.length ? (
            <ul className="space-y-2 text-xs">
              {history.data.slice(0, 8).map((h) => (
                <li key={h.id} className="text-slate-400"><span className="text-slate-200">{h.filename}</span> · {h.kind} · {fmtDateTime(h.created_at)}<br />{Object.entries(h.record_counts).map(([k, v]) => `${k} ${v}`).join(", ")}{h.warnings ? ` · ${h.warnings} warnings` : ""}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">None yet.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}

export default function ImportPage() {
  return (
    <>
      <PageHeader eyebrow="Mode B — imported research" title="Import IPO research data" subtitle="Validate first, then commit. Imported values keep their provenance and are labelled as imported throughout the app." />
      <RequireAuth what="imports"><Importer /></RequireAuth>
    </>
  );
}
