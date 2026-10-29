"use client";

import { inputClass } from "@/components/kcp/ui";
import { useApi } from "@/lib/useApi";
import type { IpoSummary, Paged } from "@/lib/types";

/** Select an IPO from the stored list. */
export default function IpoPicker({ value, onChange, label = "IPO", exclude = [], allowEmpty = false }: {
  value: number | null;
  onChange: (id: number | null) => void;
  label?: string;
  exclude?: number[];
  allowEmpty?: boolean;
}) {
  const { data } = useApi<Paged<IpoSummary>>("/api/ipos?page_size=100&sort=name");
  return (
    <label className="block text-xs text-slate-400">
      <span className="mb-1 block">{label}</span>
      <select className={inputClass} value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{allowEmpty ? "None" : "Select an IPO…"}</option>
        {data?.items
          .filter((i) => !exclude.includes(i.id) || i.id === value)
          .map((i) => (
            <option key={i.id} value={i.id}>
              {i.company_name}{i.data_status === "synthetic" ? " (demo)" : ""}
            </option>
          ))}
      </select>
    </label>
  );
}
