import { LucideIcon } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string;
  icon: LucideIcon;
  hint?: string;
}

export default function StatCard({
  title,
  value,
  icon: Icon,
  hint,
}: StatCardProps) {
  return (
    <div className="group rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl transition-all duration-300 hover:border-slate-500">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-slate-800">
        <Icon className="h-5 w-5 text-slate-300" aria-hidden />
      </div>

      <p className="text-2xl font-bold tabular-nums text-white">
        {value}
      </p>

      <p className="mt-1 text-sm text-slate-400">
        {title}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
