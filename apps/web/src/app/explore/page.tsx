import { Suspense } from "react";
import { getCases, getIndexedCases, searchCases, searchIndexedCases } from "@/lib/api";
import { CaseCard } from "@/components/CaseCard";
import { IndexedCaseCard } from "@/components/IndexedCaseCard";
import type { CaseRecord, IndexedCaseDetail } from "@/lib/types";
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
  let canonicalCases: CaseRecord[] = [];
  let indexedCases: IndexedCaseDetail[] = [];

  const keyword = q?.trim();

  const [canonResult, indexedResult] = await Promise.allSettled([
    keyword ? searchCases(keyword) : getCases({ jurisdiction, sector, outcome }),
    keyword ? searchIndexedCases(keyword) : getIndexedCases({ jurisdiction, sector, outcome }),
  ]);

  if (canonResult.status === "fulfilled") canonicalCases = canonResult.value;
  if (indexedResult.status === "fulfilled") indexedCases = indexedResult.value;

  const bothFailed =
    canonResult.status === "rejected" && indexedResult.status === "rejected";

  if (bothFailed) {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700 text-sm">
        Failed to load cases. Is the API running?{" "}
        <code className="text-xs">docker compose up</code>
      </div>
    );
  }

  const total = canonicalCases.length + indexedCases.length;

  if (total === 0) {
    return (
      <p className="text-slate-500 text-sm">
        No cases found. Try a different search or filter.
      </p>
    );
  }

  const showDivider = canonicalCases.length > 0 && indexedCases.length > 0;

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500 font-medium">
        {canonicalCases.length > 0 && (
          <span>
            {canonicalCases.length} source-reviewed
            {indexedCases.length > 0 ? " · " : ""}
          </span>
        )}
        {indexedCases.length > 0 && (
          <span>{indexedCases.length} index {indexedCases.length === 1 ? "entry" : "entries"}</span>
        )}
      </p>

      {canonicalCases.map((c) => (
        <CaseCard key={c.case_id} case_={c} />
      ))}

      {showDivider && (
        <div className="pt-1 pb-1">
          <div className="flex items-center gap-3">
            <div className="flex-1 border-t border-amber-200" />
            <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 px-3 py-1 rounded-full whitespace-nowrap">
              Index entries — metadata only
            </span>
            <div className="flex-1 border-t border-amber-200" />
          </div>
        </div>
      )}

      {indexedCases.length > 0 && !showDivider && (
        <p className="text-xs text-amber-700">
          These results are metadata-only index entries. Source-backed analysis is pending.
        </p>
      )}

      {indexedCases.map((e) => (
        <IndexedCaseCard key={e.case_id} entry={e} />
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
