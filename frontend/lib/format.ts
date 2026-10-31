// Formatting helpers. Missing values always render as an explicit "—" (never 0).

export const MISSING = "—";

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return MISSING;
  return v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return MISSING;
  return Math.round(v).toLocaleString("en-IN");
}

/** INR crore, e.g. ₹1,234.5 cr */
export function fmtCr(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return MISSING;
  return `₹${v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })} cr`;
}

export function fmtInr(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return MISSING;
  return `₹${v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function fmtPct(v: number | null | undefined, digits = 1, signed = false): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return MISSING;
  const s = v.toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

export function fmtScore(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return MISSING;
  return v.toFixed(1);
}

export function fmtMetric(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined) return MISSING;
  if (unit === "%" || unit === "pp") return `${v.toFixed(2)}${unit === "%" ? "%" : " pp"}`;
  if (unit === "x") return `${v.toFixed(2)}x`;
  if (unit === "share") return `${(v * 100).toFixed(0)}%`;
  return fmtNum(v);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return MISSING;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/** API timestamps are naive UTC ("2026-10-31T15:40:17"); a date-time without a zone is read as UTC, never as local time. */
export function parseApiTime(iso: string): Date {
  const hasTime = /T\d\d:\d\d/.test(iso);
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  return new Date(hasTime && !hasZone ? `${iso}Z` : iso);
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const d = parseApiTime(iso);
  if (Number.isNaN(d.getTime())) return MISSING;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Tone class for a 0–100 score where higher is better. */
export function scoreTone(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-ink-3";
  if (v >= 70) return "text-pos-ink";
  if (v >= 45) return "text-ink";
  return "text-warn-ink";
}

export function riskTone(level: string | null | undefined): string {
  if (level === "low") return "border-pos/40 bg-pos/10 text-pos-ink";
  if (level === "moderate") return "border-warn/40 bg-warn/10 text-warn-ink";
  if (level === "elevated") return "border-neg/30 bg-neg/5 text-neg-ink";
  if (level === "high") return "border-neg/50 bg-neg/15 text-neg-ink";
  return "border-line bg-surface-2 text-ink-3";
}

/** Text colour for a signed return: semantic positive/negative, neutral for missing. */
export function returnTone(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-ink-3";
  return v < 0 ? "text-neg-ink" : "text-pos-ink";
}

export const PROFILE_LABEL: Record<string, string> = {
  general: "General", manufacturing: "Manufacturing", technology: "Technology & internet", infrastructure: "Infrastructure & utilities",
  real_estate: "Real estate", lender: "Lender (bank/NBFC)", insurer: "Insurer",
};

export function priceBand(lo: number | null, hi: number | null): string {
  if (lo === null && hi === null) return MISSING;
  if (lo === null || lo === hi) return fmtInr(hi, 0);
  return `₹${fmtNum(lo, 0)}–${fmtNum(hi, 0)}`;
}
