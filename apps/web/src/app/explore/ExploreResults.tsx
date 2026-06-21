"use client";

import { useState } from "react";
import type { CaseRecord, IndexedCaseDetail } from "@/lib/types";
import { CaseCard } from "@/components/CaseCard";
import { IndexedCaseCard } from "@/components/IndexedCaseCard";
import { ViewToggle } from "@/components/ViewToggle";

type CardViewMode = "compact" | "detailed";

interface ExploreResultsProps {
  canonicalCases: CaseRecord[];
  indexedCases: IndexedCaseDetail[];
}

export function ExploreResults({ canonicalCases, indexedCases }: ExploreResultsProps) {
  const [viewMode, setViewMode] = useState<CardViewMode>("detailed");

  const total = canonicalCases.length + indexedCases.length;
  if (total === 0) {
    return (
      <div className="py-16 text-center text-muted">
        <p className="text-[14px]">No cases match those filters.</p>
      </div>
    );
  }

  const showDivider = canonicalCases.length > 0 && indexedCases.length > 0;
  const compact = viewMode === "compact";

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3 border-b border-line pb-3">
        <div className="flex min-w-0 items-baseline gap-2">
          {canonicalCases.length > 0 && (
            <span className="text-[14px] font-semibold text-ink">
              {canonicalCases.length} source-reviewed
            </span>
          )}
          {showDivider && <span className="text-faint">·</span>}
          {indexedCases.length > 0 && (
            <span className="text-[14px] text-muted">{indexedCases.length} indexed</span>
          )}
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
        {canonicalCases.map((c) => (
          <CaseCard key={c.case_id} case_={c} compact={compact} />
        ))}
      </div>

      {showDivider && (
        <div className="mt-8">
          <div className="mb-3 flex items-center gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
              Indexed · metadata only
            </span>
            <span className="h-px flex-1 bg-line" />
            <span className="text-[12px] text-faint">{indexedCases.length}</span>
          </div>
          <div className="space-y-2">
            {indexedCases.map((e) => (
              <IndexedCaseCard key={e.case_id} entry={e} compact={compact} />
            ))}
          </div>
        </div>
      )}

      {!showDivider && indexedCases.length > 0 && (
        <div className="space-y-2">
          {indexedCases.map((e) => (
            <IndexedCaseCard key={e.case_id} entry={e} compact={compact} />
          ))}
        </div>
      )}
    </div>
  );
}
