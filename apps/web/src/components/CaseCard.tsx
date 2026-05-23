import Link from "next/link";
import type { CaseRecord } from "@/lib/types";
import {
  cn,
  formatDate,
  formatOutcome,
  jurisdictionFlag,
  outcomeColor,
} from "@/lib/utils";
import { Badge } from "./Badge";

interface CaseCardProps {
  case_: CaseRecord;
}

export function CaseCard({ case_: c }: CaseCardProps) {
  return (
    <Link
      href={`/cases/${c.case_id}`}
      className="block bg-white border border-slate-200 rounded-xl p-5 hover:border-brand-400 hover:shadow-sm transition-all group"
    >
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xl" title={c.jurisdiction}>
            {jurisdictionFlag(c.jurisdiction)}
          </span>
          <h3 className="font-semibold text-slate-900 group-hover:text-brand-700 leading-snug">
            {c.case_name}
          </h3>
        </div>
        <Badge className={cn("shrink-0", outcomeColor(c.outcome))}>
          {formatOutcome(c.outcome)}
        </Badge>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 mb-3">
        <span>{c.authority}</span>
        <span>{formatDate(c.decision_date)}</span>
        <span className="capitalize">{c.sector}</span>
        <span className="capitalize">{c.procedure_stage.replace(/_/g, " ")}</span>
      </div>

      {c.product_markets_considered.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {c.product_markets_considered.slice(0, 3).map((m) => (
            <span
              key={m.market_id}
              className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded"
            >
              {m.name}
            </span>
          ))}
          {c.product_markets_considered.length > 3 && (
            <span className="text-xs text-slate-400">
              +{c.product_markets_considered.length - 3} more
            </span>
          )}
        </div>
      )}

      {c.theories_of_harm.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {c.theories_of_harm.slice(0, 2).map((t) => (
            <span
              key={t.theory_id}
              className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded"
            >
              {t.name.length > 40 ? t.name.slice(0, 40) + "…" : t.name}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
