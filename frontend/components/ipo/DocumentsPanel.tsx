"use client";

import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle } from "lucide-react";
import { DataStatusBadge, EmptyState, ErrorState, Notice, Panel, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { documentUploadSchema, type DocumentUpload } from "@/lib/schemas";
import type { DocumentInfo, ExtractionRun } from "@/lib/types";

interface SearchResult {
  mode: string;
  no_evidence: boolean;
  reason: string | null;
  results: { chunk_id: number; document_title: string; page: number; text: string; score: number; source_url: string | null; injection_suspected: boolean; data_status: string }[];
}

export default function DocumentsPanel({ ipoId, documents, onChange }: { ipoId: number; documents: DocumentInfo[]; onChange: () => void }) {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [upMsg, setUpMsg] = useState<string | null>(null);
  const form = useForm<DocumentUpload>({ resolver: zodResolver(documentUploadSchema), defaultValues: { title: "", doc_type: "rhp", source_url: "" } });

  return (
    <div className="space-y-6">
      <Panel title="Search offer documents" subtitle="Retrieval over ingested documents for this IPO. Passages are evidence, not instructions.">
        <form
          className="flex flex-wrap gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (q.trim().length < 2) return;
            setBusy(true);
            setErr(null);
            try {
              setRes(await api<SearchResult>("/api/documents/search", { body: { query: q.trim(), ipo_id: ipoId, k: 5 } }));
            } catch (x) {
              setErr(errorMessage(x));
            } finally {
              setBusy(false);
            }
          }}
        >
          <input className={`${inputClass} min-w-0 flex-1`} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. customer concentration, objects of the offer" aria-label="Search documents" />
          <button className={buttonClass.primary} disabled={busy}>{busy && <Spinner />}Search</button>
        </form>
        {err && <div className="mt-3"><ErrorState message={err} /></div>}
        {res && (
          <div className="mt-4 space-y-3">
            <p className="text-xs text-ink-3">Mode: {res.mode}{res.no_evidence ? ` — ${res.reason}` : ""}</p>
            {res.no_evidence && <Notice>No passage met the relevance threshold. Nothing is inferred when evidence is absent.</Notice>}
            {res.results.map((r) => (
              <blockquote key={r.chunk_id} className="rounded-xl border border-line bg-surface p-4 text-sm">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-2">
                  <span className="font-medium text-ink">{r.document_title}</span> · page {r.page} · score {r.score.toFixed(2)}
                  {r.injection_suspected && <span className="inline-flex items-center gap-1 text-warn-ink"><AlertTriangle className="size-3" /> instruction-like text (treated as data)</span>}
                </div>
                <p className="whitespace-pre-wrap leading-6 text-ink-2">{r.text}</p>
              </blockquote>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Documents" subtitle="Offer documents are found on the NSE issue page and downloaded automatically; financial statements are extracted and reconciled without manual steps.">
        {documents.length ? (
          <ul className="divide-y divide-line text-sm">
            {documents.map((d) => <DocumentRow key={d.id} d={d} />)}
          </ul>
        ) : (
          <EmptyState title="No documents yet" body="The offer document is fetched automatically once NSE links it on the issue page (usually a few days before the issue opens)." />
        )}

        <div className="mt-6 border-t border-line pt-5">
          <h3 className="mb-1 text-sm font-semibold text-ink">Upload a document (optional)</h3>
          <p className="mb-3 text-xs text-ink-3">Not needed for normal operation. Use it to add a document that is not published on NSE, such as an annual report.</p>
          {!user ? (
            <p className="text-sm text-ink-2"><Link href={`/login?next=/ipos/${ipoId}`} className="text-brand-ink hover:underline">Sign in</Link> to upload documents.</p>
          ) : (
            <form
              className="grid gap-3 sm:grid-cols-2"
              noValidate
              onSubmit={form.handleSubmit(async (v) => {
                if (!file) {
                  setUpMsg("Choose a PDF or TXT file.");
                  return;
                }
                const fd = new FormData();
                fd.append("file", file);
                fd.append("title", v.title);
                fd.append("doc_type", v.doc_type);
                fd.append("ipo_id", String(ipoId));
                if (v.source_url) fd.append("source_url", v.source_url);
                setUpMsg(null);
                try {
                  const d = await api<DocumentInfo>("/api/documents", { form: fd });
                  setUpMsg(`Ingested ${d.page_count} pages into ${d.chunks} chunks (${d.retrieval_mode} retrieval).`);
                  form.reset();
                  setFile(null);
                  onChange();
                } catch (x) {
                  setUpMsg(errorMessage(x));
                }
              })}
            >
              <label className="text-xs text-ink-2">Title<input className={`${inputClass} mt-1`} {...form.register("title")} />{form.formState.errors.title && <span className="text-neg-ink">{form.formState.errors.title.message}</span>}</label>
              <label className="text-xs text-ink-2">Type
                <select className={`${inputClass} mt-1`} {...form.register("doc_type")}>
                  {["rhp", "drhp", "prospectus", "annual_report", "disclosure", "other"].map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
                </select>
              </label>
              <label className="text-xs text-ink-2">Source URL (optional)<input className={`${inputClass} mt-1`} placeholder="https://www.sebi.gov.in/..." {...form.register("source_url")} />{form.formState.errors.source_url && <span className="text-neg-ink">{form.formState.errors.source_url.message}</span>}</label>
              <label className="text-xs text-ink-2">File (PDF or TXT, max 20 MB)<input type="file" accept=".pdf,.txt" className="mt-1 block w-full text-sm text-ink-2 file:mr-3 file:rounded-lg file:border-0 file:bg-surface-3 file:px-3 file:py-1.5 file:text-ink" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
              <div className="flex items-center gap-3 sm:col-span-2">
                <button className={buttonClass.primary} disabled={form.formState.isSubmitting}>{form.formState.isSubmitting && <Spinner />}Upload & ingest</button>
                {upMsg && <span className="text-sm text-ink-2" role="status">{upMsg}</span>}
              </div>
            </form>
          )}
        </div>
      </Panel>
    </div>
  );
}

const EXTRACTION_STYLE: Record<string, string> = {
  extracted: "border-pos/30 text-pos-ink", partial: "border-warn/30 text-warn-ink", pending: "border-brand/30 text-brand-ink",
  failed: "border-neg/40 text-neg-ink", not_found: "border-neg/30 text-neg-ink", skipped: "border-line text-ink-2",
};

function DocumentRow({ d }: { d: DocumentInfo }) {
  const [open, setOpen] = useState(false);
  const runs = useApi<{ runs: ExtractionRun[] }>(open ? `/api/documents/${d.id}/extractions` : null);
  const auto = d.source_key === "nse_rhp";
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium text-ink">{d.title}</div>
          <div className="mt-0.5 text-xs text-ink-3">
            {d.doc_type.toUpperCase()}{d.page_count ? ` · ${d.page_count} pages` : ""}{d.size_bytes ? ` · ${(d.size_bytes / 1e6).toFixed(1)} MB` : ""}
            {auto ? ` · retrieved automatically ${fmtDateTime(d.retrieved_at)}` : ` · added ${fmtDateTime(d.retrieved_at)}`}
            {d.last_checked_at ? ` · last checked ${fmtDateTime(d.last_checked_at)}` : ""}
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-xs">
            {d.file_url && <a className="text-brand-ink hover:underline" href={d.file_url} target="_blank" rel="noopener noreferrer">Open stored PDF</a>}
            {(d.archive_url || d.source_url) && <a className="text-brand-ink hover:underline" href={d.archive_url || d.source_url || "#"} target="_blank" rel="noopener noreferrer">Official source</a>}
            {d.sha256 && <span className="font-mono text-ink-3" title="SHA-256 of the stored file">sha256 {d.sha256.slice(0, 12)}…</span>}
            {auto && <button className="text-ink-2 hover:text-ink" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} extraction log</button>}
          </div>
          {d.extraction_error && <p className="mt-1 text-xs text-neg-ink/90">{d.extraction_error}</p>}
        </div>
        <div className="flex flex-col items-end gap-1">
          <DataStatusBadge status={d.data_status} />
          {d.extraction_status && auto && (
            <span className={`rounded-md border px-1.5 py-0.5 text-[11px] uppercase tracking-wide ${EXTRACTION_STYLE[d.extraction_status] ?? ""}`}>
              {d.extraction_status.replace("_", " ")}{d.parser_version ? ` · parser ${d.parser_version}` : ""}
            </span>
          )}
        </div>
      </div>
      {open && (
        <div className="mt-3 rounded-lg border border-line bg-surface p-3 text-xs">
          {runs.error ? <ErrorState message={runs.error} /> : !runs.data ? <Spinner /> : runs.data.runs.slice(0, 3).map((r) => (
            <div key={r.id} className="mb-3 last:mb-0">
              <div className="text-ink-2">Run {r.id} · {r.status} · parser {r.parser_version} · {r.pages_scanned} pages · {fmtDateTime(r.finished_at)}</div>
              {r.statements.map((st) => (
                <div key={`${st.kind}-${st.page}`} className="text-ink-2">• {({ bs: "Balance sheet", pl: "Profit and loss", cf: "Cash flow" } as Record<string, string>)[st.kind] ?? st.kind} on p{st.page} ({st.basis}, ₹ {st.unit}) — {st.periods.length} periods, {st.fields.length} fields</div>
              ))}
              {r.checks.map((c) => (
                <div key={`${c.period}-${c.basis}`} className={c.status === "passed" ? "text-pos-ink/80" : c.status === "failed" ? "text-neg-ink" : "text-warn-ink"}>
                  {c.period}: checks {c.status} ({c.checks.filter((x) => x.passed).length}/{c.checks.length})
                </div>
              ))}
              {r.warnings.map((w) => <div key={w} className="text-warn-ink">! {w}</div>)}
              {r.error && <div className="text-neg-ink">{r.error}</div>}
            </div>
          ))}
        </div>
      )}
    </li>
  );
}
