import Link from "next/link";

export default function SectionTitle({ title, subtitle, href, linkLabel = "View all" }: { title: string; subtitle?: string; href?: string; linkLabel?: string }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-ink-3">{subtitle}</p>}
      </div>
      {href && (
        <Link href={href} className="text-xs font-medium text-brand-ink hover:underline">
          {linkLabel} →
        </Link>
      )}
    </div>
  );
}
