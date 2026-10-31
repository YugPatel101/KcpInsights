import Link from "next/link";
import { AlertTriangle, FlaskConical, Inbox, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtScore, riskTone, scoreTone, titleCase } from "@/lib/format";
import type { DataStatus, FieldStatus, IpoStage, IpoStatus, Readiness, RiskLevel } from "@/lib/types";

export function Panel({ title, subtitle, action, className, children }: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("rounded-xl border border-line bg-surface p-4 sm:p-5", className)}>
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[13px] leading-5 text-ink-3">{subtitle}</p>}
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
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-xs font-medium text-ink-3">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">{title}</h1>
        {subtitle && <div className="mt-1.5 max-w-3xl text-sm leading-6 text-ink-2">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

const STATUS_STYLE: Record<IpoStatus, string> = {
  pipeline: "border-line-strong bg-surface-2 text-ink-3",
  open: "border-pos/40 bg-pos/10 text-pos-ink",
  upcoming: "border-brand/40 bg-brand/10 text-brand-ink",
  closed: "border-warn/40 bg-warn/10 text-warn-ink",
  listed: "border-line-strong bg-surface-3 text-ink-2",
  withdrawn: "border-neg/40 bg-neg/10 text-neg-ink",
};

export function StatusBadge({ status }: { status: IpoStatus }) {
  return <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", STATUS_STYLE[status])}>{titleCase(status)}</span>;
}

const DS_STYLE: Record<DataStatus, string> = {
  verified: "border-pos/40 text-pos-ink",
  imported: "border-brand/40 text-brand-ink",
  estimated: "border-warn/40 text-warn-ink",
  synthetic: "border-demo/50 bg-demo/10 text-demo-ink",
  secondary_source: "border-line-strong text-ink-2",
  extracted: "border-brand/30 text-ink-2",
  requires_review: "border-neg/50 bg-neg/10 text-neg-ink",
  unavailable: "border-line text-ink-3",
};

const DS_TITLE: Record<DataStatus, string> = {
  verified: "From an official source (exchange/regulator), parsed and validated",
  imported: "User-imported research with stated provenance",
  estimated: "Derived or estimated — e.g. expected dates from the SEBI T+3 timeline",
  synthetic: "Fictional demonstration data — not a real financial fact",
  secondary_source: "Non-authoritative public source, used for discovery or cross-checks",
  extracted: "Read from an official document by the parser; no accounting check could confirm it, so it is shown but not scored",
  requires_review: "Read from an official document but an accounting check failed; shown for inspection, never scored",
  unavailable: "Not available from any connected source",
};

export function DataStatusBadge({ status, compact = false }: { status: DataStatus | null | undefined; compact?: boolean }) {
  const s = status ?? "unavailable";
  return (
    <span
      title={DS_TITLE[s]}
      className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-[10.5px] font-medium uppercase tracking-wide", DS_STYLE[s])}
    >
      {s === "synthetic" && <FlaskConical className="size-3" aria-hidden />}
      {s === "verified" && <ShieldCheck className="size-3" aria-hidden />}
      {compact && s === "synthetic" ? "demo" : s === "secondary_source" ? "secondary" : s === "requires_review" ? "needs review" : s === "extracted" ? "unverified" : s}
    </span>
  );
}

const STAGE_LABEL: Record<IpoStage, string> = {
  pipeline: "DRHP / RHP filed", upcoming: "Upcoming", open: "Open", awaiting_allotment: "Awaiting allotment", awaiting_listing: "Awaiting listing",
  listing_unconfirmed: "Listing unconfirmed", closed: "Closed", listed: "Listed", withdrawn: "Withdrawn",
};
const STAGE_STYLE: Record<IpoStage, string> = {
  pipeline: STATUS_STYLE.pipeline, upcoming: STATUS_STYLE.upcoming, open: STATUS_STYLE.open, awaiting_allotment: STATUS_STYLE.closed,
  awaiting_listing: STATUS_STYLE.closed, listing_unconfirmed: "border-neg/40 bg-neg/5 text-neg-ink", closed: STATUS_STYLE.closed,
  listed: STATUS_STYLE.listed, withdrawn: STATUS_STYLE.withdrawn,
};

/** Lifecycle stage: like the status, but splits "closed" into awaiting allotment / awaiting listing. */
export function StageBadge({ stage }: { stage: IpoStage }) {
  return <span className={cn("inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium", STAGE_STYLE[stage])}>{STAGE_LABEL[stage]}</span>;
}

export function stageLabel(stage: IpoStage): string {
  return STAGE_LABEL[stage];
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
  const tone = value === null || value === undefined ? "bg-line" : invert ? (v >= 60 ? "bg-neg" : v >= 35 ? "bg-warn" : "bg-pos") : v >= 70 ? "bg-pos" : v >= 45 ? "bg-brand" : "bg-warn";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
        <span className="text-ink-2">{label}</span>
        <span className="tabular-nums text-ink">{value === null || value === undefined ? <span className="text-ink-3">unavailable</span> : fmtScore(value)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-3" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value ?? undefined}>
        <div className={cn("h-1.5 rounded-full transition-all", tone)} style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
      </div>
      {hint && <p className="mt-1 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export function Stat({ label, value, hint, className }: { label: string; value: React.ReactNode; hint?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-line bg-surface p-3.5", className)}>
      <div className="text-[11px] font-medium uppercase tracking-wider text-ink-3">{label}</div>
      <div className="mt-1.5 text-xl font-semibold tabular-nums text-ink">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line px-6 py-8 text-center">
      <Inbox className="size-5 text-ink-3" aria-hidden />
      <p className="mt-2.5 text-sm font-medium text-ink">{title}</p>
      {body && <div className="mt-1 max-w-md text-sm text-ink-3">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-neg/40 bg-neg/5 px-4 py-3 text-sm text-neg-ink">
      <AlertTriangle className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-1 rounded-md border border-neg/40 px-2.5 py-1 text-xs hover:bg-neg/10">
          <RefreshCw className="size-3" aria-hidden /> Retry
        </button>
      )}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warn" | "synthetic" }) {
  const style = tone === "warn" ? "border-warn/40 bg-warn/5 text-warn-ink" : tone === "synthetic" ? "border-demo/40 bg-demo/5 text-demo-ink" : "border-brand/30 bg-brand/5 text-ink-2";
  return <div className={cn("rounded-lg border px-4 py-3 text-sm leading-6", style)}>{children}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface-3", className)} />;
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
    <div role="tablist" className="-mx-1 mb-6 flex gap-0.5 overflow-x-auto border-b border-line px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-[13px] font-medium transition",
            value === t.id ? "border-brand text-ink" : "border-transparent text-ink-3 hover:text-ink-2",
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
    <p className={cn("text-xs leading-5 text-ink-3", className)}>
      KcpInsights provides educational financial research and quantitative analysis. Scores are methodology-dependent, data may be incomplete or delayed, and the platform does not provide personalized investment advice or guarantee IPO performance.
    </p>
  );
}

