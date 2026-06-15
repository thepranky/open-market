"use client";

import { useState } from "react";
import type { CaseSearchHit } from "@/lib/types";
import { SemanticCaseCard } from "@/components/SemanticCaseCard";
import { SearchForm } from "./SearchForm";

interface ExploreClientProps {
  initialQ?: string;
  initialJurisdiction?: string;
  initialSector?: string;
  initialOutcome?: string;
  initialTheory?: string;
  initialYearFrom?: string;
  initialYearTo?: string;
  serverResults: React.ReactNode;
}

export function ExploreClient({
  initialQ, initialJurisdiction, initialSector, initialOutcome,
  initialTheory, initialYearFrom, initialYearTo, serverResults,
}: ExploreClientProps) {
  const [semanticHits, setSemanticHits] = useState<CaseSearchHit[] | null>(null);

  return (
    <div className="grid lg:grid-cols-[268px_1fr] gap-8">
      <aside className="lg:sticky lg:top-[74px] self-start space-y-6">
        <SearchForm
          initialQ={initialQ}
          initialJurisdiction={initialJurisdiction}
          initialSector={initialSector}
          initialOutcome={initialOutcome}
          initialTheory={initialTheory}
          initialYearFrom={initialYearFrom}
          initialYearTo={initialYearTo}
          onSemanticResults={setSemanticHits}
          onKeywordMode={() => setSemanticHits(null)}
        />
      </aside>

      <section>
        {semanticHits !== null ? (
          <SemanticResultList hits={semanticHits} />
        ) : (
          serverResults
        )}
      </section>
    </div>
  );
}

function SemanticResultList({ hits }: { hits: CaseSearchHit[] }) {
  if (hits.length === 0) {
    return (
      <div className="text-center py-20 text-muted">
        <p className="text-[15px]">No semantic matches found. Try rephrasing your query.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2.5 pb-3 border-b border-line mb-5">
        <span className="text-[15px] font-semibold text-ink">{hits.length} semantic {hits.length === 1 ? "match" : "matches"}</span>
        <span className="text-[12px] font-medium text-brand-ink bg-brand-soft rounded-[5px] px-2 py-[3px]">semantic</span>
      </div>
      {hits.map((hit) => (
        <SemanticCaseCard key={hit.case_id} hit={hit} />
      ))}
    </div>
  );
}
