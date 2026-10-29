"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { ErrorState, LoadingBlock, Notice, PageHeader, Panel, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
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
          {msg && <span className="text-sm text-slate-300" role="status">{msg}</span>}
        </div>
      </form>
    </Panel>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const { data, error, loading, reload, setData } = useApi<ModelsStatus>("/api/models/status");
  const [checking, setChecking] = useState(false);

  const recheck = async () => {
    setChecking(true);
    try {
      setData(await api<ModelsStatus>("/api/models/status?refresh=true"));
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Settings" title="Models, data & account" actions={<button className={buttonClass.secondary} onClick={recheck} disabled={checking}>{checking && <Spinner />}Re-check providers</button>} />
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingBlock rows={6} />}
      {data && (
        <div className="space-y-6">
          <Panel title="AI provider" subtitle={`Configured: ${data.ai.configured_provider} · active: ${data.ai.active_mode}`}>
            <div className="flex items-start gap-3 text-sm">
              {data.ai.generative_available ? <CheckCircle2 className="mt-0.5 size-5 text-emerald-400" /> : <CircleAlert className="mt-0.5 size-5 text-amber-400" />}
              <div>
                <p className="text-slate-200">{data.ai.generative_available ? `Local model ${data.ai.ollama.model} is healthy.` : "No generative model available — using the deterministic research engine."}</p>
                <p className="mt-1 text-slate-400">{data.ai.reason}</p>
                <p className="mt-1 text-xs text-slate-500">{data.ai.fallback}</p>
              </div>
            </div>
            {data.ai.providers.map((p) => (
              <div key={p.name} className="mt-4 rounded-xl border border-white/10 p-3 text-xs text-slate-400">
                <div className="font-medium text-slate-200">{p.name} — {p.available ? "available" : "unavailable"}</div>
                <div>{p.detail}</div>
                {p.models_present.length > 0 && <div>Models present: {p.models_present.join(", ")}</div>}
                {p.embedding_model && <div>Embeddings ({p.embedding_model}): {p.embedding_available ? "available" : "not downloaded — keyword search is used"}</div>}
              </div>
            ))}
            {!data.ai.generative_available && (
              <Notice>
                Enable free local AI: install Ollama (ollama.com), then run <code className="font-mono">ollama pull {data.ai.ollama.model}</code> (≈2 GB; needs ~4 GB free RAM) and optionally{" "}
                <code className="font-mono">ollama pull {data.ai.ollama.embed_model}</code>. Low-memory machines: set <code className="font-mono">KCP_OLLAMA_USE_SMALL_MODEL=true</code> to use{" "}
                <code className="font-mono">{data.ai.ollama.small_model}</code>. Then press “Re-check providers”.
              </Notice>
            )}
          </Panel>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Document retrieval">
              <p className="text-sm text-slate-300">{data.retrieval.chunks} chunks indexed · {data.retrieval.embedded_chunks} with embeddings · mode: {data.retrieval.mode}</p>
            </Panel>
            <Panel title="Scoring configuration">
              <p className="text-sm text-slate-300">Active version v{data.scoring.active_version}</p>
              <p className="mt-1 text-xs text-slate-500">{data.scoring.description}</p>
            </Panel>
          </div>

          <Panel title="Listing-outcome model" subtitle={data.listing_model.warning}>
            <p className="text-sm text-slate-300">
              Real listed IPOs with verified/imported outcomes: <strong>{data.listing_model.real_listed_ipos}</strong> (minimum {data.listing_model.min_samples} before a model is trained).
            </p>
            {data.listing_model.models.length ? (
              <ul className="mt-3 space-y-2 text-xs text-slate-400">
                {data.listing_model.models.map((m) => (
                  <li key={m.id} className="rounded-lg border border-white/10 p-2">
                    <span className="text-slate-200">{m.version}</span> · {m.model_type} · {m.dataset_kind} · {m.status} · n={m.n_samples} · {fmtDateTime(m.created_at)}
                    {m.label && <div className="mt-1 font-semibold text-fuchsia-300">{m.label}</div>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-slate-500">No model has been trained. None is shown as reliable without real out-of-sample evidence.</p>
            )}
          </Panel>

          {user?.is_admin && <SourceFetch />}

          <Panel title="Account">
            {user ? (
              <p className="text-sm text-slate-300">{user.display_name} · {user.email}{user.is_admin ? " · administrator" : ""}</p>
            ) : (
              <p className="text-sm text-slate-400">Not signed in.</p>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
