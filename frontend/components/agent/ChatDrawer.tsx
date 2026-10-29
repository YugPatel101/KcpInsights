"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import ChatPanel, { type Turn } from "@/components/agent/ChatPanel";

/** Contextual research chat for one IPO, as a side drawer. */
export default function ChatDrawer({ ipoId, companyName, open, onClose }: { ipoId: number; companyName: string; open: boolean; onClose: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [convId, setConvId] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" aria-label={`Ask about ${companyName}`}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-white/10 bg-[#070708] p-4 sm:p-6">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold text-white">Ask about {companyName}</h2>
            <p className="text-xs text-slate-500">Context is kept across turns. <Link href={`/workspace?ipo=${ipoId}`} className="text-sky-300 hover:underline">Open full workspace</Link></p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:text-white" aria-label="Close chat"><X className="size-5" /></button>
        </div>
        <ChatPanel ipoId={ipoId} turns={turns} setTurns={setTurns} convId={convId} setConvId={setConvId} compact />
      </aside>
    </>
  );
}
