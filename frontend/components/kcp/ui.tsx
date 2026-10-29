import Link from "next/link";
import { AlertTriangle, FlaskConical, Inbox, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtScore, riskTone, scoreTone, titleCase } from "@/lib/format";
import type { DataStatus, IpoStatus, RiskLevel } from "@/lib/types";

export function Panel({ title, subtitle, action, className, children }: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("rounded-2xl border border-white/10 bg-white/[0.03] p-5 sm:p-6", className)}>
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="text-base font-semibold text-white">{title}</h2>}
            {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-2 text-xs font-medium uppercase tracking-[0.2em] text-slate-500">{eyebrow}</div>}
        <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

const STATUS_STYLE: Record<IpoStatus, string> = {
  open: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  upcoming: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  closed: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  listed: "border-white/15 bg-white/5 text-slate-300",
  withdrawn: "border-rose-500/30 bg-rose-500/10 text-rose-300",
};

export function StatusBadge({ status }: { status: IpoStatus }) {
  return <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", STATUS_STYLE[status])}>{titleCase(status)}</span>;
}

const DS_STYLE: Record<DataStatus, string> = {
  verified: "border-emerald-500/30 text-emerald-300",
  imported: "border-sky-500/30 text-sky-300",
  estimated: "border-amber-500/30 text-amber-300",
  synthetic: "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300",
  unavailable: "border-white/10 text-slate-500",
};

export function DataStatusBadge({ status, compact = false }: { status: DataStatus | null | undefined; compact?: boolean }) {
  const s = status ?? "unavailable";
  return (
    <span
      title={s === "synthetic" ? "Fictional demonstration data — not a real financial fact" : `Data status: ${s}`}
      className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide", DS_STYLE[s])}
    >
      {s === "synthetic" && <FlaskConical className="size-3" aria-hidden />}
      {s === "verified" && <ShieldCheck className="size-3" aria-hidden />}
      {compact && s === "synthetic" ? "demo" : s}
    </span>
  );
}

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", riskTone(level))}>
      {level ? `${titleCase(level)} risk` : "Risk n/a"}
    </span>
  );
}

export function ScoreValue({ value, className }: { value: number | null | undefined; className?: string }) {
  return <span className={cn("tabular-nums font-semibold", scoreTone(value), className)}>{fmtScore(value)}</span>;
}

/** Horizontal 0–100 bar. `invert` for risk (higher = worse). */
export function ScoreBar({ label, value, invert = false, hint }: { label: string; value: number | null | undefined; invert?: boolean; hint?: string }) {
  const v = value ?? 0;
  const tone = value === null || value === undefined ? "bg-white/10" : invert ? (v >= 60 ? "bg-rose-400" : v >= 35 ? "bg-amber-400" : "bg-emerald-400") : v >= 70 ? "bg-emerald-400" : v >= 45 ? "bg-sky-400" : "bg-amber-400";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
        <span className="text-slate-300">{label}</span>
        <span className="tabular-nums text-slate-100">{value === null || value === undefined ? <span className="text-slate-500">unavailable</span> : fmtScore(value)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06]" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value ?? undefined}>
        <div className={cn("h-1.5 rounded-full transition-all", tone)} style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
      </div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Stat({ label, value, hint, className }: { label: string; value: React.ReactNode; hint?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-white/10 bg-black/30 p-4", className)}>
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-xl font-semibold tabular-nums text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-white/10 px-6 py-10 text-center">
      <Inbox className="size-6 text-slate-500" aria-hidden />
      <p className="mt-3 font-medium text-slate-200">{title}</p>
      {body && <div className="mt-1 max-w-md text-sm text-slate-400">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-rose-500/30 bg-rose-500/5 px-4 py-3 text-sm text-rose-200">
      <AlertTriangle className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-1 rounded-lg border border-rose-400/30 px-2.5 py-1 text-xs hover:bg-rose-500/10">
          <RefreshCw className="size-3" aria-hidden /> Retry
        </button>
      )}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warn" | "synthetic" }) {
  const style = tone === "warn" ? "border-amber-500/30 bg-amber-500/5 text-amber-200" : tone === "synthetic" ? "border-fuchsia-500/30 bg-fuchsia-500/5 text-fuchsia-200" : "border-sky-500/20 bg-sky-500/5 text-sky-200";
  return <div className={cn("rounded-xl border px-4 py-3 text-sm leading-6", style)}>{children}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-white/[0.06]", className)} />;
}

export function LoadingBlock({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin", className)} aria-hidden />;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="-mx-1 mb-6 flex gap-1 overflow-x-auto border-b border-white/10 px-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            "whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition",
            value === t.id ? "border-sky-400 text-white" : "border-transparent text-slate-400 hover:text-slate-200",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Disclaimer({ className }: { className?: string }) {
  return (
    <p className={cn("text-xs leading-5 text-slate-500", className)}>
      Educational research only — not investment advice. Scores are transparent rule-based summaries of stored inputs, not forecasts and not probabilities of listing gains.
    </p>
  );
}

export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="text-sky-300 underline-offset-4 hover:underline">
      {children}
    </Link>
  );
}

export const inputClass =
  "w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400/60 focus-visible:ring-2 focus-visible:ring-sky-400/30";

export const buttonClass = {
  primary:
    "inline-flex items-center justify-center gap-2 rounded-lg bg-white px-3.5 py-2 text-sm font-semibold text-black transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50",
  secondary:
    "inline-flex items-center justify-center gap-2 rounded-lg border border-white/15 px-3.5 py-2 text-sm font-medium text-slate-200 transition hover:border-white/30 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50",
  ghost: "inline-flex items-center justify-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-slate-300 transition hover:bg-white/5 hover:text-white disabled:opacity-50",
};
