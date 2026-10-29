import { CountBarChart } from "@/components/charts/Charts";
import { Panel } from "@/components/kcp/ui";
import type { DashboardSummary } from "@/lib/types";

export default function MarketOverview({ data }: { data: DashboardSummary }) {
  return (
    <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
      <Panel title="IPOs by sector" subtitle="Count of stored issues per sector">
        <CountBarChart data={data.sectors.map((s) => ({ sector: s.sector, count: s.count }))} labelKey="sector" valueKey="count" label="IPOs" />
      </Panel>
      <Panel title="Issue size distribution" subtitle="Number of issues by total issue size (₹ crore)">
        <CountBarChart data={data.issue_sizes.map((s) => ({ bucket: s.bucket, count: s.count }))} labelKey="bucket" valueKey="count" label="IPOs" />
      </Panel>
    </div>
  );
}
