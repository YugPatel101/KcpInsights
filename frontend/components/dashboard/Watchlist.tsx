import Link from "next/link";
import IPOCard from "@/components/home/IPOCard";
import { EmptyState } from "@/components/kcp/ui";
import type { IpoSummary } from "@/lib/types";

export default function Watchlist({ items, signedIn }: { items: IpoSummary[]; signedIn: boolean }) {
  if (!signedIn) {
    return <EmptyState title="Sign in to keep a watchlist" body="Watchlists, reports and research conversations are saved per account." action={<Link className="text-sky-300 hover:underline" href="/login?next=/dashboard">Sign in</Link>} />;
  }
  if (!items.length) {
    return <EmptyState title="Your watchlist is empty" body="Use “Watch” on any IPO research page to follow it here." action={<Link className="text-sky-300 hover:underline" href="/ipos">Browse IPOs</Link>} />;
  }
  return (
    <div className="space-y-3">
      {items.map((i) => (
        <IPOCard key={i.id} ipo={i} />
      ))}
    </div>
  );
}
