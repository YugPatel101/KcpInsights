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
      className="flex min-w-0 max-w-xl flex-1 items-center justify-between rounded-md border border-line bg-surface px-3 py-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        router.push(`/ipos${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
      }}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <Search className="size-4 shrink-0 text-ink-3" aria-hidden />
        <input
          ref={ref}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search IPOs"
          placeholder="Search IPOs, companies, sectors..."
          className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
        />
      </div>
      <kbd className="hidden rounded border border-line px-1.5 py-0.5 text-[11px] text-ink-3 sm:block">⌘ K</kbd>
    </form>
  );
}
