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
import type { DashboardSummary } from "@/lib/types";

// Categorical palette validated for the dark surface (dataviz validator: all checks pass). Fixed order, never cycled.
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"] as const;
// Semantic colours (design tokens): positive / negative outcomes only, never used as series colours.
const POS = "#34b27d";
const NEG = "#e0614a";
const INK_3 = "#727d8c";
const AXIS = { stroke: INK_3, fontSize: 12 };
const GRID = "#232933";
const tooltipStyle = {
  contentStyle: { background: "#161a21", border: "1px solid #313945", borderRadius: 8, fontSize: 12, color: "#e8ebf0" },
  labelStyle: { color: "#e8ebf0", fontWeight: 600 },
  itemStyle: { color: "#aab3c0" },
  cursor: { fill: "rgba(255,255,255,0.03)" },
};
const legendStyle = { fontSize: 12, color: "#aab3c0" };

/** Revenue, EBITDA and PAT per annual period, INR crore (one axis). */
export function FinancialBarsChart({ rows }: { rows: { period: string; revenue: number | null; ebitda: number | null; pat: number | null }[] }) {
  return (
    <div className="h-64 w-full" role="img" aria-label="Revenue, EBITDA and PAT by period in INR crore">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="period" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={64} tickFormatter={(v) => fmtNum(v, 0)} />
          <Tooltip {...tooltipStyle} formatter={(v) => `₹${fmtNum(Number(v), 1)} cr`} />
          <Legend wrapperStyle={legendStyle} />
          <Bar dataKey="revenue" name="Revenue" fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={28} />
          <Bar dataKey="ebitda" name="EBITDA" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={28} />
          <Bar dataKey="pat" name="PAT" fill={SERIES[2]} radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Up to four ratios sharing one unit, across annual periods. */
export function RatioTrendChart({ rows, series, unit }: { rows: Record<string, number | string | null>[]; series: { key: string; label: string }[]; unit: "%" | "x" }) {
  return (
    <div className="h-56 w-full" role="img" aria-label={`Ratio trend: ${series.map((s) => s.label).join(", ")}`}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="period" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => `${fmtNum(v, unit === "x" ? 1 : 0)}${unit}`} />
          <Tooltip {...tooltipStyle} formatter={(v) => (v === null || v === undefined ? "n/a" : `${fmtNum(Number(v), 2)}${unit}`)} />
          {series.length > 1 && <Legend wrapperStyle={legendStyle} />}
          {series.slice(0, 4).map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={SERIES[i]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "#11141a" }}
                  connectNulls={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

type ScatterPoint = DashboardSummary["scatter"][number];

/** Fundamental score (x) against risk score (y); each dot opens the IPO. */
export function ScoreRiskScatter({ points }: { points: ScatterPoint[] }) {
  const router = useRouter();
  const groups = [
    { label: "Mainboard", color: SERIES[0], data: points.filter((p) => p.issue_type !== "sme") },
    { label: "SME", color: SERIES[1], data: points.filter((p) => p.issue_type === "sme") },
  ].filter((g) => g.data.length);
  return (
    <div className="h-72 w-full" role="img" aria-label="Fundamental score versus risk score">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="score" name="Fundamental score" domain={[0, 100]} tick={AXIS}
                 label={{ value: "Fundamental score (higher = stronger)", position: "insideBottom", offset: -8, fill: INK_3, fontSize: 11 }} />
          <YAxis type="number" dataKey="risk" name="Risk score" domain={[0, 100]} tick={AXIS} width={40} />
          <ZAxis range={[90, 90]} />
          <ReferenceLine y={50} stroke="#313945" strokeDasharray="4 4" />
          <ReferenceLine x={50} stroke="#313945" strokeDasharray="4 4" />
          <Tooltip {...tooltipStyle} content={({ payload }) => {
                     const p = payload?.[0]?.payload as ScatterPoint | undefined;
                     return p ? <div className="rounded-md border border-line-strong bg-surface-2 px-3 py-2 text-xs text-ink"><div className="font-semibold text-ink">{p.name}</div>
                       <div>Score {fmtNum(p.score, 1)} · risk {fmtNum(p.risk, 1)}</div><div className="text-ink-3">{p.sector}</div></div> : null;
                   }} />
          {groups.length > 1 && <Legend wrapperStyle={legendStyle} verticalAlign="top" />}
          {groups.map((g) => (
            <Scatter key={g.label} name={g.label} data={g.data} fill={g.color} stroke="#11141a" strokeWidth={2} cursor="pointer"
                     onClick={(item) => {
                       const id = (item as unknown as { payload?: ScatterPoint }).payload?.id;
                       if (id) router.push(`/ipos/${id}`);
                     }} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Simple counts by category (single series). */
export function CountBarChart({ data, labelKey, valueKey, label, color = SERIES[0], height = 220 }: {
  data: Record<string, string | number>[]; labelKey: string; valueKey: string; label: string; color?: string; height?: number;
}) {
  return (
    <div className="w-full" style={{ height }} role="img" aria-label={label}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
          <YAxis type="category" dataKey={labelKey} tick={{ ...AXIS, fill: "#aab3c0" }} width={150} axisLine={false} tickLine={false} />
          <Tooltip {...tooltipStyle} formatter={(v) => [String(v), label]} />
          <Bar dataKey={valueKey} fill={color} radius={[0, 4, 4, 0]} maxBarSize={18} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** IPO openings per month, mainboard and SME stacked (one axis, counts). */
export function ActivityChart({ data }: { data: DashboardSummary["activity"] }) {
  const rows = data.map((d) => ({ ...d, label: new Date(`${d.month}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "2-digit" }) }));
  return (
    <div className="h-56 w-full" role="img" aria-label="IPO openings per month">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={32} allowDecimals={false} />
          <Tooltip {...tooltipStyle} />
          <Legend wrapperStyle={legendStyle} />
          <Bar dataKey="mainboard" name="Mainboard" stackId="a" fill={SERIES[0]} maxBarSize={30} />
          <Bar dataKey="sme" name="SME" stackId="a" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={30} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Listing-day return per recent listing (diverging around zero). */
export function ListingReturnsChart({ items }: { items: { name: string; ret: number; date: string }[] }) {
  return (
    <div className="h-64 w-full" role="img" aria-label="Listing-day returns of recent listings">
      <ResponsiveContainer>
        <BarChart data={items} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={false} axisLine={false} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => `${v}%`} />
          <ReferenceLine y={0} stroke="#313945" />
          <Tooltip {...tooltipStyle} formatter={(v) => [`${fmtNum(Number(v), 2)}%`, "Listing-day return"]} labelFormatter={(l, p) => `${l} · ${p?.[0]?.payload?.date ?? ""}`} />
          <Bar dataKey="ret" radius={[4, 4, 0, 0]} maxBarSize={22}>
            {items.map((d) => <Cell key={d.name} fill={d.ret >= 0 ? POS : NEG} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Peer multiples with the IPO's multiple and the peer median as reference lines. */
export function PeerMultipleChart({ peers, ipo, median, label }: { peers: { name: string; value: number }[]; ipo: number | null; median: number | null; label: string }) {
  return (
    <div className="h-56 w-full" role="img" aria-label={`${label} of listed peers compared with the IPO`}>
      <ResponsiveContainer>
        <BarChart data={peers} layout="vertical" margin={{ top: 0, right: 24, left: 8, bottom: 0 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}x`} />
          <YAxis type="category" dataKey="name" tick={{ ...AXIS, fill: "#aab3c0" }} width={170} axisLine={false} tickLine={false} />
          <Tooltip {...tooltipStyle} formatter={(v) => [`${fmtNum(Number(v), 2)}x`, label]} />
          <Bar dataKey="value" fill={SERIES[0]} radius={[0, 4, 4, 0]} maxBarSize={16} />
          {median !== null && <ReferenceLine x={median} stroke="#aab3c0" strokeDasharray="4 4" label={{ value: `median ${fmtNum(median, 1)}x`, fill: "#aab3c0", fontSize: 11, position: "top" }} />}
          {ipo !== null && <ReferenceLine x={ipo} stroke={SERIES[3]} strokeWidth={2} label={{ value: `IPO ${fmtNum(ipo, 1)}x`, fill: SERIES[3], fontSize: 11, position: "insideBottomRight" }} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Pre-listing fundamental score (x) against listing gain (y); one dot per listed IPO. */
export function OutcomeScatter({ points }: { points: { id: number; name: string; score: number; gain: number }[] }) {
  const router = useRouter();
  return (
    <div className="h-72 w-full" role="img" aria-label="Pre-listing fundamental score versus listing gain">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="score" name="Score" domain={[0, 100]} tick={AXIS}
                 label={{ value: "Pre-listing fundamental score", position: "insideBottom", offset: -8, fill: INK_3, fontSize: 11 }} />
          <YAxis type="number" dataKey="gain" name="Listing gain" tick={AXIS} width={48} tickFormatter={(v) => `${v}%`} />
          <ZAxis range={[80, 80]} />
          <ReferenceLine y={0} stroke="#313945" />
          <Tooltip {...tooltipStyle} content={({ payload }) => {
                     const p = payload?.[0]?.payload as { name: string; score: number; gain: number } | undefined;
                     return p ? <div className="rounded-md border border-line-strong bg-surface-2 px-3 py-2 text-xs text-ink"><div className="font-semibold">{p.name}</div>
                       <div className="text-ink-2">Score {fmtNum(p.score, 1)} · listing gain {fmtNum(p.gain, 1)}%</div></div> : null;
                   }} />
          <Scatter data={points} fill={SERIES[0]} stroke="#11141a" strokeWidth={2} cursor="pointer"
                   onClick={(item) => {
                     const id = (item as unknown as { payload?: { id: number } }).payload?.id;
                     if (id) router.push(`/ipos/${id}`);
                   }} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Signed values per category (e.g. median listing gain by sector): positive and negative bars around zero. */
export function DivergingBarChart({ data, label, unit = "%", height = 240 }: { data: { name: string; value: number; n?: number }[]; label: string; unit?: string; height?: number }) {
  return (
    <div className="w-full" style={{ height }} role="img" aria-label={label}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 24, left: 8, bottom: 0 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}${unit}`} />
          <YAxis type="category" dataKey="name" tick={{ ...AXIS, fill: "#aab3c0" }} width={170} axisLine={false} tickLine={false} />
          <ReferenceLine x={0} stroke="#313945" />
          <Tooltip {...tooltipStyle} formatter={(v, _n, p) => [`${fmtNum(Number(v), 1)}${unit}${(p?.payload as { n?: number })?.n ? ` (n=${(p?.payload as { n?: number }).n})` : ""}`, label]} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={16}>
            {data.map((d) => <Cell key={d.name} fill={d.value >= 0 ? POS : NEG} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
