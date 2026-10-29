"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

export default function SearchBar() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <form
      role="search"
      className="flex min-w-0 flex-1 items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        router.push(`/ipos${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
      }}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <Search className="size-4 shrink-0 text-slate-400" aria-hidden />
        <input
          ref={ref}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search IPOs"
          placeholder="Search IPOs, companies, sectors..."
          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-500"
        />
      </div>
      <kbd className="hidden rounded-md border border-white/10 px-2 py-0.5 text-xs text-slate-500 sm:block">⌘ K</kbd>
    </form>
  );
}
