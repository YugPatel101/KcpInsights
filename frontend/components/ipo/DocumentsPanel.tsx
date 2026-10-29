"use client";

import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle } from "lucide-react";
import { DataStatusBadge, EmptyState, ErrorState, Notice, Panel, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { documentUploadSchema, type DocumentUpload } from "@/lib/schemas";
import type { DocumentInfo } from "@/lib/types";

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
            <p className="text-xs text-slate-500">Mode: {res.mode}{res.no_evidence ? ` — ${res.reason}` : ""}</p>
            {res.no_evidence && <Notice>No passage met the relevance threshold. Nothing is inferred when evidence is absent.</Notice>}
            {res.results.map((r) => (
              <blockquote key={r.chunk_id} className="rounded-xl border border-white/10 bg-black/30 p-4 text-sm">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span className="font-medium text-slate-200">{r.document_title}</span> · page {r.page} · score {r.score.toFixed(2)}
                  {r.injection_suspected && <span className="inline-flex items-center gap-1 text-amber-300"><AlertTriangle className="size-3" /> instruction-like text (treated as data)</span>}
                </div>
                <p className="whitespace-pre-wrap leading-6 text-slate-300">{r.text}</p>
              </blockquote>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Documents" subtitle="Offer documents and disclosures attached to this IPO">
        {documents.length ? (
          <ul className="divide-y divide-white/5 text-sm">
            {documents.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <div className="min-w-0">
                  <div className="font-medium text-slate-200">{d.source_url ? <a href={d.source_url} target="_blank" rel="noopener noreferrer" className="hover:underline">{d.title}</a> : d.title}</div>
                  <div className="text-xs text-slate-500">{d.doc_type.toUpperCase()} · {d.page_count} pages · added {fmtDateTime(d.retrieved_at)}{d.injection_flags ? ` · ${d.injection_flags} passage(s) flagged as instruction-like` : ""}</div>
                </div>
                <DataStatusBadge status={d.data_status} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No documents yet" body="Upload the RHP/DRHP or annual report PDF you obtained from SEBI, NSE, BSE or the company." />
        )}

        <div className="mt-6 border-t border-white/10 pt-5">
          <h3 className="mb-3 text-sm font-semibold text-white">Upload a document</h3>
          {!user ? (
            <p className="text-sm text-slate-400"><Link href={`/login?next=/ipos/${ipoId}`} className="text-sky-300 hover:underline">Sign in</Link> to upload documents.</p>
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
              <label className="text-xs text-slate-400">Title<input className={`${inputClass} mt-1`} {...form.register("title")} />{form.formState.errors.title && <span className="text-rose-300">{form.formState.errors.title.message}</span>}</label>
              <label className="text-xs text-slate-400">Type
                <select className={`${inputClass} mt-1`} {...form.register("doc_type")}>
                  {["rhp", "drhp", "prospectus", "annual_report", "disclosure", "other"].map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
                </select>
              </label>
              <label className="text-xs text-slate-400">Source URL (optional)<input className={`${inputClass} mt-1`} placeholder="https://www.sebi.gov.in/..." {...form.register("source_url")} />{form.formState.errors.source_url && <span className="text-rose-300">{form.formState.errors.source_url.message}</span>}</label>
              <label className="text-xs text-slate-400">File (PDF or TXT, max 20 MB)<input type="file" accept=".pdf,.txt" className="mt-1 block w-full text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-1.5 file:text-slate-200" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
              <div className="flex items-center gap-3 sm:col-span-2">
                <button className={buttonClass.primary} disabled={form.formState.isSubmitting}>{form.formState.isSubmitting && <Spinner />}Upload & ingest</button>
                {upMsg && <span className="text-sm text-slate-300" role="status">{upMsg}</span>}
              </div>
            </form>
          )}
        </div>
      </Panel>
    </div>
  );
}
