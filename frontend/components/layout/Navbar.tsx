"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

const navLinks = [
  { name: "IPO discovery", href: "/ipos" },
  { name: "Calendar", href: "/calendar" },
  { name: "Listing history", href: "/history" },
  { name: "Methodology", href: "/methodology" },
  { name: "Data sources", href: "/#sources" },
];

export default function Navbar() {
  const { user } = useAuth();
  return (
    <nav className="sticky top-0 z-50 border-b border-line bg-canvas/90 backdrop-blur" aria-label="Site">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="text-lg font-semibold tracking-tight text-ink">
          Kcp<span className="text-brand-ink">Insights</span>
        </Link>
        <div className="hidden items-center gap-6 md:flex">
          {navLinks.map((link) => (
            <Link key={link.name} href={link.href} className="text-sm text-ink-2 transition hover:text-ink">
              {link.name}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {!user && <Link href="/login" className="hidden rounded-md px-3 py-1.5 text-sm text-ink-2 hover:text-ink sm:inline">Sign in</Link>}
          <Link href="/dashboard" className="rounded-md bg-brand px-3.5 py-1.5 text-sm font-semibold text-white transition hover:bg-brand/85">
            Open the dashboard
          </Link>
        </div>
      </div>
    </nav>
  );
}
