"use client";

import { useState } from "react";
import type { CaseSearchHit } from "@/lib/types";
import { SemanticCaseCard } from "@/components/SemanticCaseCard";
import { ViewToggle } from "@/components/ViewToggle";
import { SearchForm } from "./SearchForm";

interface ExploreClientProps {
  initialQ?: string;
  initialJurisdiction?: string;
  initialSector?: string;
  initialOutcome?: string;
  initialYearFrom?: string;
  initialYearTo?: string;
  serverResults: React.ReactNode;
}

export function ExploreClient({
  initialQ,
  initialJurisdiction,
  initialSector,
  initialOutcome,
  initialYearFrom,
  initialYearTo,
  serverResults,
}: ExploreClientProps) {
  const [semanticHits, setSemanticHits] = useState<CaseSearchHit[] | null>(null);

  return (
    <SearchForm
      initialQ={initialQ}
      initialJurisdiction={initialJurisdiction}
      initialSector={initialSector}
      initialOutcome={initialOutcome}
      initialYearFrom={initialYearFrom}
      initialYearTo={initialYearTo}
      onSemanticResults={setSemanticHits}
      onKeywordMode={() => setSemanticHits(null)}
    >
      {semanticHits !== null ? (
        <SemanticResultList hits={semanticHits} />
      ) : (
        serverResults
      )}
    </SearchForm>
  );
}

function SemanticResultList({ hits }: { hits: CaseSearchHit[] }) {
  const [viewMode, setViewMode] = useState<"compact" | "detailed">("detailed");
  const compact = viewMode === "compact";

  if (hits.length === 0) {
    return (
      <div className="py-16 text-center text-muted">
        <p className="text-[14px]">No semantic matches found. Try rephrasing your query.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="mb-4 flex items-center justify-between gap-3 border-b border-line pb-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="text-[14px] font-semibold text-ink">
            {hits.length} semantic {hits.length === 1 ? "match" : "matches"}
          </span>
          <span className="rounded-[5px] bg-brand-soft px-2 py-0.5 text-[11px] font-medium text-brand-ink">
            semantic
          </span>
        </div>
        <ViewToggle
          aria-label="Results card view"
          options={[
            { value: "compact", label: "Compact" },
            { value: "detailed", label: "Detailed" },
          ]}
          value={viewMode}
          onChange={setViewMode}
        />
      </div>
      <div className={compact ? "space-y-2" : "space-y-3"}>
        {hits.map((hit) => (
          <SemanticCaseCard key={hit.case_id} hit={hit} compact={compact} />
        ))}
      </div>
    </div>
  );
}
