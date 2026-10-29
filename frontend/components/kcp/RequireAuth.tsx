"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { EmptyState, LoadingBlock } from "@/components/kcp/ui";
import { useAuth } from "@/lib/auth";

/** UI gate for per-user pages. Authorization is enforced server-side; this only explains it. */
export default function RequireAuth({ children, what }: { children: React.ReactNode; what: string }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  if (loading) return <LoadingBlock />;
  if (!user) {
    return (
      <EmptyState
        title={`Sign in to see your ${what}`}
        body="This content is private to your account."
        action={<Link href={`/login?next=${encodeURIComponent(pathname)}`} className="text-sky-300 hover:underline">Sign in</Link>}
      />
    );
  }
  return <>{children}</>;
}
