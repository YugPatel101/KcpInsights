"use client";

import Link from "next/link";
import KcpButton from "@/components/common/KcpButton";
import { useAuth } from "@/lib/auth";

const navLinks = [
  { name: "IPOs", href: "/ipos" },
  { name: "Dashboard", href: "/dashboard" },
  { name: "AI Research", href: "/workspace" },
  { name: "Methodology", href: "/#methodology" },
];

export default function Navbar() {
  const { user } = useAuth();
  return (
    <nav className="sticky top-0 z-50 border-b border-white/10 bg-black/80 backdrop-blur-xl">
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between gap-4 px-6 lg:px-10">
        <Link href="/" className="cursor-pointer">
          <span className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            Kcp<span className="text-slate-400">Insights</span>
          </span>
        </Link>

        <div className="hidden items-center gap-12 lg:flex">
          {navLinks.map((link) => (
            <Link
              key={link.name}
              href={link.href}
              className="group relative text-[16px] font-semibold tracking-wide text-slate-300 transition-all duration-300 hover:text-white"
            >
              {link.name}
              <span className="absolute -bottom-2 left-0 h-[2px] w-0 bg-white transition-all duration-300 group-hover:w-full"></span>
            </Link>
          ))}
        </div>

        <KcpButton asChild className="min-w-0 px-5">
          <Link href={user ? "/dashboard" : "/login"}>{user ? "Open app" : "Sign In"}</Link>
        </KcpButton>
      </div>
    </nav>
  );
}
