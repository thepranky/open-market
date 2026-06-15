import Link from "next/link";
import type { IndexedCaseDetail } from "@/lib/types";
import { formatDate, outcomeTone, formatOutcome } from "@/lib/utils";
import { Badge } from "./Badge";
import { Juris } from "./Juris";

interface IndexedCaseCardProps {
  entry: IndexedCaseDetail;
}

export function IndexedCaseCard({ entry: e }: IndexedCaseCardProps) {
  return (
    <Link
      href={`/indexed-cases/${e.case_id}`}
      className="group grid grid-cols-[auto_1fr_auto] items-center gap-4 w-full rounded-[9px] border border-dashed border-line bg-canvas px-4 py-3 hover:border-line-strong hover:bg-surface transition-all"
    >
      <Juris code={e.jurisdiction} />
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <span className="text-[15px] font-medium text-ink truncate group-hover:text-brand-ink transition-colors">
            {e.case_name}
          </span>
          <span className="hidden sm:inline text-[11px] font-medium uppercase tracking-[0.06em] text-faint border border-line rounded-[4px] px-1.5 py-[1px]">
            Indexed
          </span>
        </div>
        <div className="mt-0.5 text-[12.5px] text-muted flex items-center gap-2">
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
