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

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return MISSING;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Tone class for a 0–100 score where higher is better. */
export function scoreTone(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-slate-500";
  if (v >= 70) return "text-emerald-400";
  if (v >= 45) return "text-slate-100";
  return "text-amber-400";
}

export function riskTone(level: string | null | undefined): string {
  if (level === "low") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (level === "moderate") return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  if (level === "high") return "border-rose-500/30 bg-rose-500/10 text-rose-300";
  return "border-white/10 bg-white/5 text-slate-400";
}

export function priceBand(lo: number | null, hi: number | null): string {
  if (lo === null && hi === null) return MISSING;
  if (lo === null || lo === hi) return fmtInr(hi, 0);
  return `₹${fmtNum(lo, 0)}–${fmtNum(hi, 0)}`;
}
