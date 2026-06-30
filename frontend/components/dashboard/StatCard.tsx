import { LucideIcon } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string;
  icon: LucideIcon;
}

export default function StatCard({
  title,
  value,
  icon: Icon,
}: StatCardProps) {
  return (
    <div className="group rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl transition-all duration-300 hover:-translate-y-1 hover:border-slate-500">
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-slate-800">
        <Icon className="h-6 w-6 text-slate-300" />
      </div>

      <h2 className="text-3xl font-bold text-white">
        {value}
      </h2>

      <p className="mt-2 text-slate-400">
        {title}
      </p>
    </div>
  );
}