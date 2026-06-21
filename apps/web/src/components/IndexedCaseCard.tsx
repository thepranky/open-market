import Link from "next/link";
import type { IndexedCaseDetail } from "@/lib/types";
import { formatDate, outcomeTone, formatOutcome } from "@/lib/utils";
import { Badge } from "./Badge";
import { Juris } from "./Juris";

interface IndexedCaseCardProps {
  entry: IndexedCaseDetail;
  compact?: boolean;
}

export function IndexedCaseCard({ entry: e, compact = false }: IndexedCaseCardProps) {
  if (compact) {
    return (
      <Link
        href={`/indexed-cases/${e.case_id}`}
        className="group flex items-center gap-3 rounded-lg border border-dashed border-line bg-canvas px-3.5 py-2.5 transition-all hover:border-line-strong hover:bg-surface"
      >
        <Juris code={e.jurisdiction} className="shrink-0" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-medium text-ink group-hover:text-brand-ink transition-colors">
            {e.case_name}
          </h3>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted">
            <span className="capitalize">{e.sector}</span>
            <span className="text-line-strong">·</span>
            <span>{formatDate(e.decision_date)}</span>
            {e.concept_refs.length > 0 && (
              <>
                <span className="text-line-strong">·</span>
                <span>{e.concept_refs.length} concepts</span>
              </>
            )}
          </div>
        </div>
        <Badge tone={outcomeTone(e.outcome)} dot className="shrink-0">
          {formatOutcome(e.outcome)}
        </Badge>
      </Link>
    );
  }

  return (
    <Link
      href={`/indexed-cases/${e.case_id}`}
      className="group grid w-full grid-cols-[auto_1fr_auto] items-center gap-4 rounded-[9px] border border-dashed border-line bg-canvas px-4 py-3 transition-all hover:border-line-strong hover:bg-surface"
    >
      <Juris code={e.jurisdiction} />
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <span className="truncate text-[15px] font-medium text-ink transition-colors group-hover:text-brand-ink">
            {e.case_name}
          </span>
          <span className="hidden rounded-[4px] border border-line px-1.5 py-[1px] text-[11px] font-medium uppercase tracking-[0.06em] text-faint sm:inline">
            Indexed
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[12.5px] text-muted">
          <span className="capitalize">{e.sector}</span>
          <span className="text-line-strong">·</span>
          <span>{formatDate(e.decision_date)}</span>
          {e.concept_refs.length > 0 && (
            <>
              <span className="text-line-strong">·</span>
              <span>{e.concept_refs.length} concepts</span>
            </>
          )}
        </div>
      </div>
      <Badge tone={outcomeTone(e.outcome)} dot>{formatOutcome(e.outcome)}</Badge>
    </Link>
  );
}
