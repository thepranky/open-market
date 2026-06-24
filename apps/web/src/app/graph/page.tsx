import dynamic from "next/dynamic";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Graph — CompMap",
  description: "Navigate cases through sectors, markets, and related precedent.",
};

const NavigationGraph = dynamic(
  () => import("@/features/cases/graph/NavigationGraph").then((m) => m.NavigationGraph),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-64 text-slate-400 text-sm animate-pulse">
        Loading graph…
      </div>
    ),
  }
);

export default function GraphPage() {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900 mb-1">Market graph</h1>
        <p className="text-sm text-slate-500">
          Browse by sector, drill into markets, and discover related cases and precedent.
        </p>
      </div>
      <NavigationGraph />
    </div>
  );
}
