"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut, Menu, UserCircle2 } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { ModelsStatus } from "@/lib/types";
import SearchBar from "@/components/dashboard/SearchBar";

export default function DashboardTopbar({ onMenu }: { onMenu: () => void }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const status = useApi<ModelsStatus>("/api/models/status");
  const ai = status.data?.ai;

  return (
    <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-white/10 bg-black/80 px-4 py-3 backdrop-blur-xl sm:px-6">
      <button onClick={onMenu} className="rounded-lg border border-white/10 p-2 text-slate-300 lg:hidden" aria-label="Open navigation">
        <Menu className="size-5" />
      </button>

      <SearchBar />

      <Link
        href="/settings"
        className="hidden items-center gap-2 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-slate-400 hover:text-white md:inline-flex"
        title={ai?.reason}
      >
        <span className={`size-2 rounded-full ${status.error ? "bg-rose-400" : ai?.generative_available ? "bg-emerald-400" : "bg-amber-400"}`} aria-hidden />
        {status.error ? "API offline" : ai ? (ai.generative_available ? `AI: ${ai.active_mode}` : "AI: deterministic") : "Checking…"}
      </Link>

      {loading ? (
        <span className="h-9 w-24 animate-pulse rounded-xl bg-white/5" aria-hidden />
      ) : user ? (
        <div className="flex items-center gap-2">
          <span className="hidden max-w-40 truncate text-sm text-slate-300 sm:inline">{user.display_name}</span>
          <button
            onClick={async () => {
              await logout();
              router.push("/login");
            }}
            className="rounded-xl border border-white/10 p-2 text-slate-300 transition hover:bg-white/5"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut size={18} />
          </button>
        </div>
      ) : (
        <Link href="/login" className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:bg-white/5">
          <UserCircle2 size={18} aria-hidden /> Sign in
        </Link>
      )}
    </header>
  );
}
