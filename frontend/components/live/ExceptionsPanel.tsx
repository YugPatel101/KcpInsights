"use client";

import Link from "next/link";
import { useState } from "react";
import { EmptyState, ErrorState, LoadingBlock, Panel, Spinner, buttonClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { ExceptionsReport } from "@/lib/types";

/** What the pipeline could not resolve on its own. Nothing here blocks automatic operation. */
export default function ExceptionsPanel() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<ExceptionsReport>("/api/data/exceptions", { refreshMs: 120_000 });
  const [busy, setBusy] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <LoadingBlock rows={3} />;
  const total = data.documents.length + data.statements_requiring_review.length + data.field_conflicts.length + data.peer_rows_requiring_review.length;
  const reprocess = async (id: number) => {
    setBusy(id);
    setMsg(null);
    try {
      const r = await api<{ status: string }>(`/api/admin/documents/${id}/reprocess`, { method: "POST" });
      setMsg(`Document ${id}: ${r.status}`);
      reload();
    } catch (e) {
      setMsg(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <Panel title={`Exceptions (${total})`} subtitle={`${data.note} ${data.documents_pending} offer document(s) are queued for automatic download.`}>
      {msg && <p className="mb-3 text-sm text-ink-2" role="status">{msg}</p>}
      {!total && <EmptyState title="No exceptions" body="Every downloaded document was extracted and reconciled." />}
      {data.documents.length > 0 && (
        <section className="mb-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-2">Offer documents not fully extracted</h3>
          <ul className="divide-y divide-line text-sm">
            {data.documents.map((d) => (
              <li key={d.document_id} className="flex flex-wrap items-start justify-between gap-3 py-2">
                <div className="min-w-0">
                  {d.ipo_id ? <Link href={`/ipos/${d.ipo_id}`} className="text-ink hover:underline">{d.company_name}</Link> : <span className="text-ink">document {d.document_id}</span>}
                  <span className={`ml-2 text-xs uppercase ${d.status === "partial" ? "text-warn-ink" : "text-neg-ink"}`}>{d.status.replace("_", " ")}</span>
                  <p className="text-xs leading-5 text-ink-3" title={d.error ?? undefined}>
                    {d.error ? (d.error.length > 220 ? `${d.error.slice(0, 220)}…` : d.error) : "some statements were not found or could not be reconciled"} · {fmtDateTime(d.extracted_at)}
                  </p>
                </div>
                {user?.is_admin && (
                  <button className={buttonClass.secondary} disabled={busy === d.document_id} onClick={() => reprocess(d.document_id)}>
                    {busy === d.document_id && <Spinner />}Re-run extraction
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.statements_requiring_review.length > 0 && (
        <section className="mb-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-2">Periods that failed an accounting check (excluded from scores)</h3>
          <ul className="space-y-1 text-sm">
            {data.statements_requiring_review.map((s) => (
              <li key={s.statement_id}>
                <Link href={`/ipos/${s.ipo_id}`} className="text-ink hover:underline">{s.company_name}</Link> <span className="text-ink-3">{s.period_label} ({s.basis}):</span>{" "}
                <span className="text-neg-ink">{s.failed_checks.map((c) => `${c.formula} (difference ${fmtNum(c.difference, 2)})`).join("; ")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.peer_rows_requiring_review.length > 0 && (
        <section className="mb-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-2">Peer rows that failed the P/E cross-check (not used)</h3>
          <ul className="space-y-1 text-sm">
            {data.peer_rows_requiring_review.map((p, i) => (
              <li key={i}><Link href={`/ipos/${p.ipo_id}`} className="text-ink hover:underline">{p.company_name}</Link> <span className="text-ink-3">· {p.peer} — {p.note ?? "column layout unconfirmed"}{p.page ? ` (p${p.page})` : ""}</span></li>
            ))}
          </ul>
        </section>
      )}
      {data.field_conflicts.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-2">Conflicting source values</h3>
          <ul className="space-y-1 text-sm">
            {data.field_conflicts.map((c, i) => (
              <li key={i}><Link href={`/ipos/${c.ipo_id}`} className="text-ink hover:underline">{c.company_name}</Link> <span className="text-ink-3">· {c.field} = {c.value} from {c.source_key} · {fmtDateTime(c.observed_at)}</span></li>
            ))}
          </ul>
        </section>
      )}
    </Panel>
  );
}
