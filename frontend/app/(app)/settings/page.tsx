"use client";

import { useState } from "react";
import { ErrorState, LoadingBlock, PageHeader, Panel, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { ModelsStatus } from "@/lib/types";

function SourceFetch() {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Panel title="Fetch an official document (Mode C)" subtitle="Administrator only. Allow-listed hosts (SEBI/NSE/BSE), https only, robots.txt respected, rate-limited and cached. Sites that block automated access must be uploaded manually.">
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setMsg(null);
          try {
            const d = await api<{ id: number; page_count: number; from_cache: boolean }>("/api/sources/fetch", { body: { url, title, doc_type: "disclosure" } });
            setMsg(`Ingested document #${d.id} (${d.page_count} pages${d.from_cache ? ", from cache" : ""}).`);
          } catch (x) {
            setMsg(errorMessage(x));
          } finally {
            setBusy(false);
          }
        }}
      >
        <input className={inputClass} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.sebi.gov.in/…pdf" aria-label="Document URL" />
        <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Document title" aria-label="Document title" />
        <div className="flex items-center gap-3 sm:col-span-2">
          <button className={buttonClass.primary} disabled={busy || url.length < 10 || title.length < 3}>{busy && <Spinner />}Fetch & ingest</button>
          {msg && <span className="text-sm text-ink-2" role="status">{msg}</span>}
        </div>
      </form>
    </Panel>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<ModelsStatus>("/api/models/status");

  return (
    <>
      <PageHeader eyebrow="Settings" title="Data & account" />
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingBlock rows={6} />}
      {data && (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Document retrieval">
              <p className="text-sm text-ink-2">{data.retrieval.chunks} chunks indexed · mode: {data.retrieval.mode}</p>
            </Panel>
            <Panel title="Scoring configuration">
              <p className="text-sm text-ink-2">Active version v{data.scoring.active_version}</p>
              <p className="mt-1 text-xs text-ink-3">{data.scoring.description}</p>
            </Panel>
          </div>

          {user?.is_admin && <SourceFetch />}

          <Panel title="Account">
            {user ? (
              <p className="text-sm text-ink-2">{user.display_name} · {user.email}{user.is_admin ? " · administrator" : ""}</p>
            ) : (
              <p className="text-sm text-ink-2">Not signed in.</p>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
