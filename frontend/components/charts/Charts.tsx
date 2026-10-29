"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { useRouter } from "next/navigation";
import { fmtNum } from "@/lib/format";
import type { DashboardSummary, PeerRow, Statement } from "@/lib/types";

// Categorical palette validated for the dark surface (dataviz validator: all checks pass).
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"] as const;
const AXIS = { stroke: "#64748b", fontSize: 12 };
const GRID = "rgba(255,255,255,0.06)";
const tooltipStyle = {
  contentStyle: { background: "#0b0b0c", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 10, fontSize: 12, color: "#e2e8f0" },
  labelStyle: { color: "#f8fafc", fontWeight: 600 },
  itemStyle: { color: "#cbd5e1" },
  cursor: { fill: "rgba(255,255,255,0.04)" },
};

/** Revenue / EBITDA / PAT per period, INR crore (single axis). */
export function FinancialBarsChart({ statements }: { statements: Statement[] }) {
  const data = statements.map((s) => ({ period: s.period_label, Revenue: s.revenue, EBITDA: s.ebitda, PAT: s.pat }));
  return (
    <div className="h-72" role="img" aria-label="Revenue, EBITDA and PAT by period in INR crore">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 8 }} barGap={2}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="period" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={64} label={{ value: "₹ crore", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 12 }} />
          <Tooltip {...tooltipStyle} formatter={(v) => (typeof v === "number" ? `₹${fmtNum(v, 1)} cr` : "—")} />
          <Legend wrapperStyle={{ fontSize: 12, color: "#cbd5e1" }} />
          {(["Revenue", "EBITDA", "PAT"] as const).map((k, i) => (
            <Bar key={k} dataKey={k} fill={SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={28} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** EBITDA and PAT margins (%) per period — a separate chart instead of a second axis. */
export function MarginChart({ statements }: { statements: Statement[] }) {
  const data = statements.map((s) => ({ period: s.period_label, "EBITDA margin": s.derived.ebitda_margin_pct, "PAT margin": s.derived.pat_margin_pct }));
  return (
    <div className="h-56" role="img" aria-label="EBITDA and PAT margin by period in percent">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="period" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} unit="%" />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
          <Tooltip {...tooltipStyle} formatter={(v) => (typeof v === "number" ? `${v.toFixed(2)}%` : "—")} />
          <Legend wrapperStyle={{ fontSize: 12, color: "#cbd5e1" }} />
          <Line type="monotone" dataKey="EBITDA margin" stroke={SERIES[1]} strokeWidth={2} dot={{ r: 4 }} connectNulls={false} />
          <Line type="monotone" dataKey="PAT margin" stroke={SERIES[2]} strokeWidth={2} dot={{ r: 4 }} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

type ScatterPoint = DashboardSummary["scatter"][number];

export function QualityRiskScatter({ points }: { points: ScatterPoint[] }) {
  const router = useRouter();
  return (
    <div className="h-80" role="img" aria-label="Quality score versus risk score per IPO">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, left: 8, bottom: 24 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="risk" name="Risk" domain={[0, 100]} tick={AXIS} tickLine={false}
            label={{ value: "Risk score (higher = riskier)", position: "insideBottom", offset: -14, fill: "#64748b", fontSize: 12 }} />
          <YAxis type="number" dataKey="quality" name="Quality" domain={[0, 100]} tick={AXIS} tickLine={false} width={48}
            label={{ value: "Quality", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 12 }} />
          <ZAxis range={[90, 90]} />
          <ReferenceLine x={35} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
          <ReferenceLine x={60} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
          <Tooltip
            {...tooltipStyle}
            content={({ payload }) => {
              const p = payload?.[0]?.payload as ScatterPoint | undefined;
              if (!p) return null;
              return (
                <div className="rounded-lg border border-white/10 bg-[#0b0b0c] px-3 py-2 text-xs text-slate-300">
                  <div className="font-semibold text-white">{p.name}</div>
                  <div>{p.sector}</div>
                  <div className="mt-1 tabular-nums">Quality {p.quality.toFixed(1)} · Risk {p.risk.toFixed(1)}</div>
                  <div className="tabular-nums">Composite {p.composite === null ? "unavailable" : p.composite.toFixed(1)}</div>
                  {p.data_status === "synthetic" && <div className="mt-1 text-fuchsia-300">Synthetic demo data</div>}
                </div>
              );
            }}
          />
          <Scatter data={points} fill={SERIES[0]} stroke="#0c0c0d" strokeWidth={2} cursor="pointer"
            onClick={(d) => {
              const id = (d as unknown as { payload?: ScatterPoint }).payload?.id;
              if (id) router.push(`/ipos/${id}`);
            }} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CountBarChart({ data, labelKey, valueKey, label }: { data: Record<string, string | number>[]; labelKey: string; valueKey: string; label: string }) {
  return (
    <div style={{ height: Math.max(160, data.length * 34 + 40) }} role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey={labelKey} tick={AXIS} tickLine={false} axisLine={false} width={130} />
          <Tooltip {...tooltipStyle} />
          <Bar dataKey={valueKey} name={label} fill={SERIES[0]} radius={[0, 4, 4, 0]} maxBarSize={18} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Peer multiples as a strip with the IPO's multiple and the p25–p75 range. */
export function PeerDistributionChart({ peers, ipoMultiple, low, high, median, label }: {
  peers: PeerRow[];
  ipoMultiple: number;
  low: number;
  high: number;
  median: number;
  label: string;
}) {
  const data = [
    ...peers.filter((p) => p.value !== null).map((p) => ({ name: p.name, value: p.value as number, kind: p.used ? "Peer (used)" : "Peer (excluded)" })),
    { name: "This IPO", value: ipoMultiple, kind: "IPO" },
  ].sort((a, b) => a.value - b.value);
  return (
    <div className="h-64" role="img" aria-label={`${label} of peers compared with the IPO`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 16, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={{ ...AXIS, fontSize: 11 }} tickLine={false} interval={0} angle={-20} textAnchor="end" height={60} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} label={{ value: `${label} (x)`, angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 12 }} />
          <ReferenceLine y={low} stroke={SERIES[2]} strokeDasharray="4 4" label={{ value: "p25", fill: "#94a3b8", fontSize: 11, position: "right" }} />
          <ReferenceLine y={median} stroke="rgba(255,255,255,0.35)" label={{ value: "median", fill: "#94a3b8", fontSize: 11, position: "right" }} />
          <ReferenceLine y={high} stroke={SERIES[1]} strokeDasharray="4 4" label={{ value: "p75", fill: "#94a3b8", fontSize: 11, position: "right" }} />
          <Tooltip {...tooltipStyle} formatter={(v, _n, item) => [`${typeof v === "number" ? v.toFixed(2) : v}x`, (item?.payload as { kind?: string })?.kind ?? ""]} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={36}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.kind === "IPO" ? SERIES[3] : d.kind === "Peer (used)" ? SERIES[0] : "#334155"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
