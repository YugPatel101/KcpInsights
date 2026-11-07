"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut, Menu, UserCircle2 } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { timeAgo } from "@/lib/time";
import type { SyncStatus } from "@/lib/types";
import SearchBar from "@/components/dashboard/SearchBar";

export default function DashboardTopbar({ onMenu }: { onMenu: () => void }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  // Last successful sync from the scheduler's job log (no "live" claim: it shows when data was last fetched).
  const status = useApi<SyncStatus>("/api/data/sync-status?limit=15", { refreshMs: 120_000 });
  const last = status.data?.jobs.find((j) => j.status === "success" || j.status === "partial");

  return (
    <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-canvas/90 px-4 py-2.5 backdrop-blur sm:px-6 lg:px-8">
      <button onClick={onMenu} className="rounded-md border border-line p-2 text-ink-2 lg:hidden" aria-label="Open navigation">
        <Menu className="size-5" />
      </button>

      <SearchBar />

      <Link
        href="/data"
        className="hidden items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-2 hover:text-ink md:inline-flex"
        title={last?.finished_at ? `Last successful ${last.job_type} job: ${last.finished_at} UTC` : undefined}
      >
        <span className={`size-2 rounded-full ${status.error ? "bg-neg" : status.data?.scheduler.running ? "bg-pos" : "bg-warn"}`} aria-hidden />
        {status.error ? "API offline" : status.data ? `Data synced ${timeAgo(last?.finished_at)}` : "Checking…"}
      </Link>

      {loading ? (
        <span className="h-8 w-24 animate-pulse rounded-md bg-surface-3" aria-hidden />
      ) : user ? (
        <div className="flex items-center gap-2">
          <span className="hidden max-w-40 truncate text-sm text-ink-2 sm:inline">{user.display_name}</span>
          <button
            onClick={async () => {
              await logout();
              router.push("/login");
            }}
            className="rounded-md border border-line p-2 text-ink-2 transition hover:bg-surface-3"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut size={18} />
          </button>
        </div>
      ) : (
        <Link href="/login" className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-sm text-ink-2 transition hover:bg-surface-3">
          <UserCircle2 size={18} aria-hidden /> Sign in
        </Link>
      )}
    </header>
  );
}
