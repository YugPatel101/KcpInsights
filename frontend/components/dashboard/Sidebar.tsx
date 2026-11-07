"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BookOpenText,
  CalendarDays,
  Calculator,
  FileText,
  GitCompareArrows,
  History,
  LayoutDashboard,
  ListFilter,
  Settings,
  Star,
  Upload,
  X,
} from "lucide-react";

const groups = [
  {
    label: "Research",
    items: [
      { icon: LayoutDashboard, title: "Market overview", href: "/dashboard" },
      { icon: ListFilter, title: "IPO discovery", href: "/ipos" },
      { icon: CalendarDays, title: "Listing calendar", href: "/calendar" },
      { icon: Calculator, title: "Financial analysis", href: "/analysis" },
      { icon: GitCompareArrows, title: "Compare", href: "/compare" },
      { icon: History, title: "Listing history", href: "/history" },
    ],
  },
  {
    label: "Reference",
    items: [{ icon: BookOpenText, title: "Methodology", href: "/methodology" }],
  },
  {
    label: "Workspace",
    items: [
      { icon: Star, title: "Watchlist", href: "/watchlist" },
      { icon: FileText, title: "Reports", href: "/reports" },
    ],
  },
  {
    label: "System",
    items: [
      { icon: Activity, title: "System health", href: "/data" },
      { icon: Upload, title: "Import (optional)", href: "/import" },
      { icon: Settings, title: "Settings", href: "/settings" },
    ],
  },
];

export default function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/70 lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-line bg-surface px-3 py-5 transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="Primary"
      >
        <div className="mb-6 flex items-start justify-between px-2">
          <Link href="/" className="block" aria-label="KcpInsights home">
            <span className="text-lg font-semibold tracking-tight text-ink">
              Kcp<span className="text-brand-ink">Insights</span>
            </span>
            <span className="mt-0.5 block text-[11px] text-ink-3">Indian IPO research</span>
          </Link>
          <button onClick={onClose} className="rounded-md p-1 text-ink-3 hover:text-ink lg:hidden" aria-label="Close navigation">
            <X className="size-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto">
          {groups.map((g) => (
            <div key={g.label}>
              <p className="mb-1 px-2 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-3">{g.label}</p>
              <ul className="space-y-0.5">
                {g.items.map((item) => {
                  const Icon = item.icon;
                  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onClose}
                        aria-current={active ? "page" : undefined}
                        className={`flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition ${
                          active ? "bg-surface-3 font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                        }`}
                      >
                        <Icon size={16} className={active ? "text-brand-ink" : "text-ink-3"} aria-hidden />
                        {item.title}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <p className="mt-4 border-t border-line px-2 pt-4 text-[11px] leading-4 text-ink-3">
          Educational research. Scores summarise stored data under a versioned methodology; they are not advice or forecasts.
        </p>
      </aside>
    </>
  );
}
