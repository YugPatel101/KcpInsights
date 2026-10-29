"use client";

import { useSyncExternalStore } from "react";
import { useAuth } from "@/lib/auth";

const noopSubscribe = () => () => {};

function localGreeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good Morning" : hour < 18 ? "Good Afternoon" : "Good Evening";
}

export default function DashboardHeader({ asOf }: { asOf?: string }) {
  const { user } = useAuth();
  // Follows the reader's local clock; the server render uses a neutral greeting to avoid hydration mismatch.
  const greeting = useSyncExternalStore(noopSubscribe, localGreeting, () => "Welcome");

  return (
    <div className="mb-8">
      <h1 className="text-3xl font-bold sm:text-4xl">
        {greeting},
        <span className="ml-2 bg-gradient-to-r from-white via-slate-300 to-slate-500 bg-clip-text text-transparent">
          {user?.display_name ?? "Researcher"}
        </span>
      </h1>
      <p className="mt-3 text-slate-400">
        IPO pipeline and research scores from your KcpInsights database{asOf ? ` as of ${asOf}` : ""}.
      </p>
    </div>
  );
}
