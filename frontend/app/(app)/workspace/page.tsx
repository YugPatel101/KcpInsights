"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import ChatPanel, { type Turn } from "@/components/agent/ChatPanel";
import IpoPicker from "@/components/ipo/IpoPicker";
import { PageHeader, Panel, Spinner, buttonClass } from "@/components/kcp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { AgentResponse, ModelsStatus } from "@/lib/types";

function Workspace() {
  const sp = useSearchParams();
  const { user } = useAuth();
  const [ipoId, setIpoId] = useState<number | null>(sp.get("ipo") ? Number(sp.get("ipo")) : null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const status = useApi<ModelsStatus>("/api/models/status");
  const convs = useApi<{ id: number; title: string; updated_at: string }[]>(user ? `/api/agent/conversations?u=${user.id}` : null);

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
      setLoadError(errorMessage(e));
    }
  };

  const ai = status.data?.ai;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px] [&>*]:min-w-0">
      <div className="flex min-h-[65vh] flex-col">
        <ChatPanel ipoId={ipoId} turns={turns} setTurns={setTurns} convId={convId} setConvId={setConvId} onSaved={convs.reload} />
        {loadError && <p className="mt-2 text-sm text-rose-300">{loadError}</p>}
      </div>
      <aside className="space-y-4">
        <Panel title="Research context">
          <IpoPicker value={ipoId} onChange={setIpoId} allowEmpty label="Focus IPO (kept across turns)" />
          {ipoId && <Link href={`/ipos/${ipoId}`} className="mt-2 inline-block text-xs text-sky-300 hover:underline">Open research page</Link>}
          <button className={`${buttonClass.ghost} mt-3 w-full`} onClick={() => { setTurns([]); setConvId(null); }}>New conversation</button>
        </Panel>
        <Panel title="Engine">
          {ai ? (
            <p className="text-sm text-slate-300">
              {ai.generative_available
                ? <>Local model <span className="font-mono">{ai.ollama.model}</span> is healthy. It may request extra tools and writes a short summary; the cited points always come from the engine, and a summary with unsupported numbers, misattributed dates or advice is replaced.</>
                : <>Deterministic engine (no generative model available). Factual answers are templated from the same tools and data.</>}
            </p>
          ) : (
            <Spinner />
          )}
          <p className="mt-2 text-xs text-slate-500">Badges show whether each point is a sourced fact, a calculation, an interpretation or a hypothetical scenario.</p>
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
      <PageHeader eyebrow="AI research workspace" title="Research agent" subtitle="A bounded, auditable tool-using agent over live NSE data, your imports and offer documents. Scores come from the deterministic engine; every point cites stored evidence." />
      <Suspense fallback={<Spinner />}>
        <Workspace />
      </Suspense>
    </>
  );
}