export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="text-brand-ink underline-offset-4 hover:underline">
      {children}
    </Link>
  );
}

export const inputClass =
  "w-full rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none transition placeholder:text-ink-3 focus:border-brand/70 focus-visible:ring-2 focus-visible:ring-brand/25";

export const buttonClass = {
  primary:
    "inline-flex items-center justify-center gap-2 rounded-md bg-brand px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-brand/85 disabled:cursor-not-allowed disabled:opacity-50",
  secondary:
    "inline-flex items-center justify-center gap-2 rounded-md border border-line-strong bg-surface px-3.5 py-2 text-sm font-medium text-ink transition hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50",
  ghost: "inline-flex items-center justify-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-ink-2 transition hover:bg-surface-3 hover:text-ink disabled:opacity-50",
};

/** Shared table look: compact rows, right-aligned figures (add `num` to numeric cells). */
export const tableClass = {
  wrap: "overflow-x-auto rounded-lg border border-line",
  table: "w-full min-w-[640px] border-collapse text-sm",
  thead: "bg-surface-2 text-left text-[11px] font-medium uppercase tracking-wider text-ink-3",
  th: "px-3 py-2.5 font-medium",
  tr: "border-t border-line hover:bg-surface-2/60",
  td: "px-3 py-2.5 text-ink-2",
  num: "whitespace-nowrap text-right tabular-nums",
};

const READINESS_STYLE: Record<Readiness, string> = {
  ready: "border-pos/40 text-pos-ink",
  partial: "border-warn/40 text-warn-ink",
  insufficient: "border-line-strong text-ink-3",
};
const READINESS_LABEL: Record<Readiness, string> = { ready: "Analysis ready", partial: "Partially ready", insufficient: "Insufficient data" };

export function ReadinessBadge({ level }: { level: Readiness | null | undefined }) {
  if (!level) return <span className="text-xs text-ink-3">not assessed</span>;
  return <span className={cn("inline-flex items-center whitespace-nowrap rounded border px-1.5 py-px text-[11px] font-medium", READINESS_STYLE[level])}>{READINESS_LABEL[level]}</span>;
}

/** Data completeness 0–100 as a thin meter with the number. Completeness is not a confidence level. */
export function CompletenessMeter({ value, className, label = "Data completeness" }: { value: number | null | undefined; className?: string; label?: string }) {
  const v = value ?? 0;
  const tone = value === null || value === undefined ? "bg-line" : v >= 75 ? "bg-pos" : v >= 50 ? "bg-brand" : v >= 25 ? "bg-warn" : "bg-neg";
  return (
    <span className={cn("inline-flex items-center gap-2", className)} title={`${label}: share of expected fields on record (not a confidence level)`}>
      <span className="h-1.5 w-14 rounded-full bg-surface-3" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value ?? undefined}>
        <span className={cn("block h-1.5 rounded-full", tone)} style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
      </span>
      <span className="w-9 text-right text-xs tabular-nums text-ink-2">{value === null || value === undefined ? "—" : `${Math.round(v)}%`}</span>
    </span>
  );
}

const FIELD_STYLE: Record<FieldStatus, string> = {
  available: "text-pos-ink", not_meaningful: "text-ink-2", estimated: "text-warn-ink", unverified: "text-brand-ink",
  requires_review: "text-neg-ink", unavailable: "text-ink-3", not_applicable: "text-ink-3", pending: "text-ink-3",
};
const FIELD_LABEL: Record<FieldStatus, string> = {
  available: "Available", not_meaningful: "Not meaningful", estimated: "Estimated", unverified: "Extracted, unverified",
  requires_review: "Requires review", unavailable: "Unavailable", not_applicable: "Not applicable", pending: "Not expected yet",
};

export function FieldStatusLabel({ status }: { status: FieldStatus }) {
  const dot = status === "available" ? "bg-pos" : status === "estimated" ? "bg-warn" : status === "unverified" ? "bg-brand" : status === "requires_review" ? "bg-neg" : "bg-line-strong";
  return <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-xs", FIELD_STYLE[status])}><span className={cn("size-1.5 rounded-full", dot)} aria-hidden />{FIELD_LABEL[status]}</span>;
}

/** Key/value rows for detail panels. */
export function KV({ rows }: { rows: [React.ReactNode, React.ReactNode][] }) {
  return (
    <dl className="divide-y divide-line text-sm">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex justify-between gap-4 py-2">
          <dt className="text-ink-3">{k}</dt>
          <dd className="text-right tabular-nums text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
