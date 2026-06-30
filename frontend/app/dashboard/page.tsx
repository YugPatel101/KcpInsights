import Sidebar from "@/components/dashboard/Sidebar";
import DashboardTopbar from "@/components/dashboard/DashboardTopbar";
import DashboardHeader from "@/components/dashboard/DashboardHeader";
import SearchBar from "@/components/dashboard/SearchBar";
import StatCard from "@/components/dashboard/StatCard";
import UpcomingTable from "@/components/dashboard/UpcomingTable";

import {
  TrendingUp,
  Activity,
  Brain,
  Landmark,
} from "lucide-react";

export default function DashboardPage() {
  return (
    <div className="flex min-h-screen bg-black text-white">

      <Sidebar />

      <main className="flex-1 overflow-y-auto">

        <div className="mx-auto max-w-7xl px-10 py-10">

          <DashboardTopbar />

          <DashboardHeader />

          <SearchBar />

          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">

            <StatCard
              title="Upcoming IPOs"
              value="127"
              icon={TrendingUp}
            />

            <StatCard
              title="Live IPOs"
              value="18"
              icon={Activity}
            />

            <StatCard
              title="AI Accuracy"
              value="94%"
              icon={Brain}
            />

            <StatCard
              title="Funds Raised"
              value="₹2.3T"
              icon={Landmark}
            />

          </div>

          <UpcomingTable />

        </div>

      </main>

    </div>
  );
}