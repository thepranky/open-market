import { Suspense } from "react";
import { getCases, getIndexedCases, searchCases, searchIndexedCases } from "@/lib/api";
import { CaseCard } from "@/components/CaseCard";
import { IndexedCaseCard } from "@/components/IndexedCaseCard";
import type { CaseRecord, IndexedCaseDetail } from "@/lib/types";
import { ExploreClient } from "./ExploreClient";

interface ExplorePageProps {
  searchParams: Promise<{
    q?: string;
    jurisdiction?: string;
    sector?: string;
    outcome?: string;
    theory?: string;
    year_from?: string;
    year_to?: string;
  }>;
}

async function CaseResults({
  q, jurisdiction, sector, outcome, theory, year_from, year_to,
}: {
  q?: string; jurisdiction?: string; sector?: string;
  outcome?: string; theory?: string; year_from?: string; year_to?: string;
}) {
  let canonicalCases: CaseRecord[] = [];
  let indexedCases: IndexedCaseDetail[] = [];

  const keyword  = q?.trim();
  const yearFrom = year_from ? parseInt(year_from) : undefined;
  const yearTo   = year_to   ? parseInt(year_to)   : undefined;

  const [canonResult, indexedResult] = await Promise.allSettled([
    keyword
      ? searchCases(keyword).then((cs) => {
          let r = cs;
          if (jurisdiction) r = r.filter((c) => c.jurisdiction.toUpperCase() === jurisdiction.toUpperCase());
          if (yearFrom) r = r.filter((c) => new Date(c.decision_date).getFullYear() >= yearFrom);
          if (yearTo)   r = r.filter((c) => new Date(c.decision_date).getFullYear() <= yearTo);
          if (theory)   r = r.filter((c) => c.theories_of_harm.some((t) =>
            t.name.toLowerCase().includes(theory.toLowerCase()) ||
            (t.description || "").toLowerCase().includes(theory.toLowerCase())
          ));
          return r;
        })
      : getCases({ jurisdiction, sector, outcome, theory, year_from: yearFrom, year_to: yearTo }),
    keyword
      ? searchIndexedCases(keyword)
      : getIndexedCases({ jurisdiction, sector, outcome, year_from: yearFrom, year_to: yearTo }),
  ]);

  if (canonResult.status === "fulfilled") canonicalCases = canonResult.value;
  if (indexedResult.status === "fulfilled") indexedCases = indexedResult.value;

  const bothFailed = canonResult.status === "rejected" && indexedResult.status === "rejected";
  if (bothFailed) {
    return (
      <div className="rounded-xl bg-neg-soft border border-neg p-4 text-neg-ink text-[14px]">
        Failed to load cases. Is the API running? <code className="text-[12px] font-mono">docker compose up</code>
      </div>
    );
  }

  const total = canonicalCases.length + indexedCases.length;
  if (total === 0) {
    return (
      <div className="text-center py-20 text-muted">
        <p className="text-[15px]">No cases match those filters.</p>
      </div>
    );
  }

  const showDivider = canonicalCases.length > 0 && indexedCases.length > 0;

  return (
    <div>
      <div className="flex items-baseline gap-2.5 mb-5 pb-3 border-b border-line">
        {canonicalCases.length > 0 && (
          <span className="text-[15px] font-semibold text-ink">{canonicalCases.length} source-reviewed</span>
        )}
        {showDivider && <span className="text-faint">·</span>}
        {indexedCases.length > 0 && (
          <span className="text-[15px] text-muted">{indexedCases.length} indexed</span>
        )}
      </div>

      <div className="space-y-3">
        {canonicalCases.map((c) => <CaseCard key={c.case_id} case_={c} />)}
      </div>

      {showDivider && (
        <div className="mt-9">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-[12px] font-semibold uppercase tracking-[0.08em] text-faint">Indexed · metadata only</span>
            <span className="flex-1 h-px bg-line" />
            <span className="text-[12px] text-faint">{indexedCases.length}</span>
          </div>
          <div className="space-y-2">
            {indexedCases.map((e) => <IndexedCaseCard key={e.case_id} entry={e} />)}
          </div>
        </div>
      )}

      {!showDivider && indexedCases.length > 0 && (
        <div className="space-y-2">
          {indexedCases.map((e) => <IndexedCaseCard key={e.case_id} entry={e} />)}
        </div>
      )}
    </div>
  );
}

export default async function ExplorePage({ searchParams }: ExplorePageProps) {
  const params = await searchParams;
  const { q, jurisdiction, sector, outcome, theory, year_from, year_to } = params;

  return (
    <div className="mx-auto max-w-content px-6 lg:px-8 py-10">
      <div className="mb-7">
        <h1 className="font-sans font-semibold tracking-tight text-ink" style={{ fontSize: "clamp(26px, 3vw, 34px)" }}>
          Explore cases
        </h1>
        <p className="mt-2 text-[15px] text-muted max-w-2xl">
          Search merger precedent by keyword or semantics, then filter by jurisdiction, sector, and outcome.
          Source-reviewed records carry full market definitions; indexed records carry metadata only.
        </p>
      </div>

      <ExploreClient
        initialQ={q}
        initialJurisdiction={jurisdiction}
        initialSector={sector}
        initialOutcome={outcome}
        initialTheory={theory}
        initialYearFrom={year_from}
        initialYearTo={year_to}
        serverResults={
          <Suspense fallback={<div className="text-[14px] text-faint animate-pulse">Loading cases…</div>}>
            <CaseResults
              q={q} jurisdiction={jurisdiction} sector={sector}
              outcome={outcome} theory={theory} year_from={year_from} year_to={year_to}
            />
          </Suspense>
        }
      />
    </div>
  );
}
