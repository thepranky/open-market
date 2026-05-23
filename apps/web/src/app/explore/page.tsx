import { Suspense } from "react";
import { getCases, searchCases } from "@/lib/api";
import { CaseCard } from "@/components/CaseCard";
import type { CaseRecord } from "@/lib/types";
import { SearchForm } from "./SearchForm";

interface ExplorePageProps {
  searchParams: Promise<{
    q?: string;
    jurisdiction?: string;
    sector?: string;
    outcome?: string;
  }>;
}

async function CaseResults({
  q,
  jurisdiction,
  sector,
  outcome,
}: {
  q?: string;
  jurisdiction?: string;
  sector?: string;
  outcome?: string;
}) {
  let cases: CaseRecord[] = [];
  let error: string | null = null;

  try {
    if (q && q.trim()) {
      cases = await searchCases(q.trim());
    } else {
      cases = await getCases({ jurisdiction, sector, outcome });
    }
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load cases";
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700 text-sm">
        {error}. Is the API running?{" "}
        <code className="text-xs">docker compose up</code>
      </div>
    );
  }

  if (cases.length === 0) {
    return (
      <p className="text-slate-500 text-sm">
        No cases found. Try a different search or filter.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500 font-medium">
        {cases.length} case{cases.length !== 1 ? "s" : ""}
      </p>
      {cases.map((c) => (
        <CaseCard key={c.case_id} case_={c} />
      ))}
    </div>
  );
}

export default async function ExplorePage({ searchParams }: ExplorePageProps) {
  const params = await searchParams;
  const { q, jurisdiction, sector, outcome } = params;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900 mb-1">Explore cases</h1>
        <p className="text-sm text-slate-500">
          Search merger precedent by keyword, or filter by jurisdiction, sector, and outcome.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
        {/* Filter panel */}
        <aside className="space-y-6">
          <SearchForm
            initialQ={q}
            initialJurisdiction={jurisdiction}
            initialSector={sector}
            initialOutcome={outcome}
          />
        </aside>

        {/* Results */}
        <section>
          <Suspense
            fallback={
              <div className="text-sm text-slate-400 animate-pulse">
                Loading cases…
              </div>
            }
          >
            <CaseResults
              q={q}
              jurisdiction={jurisdiction}
              sector={sector}
              outcome={outcome}
            />
          </Suspense>
        </section>
      </div>
    </div>
  );
}
