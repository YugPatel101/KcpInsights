"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  TrendingUp,
  Star,
  Brain,
  Settings,
  Calculator,
  GitCompareArrows,
  FileText,
  Upload,
  X,
} from "lucide-react";

const menu = [
  { icon: LayoutDashboard, title: "Dashboard", href: "/dashboard" },
  { icon: TrendingUp, title: "IPOs", href: "/ipos" },
  { icon: Calculator, title: "Quant analysis", href: "/analysis" },
  { icon: GitCompareArrows, title: "Compare", href: "/compare" },
  { icon: Brain, title: "AI Research", href: "/workspace" },
  { icon: FileText, title: "Reports", href: "/reports" },
  { icon: Star, title: "Watchlist", href: "/watchlist" },
  { icon: Upload, title: "Import data", href: "/import" },
  { icon: Settings, title: "Settings", href: "/settings" },
];

export default function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-white/10 bg-black/95 px-4 py-6 backdrop-blur-xl transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 lg:bg-black/50 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="Primary"
      >
        <div className="mb-10 flex items-start justify-between px-2">
          <Link href="/" className="block">
            <h1 className="text-2xl font-bold">
              Kcp<span className="text-slate-400">Insights</span>
            </h1>
            <p className="mt-1 text-xs text-slate-500">IPO research · educational</p>
          </Link>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:text-white lg:hidden" aria-label="Close navigation">
            <X className="size-5" />
          </button>
        </div>

        <nav className="space-y-1">
          {menu.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                aria-current={active ? "page" : undefined}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${
                  active ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-white/5 hover:text-white"
                }`}
              >
                <Icon size={18} aria-hidden />
                <span className="font-medium">{item.title}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-xs leading-5 text-slate-500">
          Educational research only. Scores summarise stored data under a versioned methodology — they are not advice or forecasts.
        </div>
      </aside>
    </>
  );
}
