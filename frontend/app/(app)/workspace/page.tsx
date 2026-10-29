"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Brain, ChevronDown, ChevronRight, Cpu, Send, Wrench } from "lucide-react";
import IpoPicker from "@/components/ipo/IpoPicker";
import { DataStatusBadge, ErrorState, Notice, PageHeader, Panel, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { AgentResponse, Evidence, ModelsStatus } from "@/lib/types";

interface Turn {
  role: "user" | "assistant";
  text: string;
  res?: AgentResponse;
}

const SUGGESTIONS = [
  "Explain why this IPO has its research score",
  "What are the main risks from the offer document?",
  "Explain the valuation relative to peers",
  "Run best, base and worst case scenarios",
  "What data is missing before this IPO can be evaluated?",
  "Generate a research report",
];

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  const cited = evidence.filter((e) => e.cited);
  if (!cited.length) return null;
  return (
    <ol className="mt-3 space-y-1 border-t border-white/10 pt-3 text-xs">
      {cited.map((e) => (
        <li key={e.id} id={`ev-${e.id}`} className="flex flex-wrap items-center gap-2 text-slate-400">
          <span className="font-mono text-slate-300">[{e.id}]</span>
          {e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer" className="text-sky-300 hover:underline">{e.label}</a> : <span>{e.label}</span>}
          <span className="text-slate-600">{e.kind.replace("_", " ")}{e.page ? ` · p.${e.page}` : ""}</span>
          {e.data_status && <DataStatusBadge status={e.data_status} compact />}
        </li>
      ))}
    </ol>
  );
}

function AssistantMessage({ res }: { res: AgentResponse }) {
  const [showTools, setShowTools] = useState(false);
  const a = res.answer;
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {res.generative ? <Brain className="size-3.5" aria-hidden /> : <Cpu className="size-3.5" aria-hidden />}
        {res.generative ? `Local model (${res.mode.split(":").slice(1).join(":")}) · validated against tool results` : "Deterministic research engine (no generative AI)"}
        · {res.elapsed_ms} ms
      </div>
      {/* Rendered as plain text nodes — model output is never injected as HTML. */}
      <p className="text-sm leading-6 text-slate-100">{a.summary}</p>
      {a.points.length > 0 && (
        <ul className="mt-3 space-y-2 text-sm leading-6 text-slate-300">
          {a.points.map((p, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-slate-500" aria-hidden />
              <span className="whitespace-pre-wrap">
                {p.text}{" "}
                {p.evidence.map((e) => (
                  <a key={e} href={`#ev-${e}`} className="font-mono text-xs text-sky-300 hover:underline">[{e}]</a>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}
      {a.limitations.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-5 text-amber-100/90">
          <div className="mb-1 font-semibold">Limitations</div>
          <ul className="list-disc space-y-0.5 pl-4">{a.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      )}
      {res.warnings.length > 0 && <p className="mt-2 text-xs text-slate-500">Notes: {res.warnings.join(" · ")}</p>}
      {res.report_id && <p className="mt-2 text-sm"><Link href={`/reports/${res.report_id}`} className="text-sky-300 hover:underline">Open saved report #{res.report_id}</Link></p>}
      <EvidenceList evidence={res.evidence} />
      <button className="mt-3 flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200" onClick={() => setShowTools(!showTools)} aria-expanded={showTools}>
        {showTools ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}<Wrench className="size-3" /> {res.tool_calls.length} tool call(s)
      </button>
      {showTools && (
        <ul className="mt-2 space-y-1 font-mono text-[11px] text-slate-400">
          {res.tool_calls.map((t, i) => (
            <li key={i}>
              <span className={t.status === "ok" ? "text-emerald-300" : "text-rose-300"}>{t.status}</span> {t.tool}({JSON.stringify(t.arguments)}) — {t.summary} · {t.duration_ms} ms
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Workspace() {
  const sp = useSearchParams();
  const { user } = useAuth();
  const [ipoId, setIpoId] = useState<number | null>(sp.get("ipo") ? Number(sp.get("ipo")) : null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = useApi<ModelsStatus>("/api/models/status");
  const convs = useApi<{ id: number; title: string; updated_at: string }[]>(user ? `/api/agent/conversations?u=${user.id}` : null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  const send = async (text: string) => {
    if (text.trim().length < 2 || busy) return;
    setTurns((t) => [...t, { role: "user", text }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await api<AgentResponse>("/api/agent/chat", { body: { message: text, ipo_id: ipoId, conversation_id: convId } });
      setTurns((t) => [...t, { role: "assistant", text: res.answer_text, res }]);
      if (res.conversation_id) {
        setConvId(res.conversation_id);
        convs.reload();
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const loadConversation = async (id: number) => {
    try {
      const c = await api<{ id: number; ipo_id: number | null; messages: { role: "user" | "assistant"; content: string; meta: Partial<AgentResponse> }[] }>(`/api/agent/conversations/${id}`);
      setConvId(c.id);
      setIpoId(c.ipo_id);
      setTurns(
        c.messages.map((m) =>
          m.role === "assistant" && m.meta.answer
            ? { role: "assistant", text: m.content, res: { answer_text: m.content, generative: (m.meta.mode ?? "deterministic") !== "deterministic", elapsed_ms: 0, saved: true, conversation_id: c.id, report_id: null, ...m.meta } as AgentResponse }
            : { role: m.role, text: m.content },
        ),
      );
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const ai = status.data?.ai;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <div className="flex min-h-[60vh] flex-col">
        <div className="flex-1 space-y-4">
          {turns.length === 0 && (
            <Panel title="Ask a research question" subtitle="The agent calls KcpInsights tools (scores, financials, peers, documents, scenarios) and cites every point. It cannot browse the web or change data.">
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className={buttonClass.secondary} onClick={() => void send(s)} disabled={!ipoId && !s.includes("missing")}>{s}</button>
                ))}
              </div>
              {!ipoId && <p className="mt-3 text-xs text-slate-500">Choose an IPO on the right, or name the company in your question.</p>}
            </Panel>
          )}
          {turns.map((t, i) =>
            t.role === "user" ? (
              <div key={i} className="ml-auto max-w-[85%] rounded-2xl bg-slate-800 px-4 py-2.5 text-sm text-white">{t.text}</div>
            ) : t.res ? (
              <AssistantMessage key={i} res={t.res} />
            ) : (
              <div key={i} className="whitespace-pre-wrap rounded-2xl border border-white/10 p-4 text-sm text-slate-300">{t.text}</div>
            ),
          )}
          {busy && (
            <div className="flex items-center gap-2 text-sm text-slate-400" role="status">
              <Spinner /> Running tools{ai?.generative_available ? " and the local model (can take up to a minute)" : ""}…
            </div>
          )}
          {error && <ErrorState message={error} />}
          <div ref={endRef} />
        </div>
        <form
          className="sticky bottom-0 mt-6 flex gap-2 bg-black/80 py-3 backdrop-blur"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input.trim());
          }}
        >
          <input className={`${inputClass} flex-1`} value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000} placeholder="e.g. Compare Aravalli and Kaveri on valuation and risk" aria-label="Research question" />
          <button className={buttonClass.primary} disabled={busy || input.trim().length < 2} aria-label="Send"><Send className="size-4" /></button>
        </form>
      </div>

      <aside className="space-y-4">
        <Panel title="Research context">
          <IpoPicker value={ipoId} onChange={setIpoId} allowEmpty label="Focus IPO" />
          {ipoId && <Link href={`/ipos/${ipoId}`} className="mt-2 inline-block text-xs text-sky-300 hover:underline">Open research page</Link>}
          <button className={`${buttonClass.ghost} mt-3 w-full`} onClick={() => { setTurns([]); setConvId(null); }}>New conversation</button>
        </Panel>
        <Panel title="Engine">
          {ai ? (
            ai.generative_available ? (
              <p className="text-sm text-slate-300">Local model <span className="font-mono">{ai.ollama.model}</span> is healthy. Its answers are checked against tool outputs; unsupported numbers are dropped.</p>
            ) : (
              <Notice>No local model is available ({ai.reason}). Answers come from the deterministic research engine using the same tools — they are templated, not generated. <Link href="/settings" className="underline">Enable Ollama</Link>.</Notice>
            )
          ) : (
            <Spinner />
          )}
        </Panel>
        <Panel title="Saved conversations">
          {!user ? (
            <p className="text-sm text-slate-400"><Link href="/login?next=/workspace" className="text-sky-300 hover:underline">Sign in</Link> to save conversations. Anonymous chats are not stored.</p>
          ) : convs.data?.length ? (
            <ul className="space-y-1 text-sm">
              {convs.data.map((c) => (
                <li key={c.id}>
                  <button className={`w-full truncate rounded-lg px-2 py-1.5 text-left hover:bg-white/5 ${c.id === convId ? "bg-white/5 text-white" : "text-slate-300"}`} onClick={() => void loadConversation(c.id)} title={fmtDateTime(c.updated_at)}>
                    {c.title}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">None yet.</p>
          )}
        </Panel>
      </aside>
    </div>
  );
}

export default function WorkspacePage() {
  return (
    <>
      <PageHeader eyebrow="AI research workspace" title="Research agent" subtitle="A bounded, auditable tool-using agent. Scores come from the deterministic engine; the agent explains them with citations to stored evidence." />
      <Suspense fallback={<Spinner />}>
        <Workspace />
      </Suspense>
    </>
  );
}
