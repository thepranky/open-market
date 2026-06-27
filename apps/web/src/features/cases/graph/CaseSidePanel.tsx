"use client";

import Link from "next/link";
import type { CaseRecord } from "@/lib/types";
import { cn, formatDate, jurisdictionFlag } from "@/lib/utils";

const DEFINITION_STATUS_COLORS: Record<string, string> = {
  defined:    "bg-emerald-100 text-emerald-800",
  left_open:  "bg-amber-100 text-amber-800",
  discussed:  "bg-slate-100 text-slate-700",
  segmented:  "bg-blue-100 text-blue-800",
  considered: "bg-purple-100 text-purple-800",
};

const OUTCOME_COLORS: Record<string, string> = {
  cleared:                  "bg-emerald-100 text-emerald-800",
  cleared_with_conditions:  "bg-amber-100 text-amber-800",
  cleared_with_remedies:    "bg-amber-100 text-amber-800",
  blocked:                  "bg-red-100 text-red-800",
  abandoned:                "bg-slate-100 text-slate-700",
  pending:                  "bg-slate-100 text-slate-700",
};

interface Props {
  caseId: string;
  caseRecord: CaseRecord | null;
  loading: boolean;
  onClose: () => void;
}

export function CaseSidePanel({ caseId, caseRecord, loading, onClose }: Props) {
  return (
    <div className="w-80 shrink-0 flex flex-col border-l border-slate-200 bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 p-4 border-b border-slate-100">
        <div className="min-w-0">
          {loading ? (
            <div className="h-4 w-48 bg-slate-100 rounded animate-pulse" />
          ) : (
            <h3 className="text-sm font-semibold text-slate-900 leading-snug break-words">
              {caseRecord?.case_name ?? caseId}
            </h3>
          )}
          {caseRecord && (
            <p className="text-xs text-slate-500 mt-1">
              {jurisdictionFlag(caseRecord.jurisdiction)}{" "}
              {caseRecord.authority} · {formatDate(caseRecord.decision_date).slice(0, 4)}
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 text-slate-400 hover:text-slate-700 text-lg leading-none"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {loading && (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-xs text-slate-400 animate-pulse">Loading case…</span>
        </div>
      )}

      {!loading && caseRecord && (
        <div className="flex-1 overflow-y-auto">
          {/* Outcome */}
          <div className="px-4 pt-3 pb-2">
            <span
              className={cn(
                "inline-block text-xs px-2 py-0.5 rounded-full font-medium capitalize",
                OUTCOME_COLORS[caseRecord.outcome] ?? "bg-slate-100 text-slate-700"
              )}
            >
              {caseRecord.outcome.replace(/_/g, " ")}
            </span>
          </div>

          {/* AI summary */}
          {caseRecord.ai_summary && (
            <div className="px-4 pb-3">
              <p className="text-xs text-slate-600 line-clamp-4">{caseRecord.ai_summary}</p>
            </div>
          )}

          {/* Product markets */}
          {caseRecord.product_markets_considered.length > 0 && (
            <div className="px-4 pb-3 border-t border-slate-50 pt-3">
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                Markets considered
              </p>
              <ul className="space-y-1.5">
                {caseRecord.product_markets_considered.map((pm) => (
                  <li key={pm.market_id} className="flex items-start gap-2">
                    <span
                      className={cn(
                        "shrink-0 mt-0.5 text-xs px-1.5 py-0.5 rounded font-medium",
                        DEFINITION_STATUS_COLORS[pm.definition_status] ?? "bg-slate-100 text-slate-700"
                      )}
                    >
                      {pm.definition_status.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-slate-700 leading-snug">{pm.name}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Theories of harm */}
          {caseRecord.theories_of_harm.length > 0 && (
            <div className="px-4 pb-3 border-t border-slate-50 pt-3">
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                Theories of harm
              </p>
              <ul className="space-y-1">
                {caseRecord.theories_of_harm.map((toh) => (
                  <li key={toh.theory_id} className="text-xs text-slate-700">{toh.name}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {!loading && !caseRecord && (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-xs text-slate-400">Could not load case.</span>
        </div>
      )}

      {/* Footer */}
      <div className="border-t border-slate-100 p-3">
        <Link
          href={`/cases/${caseId}`}
          className="block text-center text-xs bg-slate-800 text-white rounded-lg py-2 hover:bg-slate-700 transition-colors"
        >
          Open full case →
        </Link>
      </div>
    </div>
  );
}
