import { Suspense } from "react";
import { getCases, getIndexedCases, searchCases, searchIndexedCases } from "@/features/cases/api";
import type { CaseRecord, IndexedCaseDetail } from "@/lib/types";
import { ExploreClient } from "@/features/cases/explore/ExploreClient";
import { ExploreResults } from "@/features/cases/explore/ExploreResults";

interface ExplorePageProps {
  searchParams: Promise<{
    q?: string;
    jurisdiction?: string;
    sector?: string;
    outcome?: string;
    year_from?: string;
    year_to?: string;
  }>;
}

async function CaseResults({
  q,
  jurisdiction,
  sector,
  outcome,
  year_from,
  year_to,
}: {
  q?: string;
  jurisdiction?: string;
  sector?: string;
  outcome?: string;
  year_from?: string;
  year_to?: string;
}) {
  let canonicalCases: CaseRecord[] = [];
  let indexedCases: IndexedCaseDetail[] = [];

  const keyword = q?.trim();
  const yearFrom = year_from ? parseInt(year_from) : undefined;
  const yearTo = year_to ? parseInt(year_to) : undefined;

  const [canonResult, indexedResult] = await Promise.allSettled([
    keyword
      ? searchCases(keyword).then((cs) => {
          let r = cs;
          if (jurisdiction) r = r.filter((c) => c.jurisdiction.toUpperCase() === jurisdiction.toUpperCase());
          if (yearFrom) r = r.filter((c) => new Date(c.decision_date).getFullYear() >= yearFrom);
          if (yearTo) r = r.filter((c) => new Date(c.decision_date).getFullYear() <= yearTo);
          return r;
        })
      : getCases({ jurisdiction, sector, outcome, year_from: yearFrom, year_to: yearTo }),
    keyword
      ? searchIndexedCases(keyword)
      : getIndexedCases({ jurisdiction, sector, outcome, year_from: yearFrom, year_to: yearTo }),
  ]);

  if (canonResult.status === "fulfilled") canonicalCases = canonResult.value;
  if (indexedResult.status === "fulfilled") indexedCases = indexedResult.value;

  const bothFailed = canonResult.status === "rejected" && indexedResult.status === "rejected";
  if (bothFailed) {
    return (
      <div className="rounded-xl border border-neg bg-neg-soft p-4 text-[14px] text-neg-ink">
        Failed to load cases. Is the API running?{" "}
        <code className="font-mono text-[12px]">docker compose up</code>
      </div>
    );
  }

  return <ExploreResults canonicalCases={canonicalCases} indexedCases={indexedCases} />;
}

export default async function ExplorePage({ searchParams }: ExplorePageProps) {
  const params = await searchParams;
  const { q, jurisdiction, sector, outcome, year_from, year_to } = params;

  return (
    <div className="mx-auto max-w-content px-6 py-8 lg:px-8">
      <h1 className="mb-5 text-[20px] font-semibold text-ink">Explore</h1>

      <ExploreClient
        initialQ={q}
        initialJurisdiction={jurisdiction}
        initialSector={sector}
        initialOutcome={outcome}
        initialYearFrom={year_from}
        initialYearTo={year_to}
        serverResults={
          <Suspense fallback={<div className="animate-pulse text-[14px] text-faint">Loading cases…</div>}>
            <CaseResults
              q={q}
              jurisdiction={jurisdiction}
              sector={sector}
              outcome={outcome}
              year_from={year_from}
              year_to={year_to}
            />
          </Suspense>
        }
      />
    </div>
  );
}
