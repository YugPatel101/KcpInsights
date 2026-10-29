import Link from "next/link";

export default function SectionTitle({ title, subtitle, href, linkLabel = "View all" }: { title: string; subtitle?: string; href?: string; linkLabel?: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-xl font-bold text-white">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {href && (
        <Link href={href} className="rounded-xl border border-white/10 px-3 py-1.5 text-sm text-slate-300 transition hover:border-slate-500 hover:bg-white/5">
          {linkLabel}
        </Link>
      )}
    </div>
  );
}
