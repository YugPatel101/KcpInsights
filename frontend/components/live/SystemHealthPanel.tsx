"use client";

import Link from "next/link";
import { ErrorState, LoadingBlock, Notice, Panel, tableClass } from "@/components/kcp/ui";
import { fmtDateTime, fmtPct, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { SystemHealth } from "@/lib/types";

const STAGE: Record<string, string> = {
  discovered: "Discovered", located: "Offer document located", downloaded: "Downloaded & hashed", extracted: "Statements extracted",
  validated: "Accounting checks passed", calculated: "Ratios calculated", scored: "Scored",
};
const STATUSES = ["extracted", "partial", "not_found", "failed", "pending", "duplicate"];
const SOURCE: Record<string, string> = { nse_rhp: "NSE RHP archive", sebi_rhp: "SEBI RHP filings", sebi_drhp: "SEBI DRHP filings", upload: "Uploads" };

/** Pipeline monitoring: stage funnel, document processing by source, dead letters, completeness and integrity. */
export default function SystemHealthPanel() {
  const { data, error, reload } = useApi<SystemHealth>("/api/system/health", { refreshMs: 30_000 });
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <LoadingBlock rows={4} />;
  const total = data.completeness.ipos || 1;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
        <Panel title="Pipeline funnel" subtitle={`Where the ${data.completeness.ipos} real IPOs on record stand (demo records excluded)`}>
          <ul className="space-y-2.5">
            {data.pipeline_funnel.map((f) => (
              <li key={f.stage}>
                <div className="mb-1 flex justify-between gap-2 text-sm"><span className="text-ink-2">{STAGE[f.stage] ?? f.stage}</span>
                  <span className="tabular-nums text-ink">{f.done}{f.failed ? <span className="ml-2 text-xs text-neg-ink">{f.failed} failed</span> : null}{f.pending ? <span className="ml-2 text-xs text-ink-3">{f.pending} pending</span> : null}</span></div>
                <div className="flex h-1.5 overflow-hidden rounded-full bg-surface-3" role="img" aria-label={`${STAGE[f.stage]}: ${f.done} done, ${f.failed} failed, ${f.pending} pending`}>
                  <span className="bg-pos" style={{ width: `${(f.done / total) * 100}%` }} />
                  <span className="bg-neg" style={{ width: `${(f.failed / total) * 100}%` }} />
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink-3">Median data completeness {fmtPct(data.completeness.median, 0)}; {data.completeness.below_50} IPO(s) below 50%.</p>
        </Panel>
        <Panel title="Offer-document processing" subtitle={`Parser v${data.documents.parser_version} · ${data.documents.retained_mb} of ${data.documents.storage_limit_mb} MB stored · OCR ${data.documents.ocr_available ? (data.documents.ocr_enabled ? "available (Tesseract)" : "installed but disabled") : "not installed"}`}>
          <div className={tableClass.wrap}>
            <table className={`${tableClass.table} min-w-[520px]`}>
              <thead className={tableClass.thead}><tr><th className={tableClass.th}>Source</th>{STATUSES.map((s) => <th key={s} className={`${tableClass.th} text-right`}>{titleCase(s)}</th>)}</tr></thead>
              <tbody>
                {Object.entries(data.documents.by_source_and_status).map(([src, counts]) => (
                  <tr key={src} className={tableClass.tr}>
                    <td className={`${tableClass.td} text-ink`}>{SOURCE[src] ?? src}</td>
                    {STATUSES.map((s) => <td key={s} className={`${tableClass.td} ${tableClass.num}`}>{counts[s] ?? 0}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.documents.awaiting_reprocessing > 0 && <p className="mt-2 text-xs text-ink-3">{data.documents.awaiting_reprocessing} stored document(s) will be re-read by the current parser on upcoming runs.</p>}
          <p className="mt-2 text-xs text-ink-3">Failed downloads and extractions retry with exponential backoff (1 h, 2 h, 4 h … up to 7 days); after {data.documents.max_attempts} attempts a document becomes a dead letter.</p>
        </Panel>
      </div>

      {(data.dead_letters.length > 0 || data.backing_off.length > 0) && (
        <Panel title="Retries and dead letters" subtitle="Documents the pipeline could not fetch or read; earlier data is never removed">
          <div className={tableClass.wrap}>
            <table className={tableClass.table}>
              <thead className={tableClass.thead}><tr><th className={tableClass.th}>Document</th><th className={tableClass.th}>State</th><th className={`${tableClass.th} text-right`}>Attempts</th><th className={tableClass.th}>Error</th></tr></thead>
              <tbody>
                {[...data.dead_letters.map((d) => ({ ...d, state: "dead letter" })), ...data.backing_off.map((d) => ({ ...d, state: `retry after ${fmtDateTime(d.next_attempt_at)}` }))].map((d) => (
                  <tr key={`${d.document_id}-${d.state}`} className={`${tableClass.tr} align-top`}>
                    <td className={tableClass.td}>{d.ipo_id ? <Link href={`/ipos/${d.ipo_id}`} className="text-ink hover:text-brand-ink">{d.title}</Link> : d.title}</td>
                    <td className={`${tableClass.td} text-xs ${d.state === "dead letter" ? "text-neg-ink" : "text-warn-ink"}`}>{d.state}</td>
                    <td className={`${tableClass.td} ${tableClass.num}`}>{d.attempts}</td>
                    <td className={`${tableClass.td} text-xs text-ink-3`}>{d.error?.slice(0, 200)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
        <Panel title="Jobs in the last 24 hours" className="lg:col-span-2">
          {data.jobs_24h.length ? (
            <div className={tableClass.wrap}>
              <table className={`${tableClass.table} min-w-[600px]`}>
                <thead className={tableClass.thead}><tr>
                  <th className={tableClass.th}>Job</th><th className={`${tableClass.th} text-right`}>Runs</th><th className={`${tableClass.th} text-right`}>OK</th>
                  <th className={`${tableClass.th} text-right`}>Partial</th><th className={`${tableClass.th} text-right`}>Failed</th><th className={`${tableClass.th} text-right`}>Requests</th><th className={tableClass.th}>Last</th>
                </tr></thead>
                <tbody>
                  {data.jobs_24h.map((j) => (
                    <tr key={j.job_type} className={`${tableClass.tr} align-top`}>
                      <td className={`${tableClass.td} text-ink`}>{titleCase(j.job_type)}</td>
                      <td className={`${tableClass.td} ${tableClass.num}`}>{j.runs}</td>
                      <td className={`${tableClass.td} ${tableClass.num}`}>{j.success}</td>
                      <td className={`${tableClass.td} ${tableClass.num}`}>{j.partial}</td>
                      <td className={`${tableClass.td} ${tableClass.num} ${j.failed ? "text-neg-ink" : ""}`}>{j.failed}</td>
                      <td className={`${tableClass.td} ${tableClass.num}`}>{j.requests}</td>
                      <td className={`${tableClass.td} text-xs`}>{j.last_status} · {fmtDateTime(j.last_finished_at)}{j.last_error && <span className="block text-neg-ink">{j.last_error.slice(0, 120)}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="text-sm text-ink-3">No jobs ran in the last 24 hours.</p>}
        </Panel>
        <Panel title="Integrity">
          <dl className="divide-y divide-line text-sm">
            <div className="flex justify-between py-2"><dt className="text-ink-3">Statement periods requiring review</dt><dd className="tabular-nums text-ink">{data.integrity.statements_requiring_review}</dd></div>
            <div className="flex justify-between py-2"><dt className="text-ink-3">Source conflicts recorded</dt><dd className="tabular-nums text-ink">{data.integrity.field_conflicts}</dd></div>
            <div className="flex justify-between py-2"><dt className="text-ink-3">Live issues with stale details</dt><dd className="tabular-nums text-ink">{data.integrity.stale_live_issues.length}</dd></div>
          </dl>
          <div className="mt-3"><Notice>{data.hosting_note}</Notice></div>
        </Panel>
      </div>
    </div>
  );
}
