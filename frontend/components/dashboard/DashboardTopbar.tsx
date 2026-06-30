import { Bell, UserCircle2 } from "lucide-react";

export default function DashboardTopbar() {
  return (
    <header className="mb-12 flex items-center justify-between">

      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Kcp<span className="text-slate-400">Insights</span>
        </h1>

        <p className="mt-1 text-slate-500">
          AI-powered IPO Intelligence
        </p>
      </div>

      <div className="flex items-center gap-5">

        <button className="rounded-xl border border-white/10 p-3 transition hover:bg-white/5">
          <Bell size={20}/>
        </button>

        <button className="rounded-xl border border-white/10 p-3 transition hover:bg-white/5">
          <UserCircle2 size={20}/>
        </button>

      </div>

    </header>
  );
}