import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string;
  icon: LucideIcon;
  hint?: string;
}

export default function StatCard({ title, value, icon: Icon, hint }: StatCardProps) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-medium uppercase tracking-wider text-ink-3">{title}</p>
        <Icon className="size-4 text-ink-3" aria-hidden />
      </div>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums text-ink">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}
