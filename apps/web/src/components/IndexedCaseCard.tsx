import Link from "next/link";
import type { IndexedCaseDetail } from "@/lib/types";
import {
  cn,
  conceptCategoryColor,
  formatConceptId,
  formatDate,
  formatOutcome,
  jurisdictionFlag,
  outcomeColor,
} from "@/lib/utils";
import { Badge } from "./Badge";

interface IndexedCaseCardProps {
  entry: IndexedCaseDetail;
}

export function IndexedCaseCard({ entry: e }: IndexedCaseCardProps) {
  return (
    <Link
      href={`/indexed-cases/${e.case_id}`}
      className="block bg-amber-50/40 border border-amber-200 rounded-xl p-5 hover:border-amber-400 hover:shadow-sm transition-all group"
    >
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xl" title={e.jurisdiction}>
            {jurisdictionFlag(e.jurisdiction)}
          </span>
          <h3 className="font-semibold text-slate-900 group-hover:text-brand-700 leading-snug">
            {e.case_name}
          </h3>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Badge className={cn(outcomeColor(e.outcome))}>
            {formatOutcome(e.outcome)}
          </Badge>
          <Badge className="bg-amber-100 text-amber-800 border border-amber-200">
            Index entry
          </Badge>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 mb-3">
        <span>{e.authority}</span>
        <span>{formatDate(e.decision_date)}</span>
        <span className="capitalize">{e.sector}</span>
      </div>

      {e.concept_refs.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {e.concept_refs.map((ref) => (
            <span
              key={ref.concept_id}
              title={`${ref.quality_level} · ${ref.provenance.replace(/_/g, " ")}`}
              className={cn(
                "text-xs px-2 py-0.5 rounded",
                conceptCategoryColor(ref.concept_id)
              )}
            >
              {formatConceptId(ref.concept_id)}
            </span>
          ))}
        </div>
      )}

      <p className="text-xs text-amber-700">
        Metadata only — source-backed analysis not yet extracted.
      </p>
    </Link>
  );
}
