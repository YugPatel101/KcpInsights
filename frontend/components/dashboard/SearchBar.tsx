import { Search } from "lucide-react";

export default function SearchBar() {
  return (
    <div className="mb-12">

      <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-5 py-4">

        <div className="flex items-center gap-3">

          <Search className="text-slate-400"/>

          <input
            placeholder="Search IPOs, companies, sectors..."
            className="w-96 bg-transparent outline-none placeholder:text-slate-500"
          />

        </div>

        <div className="rounded-lg border border-white/10 px-3 py-1 text-sm text-slate-500">

          ⌘ K

        </div>

      </div>

    </div>
  );
}