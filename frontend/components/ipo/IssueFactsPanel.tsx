"use client";

import { Panel } from "@/components/kcp/ui";
import { MISSING, fmtCr, fmtInr, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import type { IpoDetail, IssueFact } from "@/lib/types";

const GROUPS: { title: string; keys: string[] }[] = [
  { title: "Offer", keys: ["issue_method", "price_band", "final_issue_price", "face_value", "lot_size", "lot_value", "issue_size", "issue_split", "total_shares", "shares_offered"] },
  { title: "Shares, valuation & ownership", keys: ["pre_issue_shares", "post_issue_shares", "market_cap", "pe_pre", "pe_post", "peer_premium", "peer_price",
    "peer_value", "promoter_holding_pre", "promoter_holding_post", "promoter_holding_latest", "promoters"] },
  { title: "Listing & intermediaries", keys: ["listing_exchanges", "isin", "registrar", "lead_managers", "website"] },
];

function shares(v: number | null | undefined): string {
  return v === null || v === undefined ? MISSING : `${fmtInt(v)} shares`;
}

function display(f: IssueFact): React.ReactNode {
  const v = f.value;
  if (v === null || v === undefined) return MISSING;
  switch (f.unit) {
    case "inr":
      return fmtInr(v as number, Number.isInteger(v) ? 0 : 2);
    case "inr_range": {
      const [lo, hi] = v as number[];
      return lo === hi ? fmtInr(hi, 0) : `₹${fmtNum(lo, 0)} – ₹${fmtNum(hi, 0)}`;
    }
    case "cr":
      return fmtCr(v as number, 2);
    case "shares":
      return shares(v as number);
    case "pct":
      return fmtPct(v as number, 2);
    case "pct_signed":
      return `${fmtPct(Math.abs(v as number), 1)} ${(v as number) >= 0 ? "above" : "below"}`;
    case "pct_range": {
      const [lo, hi] = v as number[];
      return `${fmtPct(lo, 2)} – ${fmtPct(hi, 2)}`;
    }
    case "x":
      return `${fmtNum(v as number, 2)}x`;
    case "list":
      return (v as string[]).join(", ");
    case "split": {
      const s = v as { fresh_cr: number | null; ofs_cr: number | null; fresh_shares?: number | null; ofs_shares?: number | null };
      // a draft document can print the share count while the rupee value is set with the price ("[●]")
      const part = (cr: number | null, sh?: number | null) =>
        cr === 0 || (cr === null && sh === 0) ? "nil" : cr === null ? (sh ? `${fmtInt(sh)} shares` : "—") : `${fmtCr(cr, 2)}${sh ? ` (${fmtInt(sh)} sh)` : ""}`;
      return `${part(s.fresh_cr, s.fresh_shares)} / ${part(s.ofs_cr, s.ofs_shares)}`;
    }
    case "url":
      return (
        <a className="text-brand-ink hover:underline" href={String(v)} target="_blank" rel="noopener noreferrer nofollow">
          {String(v).replace(/^https?:\/\//, "")}
        </a>
      );
    default:
      return String(v);
  }
}

function Provenance({ f }: { f: IssueFact }) {
  if (f.value === null || f.value === undefined) {
    return <span className={f.status === "pending" ? "text-ink-3" : "text-warn-ink"}>{f.reason ?? "not available"}</span>;
  }
  // the page link always names the offer document, so "NSE" is never read as "NSE, page 1"
  const fromDocument = /RHP|DRHP|document/i.test(f.source ?? "");
  const page = f.page && f.document_id
    ? <a className="text-brand-ink hover:underline" href={`/api/documents/${f.document_id}/file#page=${f.page}`} target="_blank" rel="noopener noreferrer">
        {fromDocument ? `p${f.page}` : `matches offer document p${f.page}`}</a>
    : null;
  return (
    <span className="text-ink-3">
      {f.status === "estimated" && <span className="mr-1 text-warn-ink">estimate ·</span>}
      {f.status === "unverified" && <span className="mr-1 text-warn-ink">unverified ·</span>}
      {f.status === "proposed" && <span className="mr-1 text-brand-ink">proposed ·</span>}
      {f.status === "derived" && <span className="mr-1">derived ·</span>}
      {f.source}
      {page && <>{fromDocument ? " " : " · "}{page}</>}
      {f.basis && <span className="block truncate" title={f.basis}>{f.basis}</span>}
    </span>
  );
}

export default function IssueFactsPanel({ d }: { d: IpoDetail }) {
  const facts = new Map((d.issue_facts ?? []).map((f) => [f.key, f]));
  const missing = (d.issue_facts ?? []).filter((f) => f.value === null && f.status === "unavailable").length;
  return (
    <Panel title="Issue details"
           subtitle={`Each value shows its source; gaps say why they are empty${missing ? ` (${missing} not published by the sources tried)` : ""}.`}>
      <div className="grid gap-x-8 gap-y-6 xl:grid-cols-2">
        {GROUPS.map((g) => (
          <div key={g.title} className={g.title.startsWith("Shares") ? "xl:row-span-2" : undefined}>
            <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wider text-ink-3">{g.title}</h3>
            <dl className="text-sm">
              {g.keys.map((k) => facts.get(k)).filter((f): f is IssueFact => Boolean(f)).map((f) => (
                <div key={f.key} className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-4 border-b border-line py-2 last:border-0">
                  <dt className="max-w-[13rem] text-ink-2">{f.label}</dt>
                  <dd className={`break-words text-right tabular-nums ${f.value === null ? "text-ink-3" : "text-ink"}`}>{display(f)}</dd>
                  <dd className="col-span-2 mt-0.5 text-[11px] leading-4"><Provenance f={f} /></dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
      {d.issue_size_text && <p className="mt-4 text-xs leading-5 text-ink-3">Issue as published by NSE: {d.issue_size_text}</p>}
      <p className="mt-2 flex flex-wrap gap-3 text-xs">
        {d.offer_document_url && <a className="text-brand-ink hover:underline" href={d.offer_document_url} target="_blank" rel="noopener noreferrer">Red Herring Prospectus (NSE, zip)</a>}
        {d.basis_of_price_url && <a className="text-brand-ink hover:underline" href={d.basis_of_price_url} target="_blank" rel="noopener noreferrer">Basis of issue price (NSE, zip)</a>}
      </p>
    </Panel>
  );
}
