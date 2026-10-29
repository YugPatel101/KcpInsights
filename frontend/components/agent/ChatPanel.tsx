"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Brain, Check, ChevronDown, ChevronRight, Copy, Cpu, FileText, RotateCcw, Send, Wrench } from "lucide-react";
import { DataStatusBadge, ErrorState, Notice, Spinner, buttonClass, inputClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import type { AgentResponse, Evidence, ModelsStatus, PointKind } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export interface Turn {
  role: "user" | "assistant";
  text: string;
  res?: AgentResponse;
  failed?: boolean;
}

const KIND_STYLE: Record<PointKind, string> = {
  fact: "border-emerald-500/30 text-emerald-300",
  calculation: "border-sky-500/30 text-sky-300",
  interpretation: "border-violet-400/30 text-violet-300",
  hypothetical: "border-amber-500/30 text-amber-300",
};
const KIND_LABEL: Record<PointKind, string> = { fact: "source", calculation: "calculated", interpretation: "interpretation", hypothetical: "hypothetical" };

export const GENERAL_SUGGESTIONS = [
  "Which IPOs are opening next week?",
  "Which IPOs are open right now?",
  "Which IPOs list this week?",
  "Show recently listed IPOs",
];
export const IPO_SUGGESTIONS = [
  "What is the latest status of this IPO?",
  "When is it expected to list? Has the listing date changed?",
  "What is the latest subscription status?",
  "Why is its quantitative score what it is?",
  "What is known and still missing about this issue?",
  "Show me the source for the listing date",
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

function AssistantMessage({ res, ipoId, onRetry }: { res: AgentResponse; ipoId: number | null; onRetry?: () => void }) {
  const [showTools, setShowTools] = useState(false);
  const [copied, setCopied] = useState(false);
  const a = res.answer;
  const reportIpo = ipoId ?? res.ipo_ids[0] ?? null;
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {res.generative ? <Brain className="size-3.5" aria-hidden /> : <Cpu className="size-3.5" aria-hidden />}
        {res.generative
          ? `Summary written by the local model (${res.mode.split(":").slice(1).join(":")}) and checked; the points below come from the research engine`
          : "Deterministic research engine — generative AI not used"}
        {res.elapsed_ms ? ` · ${res.elapsed_ms} ms` : ""}
      </div>
      {/* Plain text nodes only: model output is never rendered as HTML. */}
      <p className="text-sm leading-6 text-slate-100">{a.summary}</p>
      {res.generative && a.points.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">AI summaries can word things loosely; the cited points are the verified record.</p>
      )}
      {a.points.length > 0 && (
        <ul className="mt-3 space-y-2 text-sm leading-6 text-slate-300">
          {a.points.map((p, i) => {
            const kind = p.kind ?? "fact";
            return (
              <li key={i} className="flex gap-2">
                <span className={`mt-1 h-fit shrink-0 rounded border px-1 text-[10px] uppercase tracking-wide ${KIND_STYLE[kind]}`} title={`Point type: ${kind}`}>{KIND_LABEL[kind]}</span>
                <span className="whitespace-pre-wrap">
                  {p.text}{" "}
                  {p.evidence.map((e) => (
                    <a key={e} href={`#ev-${e}`} className="font-mono text-xs text-sky-300 hover:underline">[{e}]</a>
                  ))}
                </span>
              </li>
            );
          })}
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
      <div className="mt-3 flex flex-wrap items-center gap-1">
        <button className={buttonClass.ghost} onClick={() => setShowTools(!showTools)} aria-expanded={showTools}>
          {showTools ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}<Wrench className="size-3" /> {res.tool_calls.length} tool call(s)
        </button>
        <button
          className={buttonClass.ghost}
          onClick={async () => {
            await navigator.clipboard.writeText(res.answer_text);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />} {copied ? "Copied" : "Copy"}
        </button>
        {onRetry && <button className={buttonClass.ghost} onClick={onRetry}><RotateCcw className="size-3" /> Retry</button>}
        {reportIpo && <Link className={buttonClass.ghost} href={`/ipos/${reportIpo}`}><FileText className="size-3" /> Open IPO</Link>}
      </div>
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

export default function ChatPanel({
  ipoId,
  turns,
  setTurns,
  convId,
  setConvId,
  onSaved,
  compact = false,
}: {
  ipoId: number | null;
  turns: Turn[];
  setTurns: (f: (t: Turn[]) => Turn[]) => void;
  convId: number | null;
  setConvId: (id: number | null) => void;
  onSaved?: () => void;
  compact?: boolean;
}) {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = useApi<ModelsStatus>("/api/models/status");
  const endRef = useRef<HTMLDivElement>(null);
  const ai = status.data?.ai;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns, busy]);

  const send = async (text: string, retry = false) => {
    if (text.trim().length < 2 || busy) return;
    if (!retry) setTurns((t) => [...t, { role: "user", text }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await api<AgentResponse>("/api/agent/chat", { body: { message: text, ipo_id: ipoId, conversation_id: convId } });
      setTurns((t) => [...t.filter((x) => !x.failed), { role: "assistant", text: res.answer_text, res }]);
      if (res.conversation_id) {
        setConvId(res.conversation_id);
        onSaved?.();
      }
    } catch (e) {
      setError(errorMessage(e));
      setTurns((t) => (t.some((x) => x.failed) ? t : [...t, { role: "assistant", text, failed: true }]));
    } finally {
      setBusy(false);
    }
  };

  const lastUser = [...turns].reverse().find((t) => t.role === "user")?.text;
  const suggestions = ipoId ? IPO_SUGGESTIONS : GENERAL_SUGGESTIONS;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {ai && !ai.generative_available && !compact && (
        <div className="mb-3"><Notice>Generative AI is unavailable ({ai.reason}). Answers come from the deterministic engine using the same tools and data. <Link href="/settings" className="underline">Enable a local model</Link>.</Notice></div>
      )}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        {turns.length === 0 && (
          <div>
            <p className="mb-2 text-sm text-slate-400">The agent reads the KcpInsights database (live NSE data, imports, documents) and the scoring engine, and cites every point.</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button key={s} className={`${buttonClass.secondary} text-left`} onClick={() => void send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="ml-auto max-w-[85%] rounded-2xl bg-slate-800 px-4 py-2.5 text-sm text-white">{t.text}</div>
          ) : t.res ? (
            <AssistantMessage key={i} res={t.res} ipoId={ipoId} onRetry={i === turns.length - 1 && lastUser ? () => void send(lastUser, true) : undefined} />
          ) : t.failed ? null : (
            <div key={i} className="whitespace-pre-wrap rounded-2xl border border-white/10 p-4 text-sm text-slate-300">{t.text}</div>
          ),
        )}
        {busy && (
          <div className="flex items-center gap-2 text-sm text-slate-400" role="status">
            <Spinner /> Querying the database and tools{ai?.generative_available ? ", then the local model (usually 10–30 s)" : ""}…
          </div>
        )}
        {error && (
          <div className="space-y-2">
            <ErrorState message={error} onRetry={lastUser ? () => void send(lastUser, true) : undefined} />
          </div>
        )}
        <div ref={endRef} />
      </div>
      <form
        className="mt-4 flex gap-2 border-t border-white/10 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input.trim());
        }}
      >
        <input className={`${inputClass} flex-1`} value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000}
          placeholder={ipoId ? "Ask about this IPO…" : "e.g. Which IPOs are opening next week?"} aria-label="Research question" />
        <button className={buttonClass.primary} disabled={busy || input.trim().length < 2} aria-label="Send"><Send className="size-4" /></button>
      </form>
    </div>
  );
}
