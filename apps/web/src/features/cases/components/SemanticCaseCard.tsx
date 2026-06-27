import Link from "next/link";
import type { CaseSearchHit } from "@/lib/types";
import { formatDate, outcomeTone, formatOutcome } from "@/lib/utils";
import { Badge } from "@/components/Badge";
import { Juris } from "./Juris";

export function SemanticCaseCard({ hit, compact = false }: { hit: CaseSearchHit; compact?: boolean }) {
  const isSource = hit.data_layer === "canonical";
  const href = isSource ? `/cases/${hit.case_id}` : `/indexed-cases/${hit.case_id}`;

  if (compact) {
    return (
      <Link
        href={href}
        className="group flex items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-2.5 transition-all hover:border-line-strong hover:shadow-card"
      >
        <Juris code={hit.jurisdiction} className="shrink-0" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-medium text-ink group-hover:text-brand-ink transition-colors">
            {hit.case_name}
          </h3>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted">
            <span>{formatDate(hit.decision_date)}</span>
            <span className="text-line-strong">·</span>
            <span className="capitalize">{hit.sector}</span>
            {hit.similarity_score !== undefined && (
              <>
                <span className="text-line-strong">·</span>
                <span className="text-brand-ink">{Math.round(hit.similarity_score * 100)}% match</span>
              </>
            )}
          </div>
        </div>
        <Badge tone={outcomeTone(hit.outcome)} dot className="shrink-0">
          {formatOutcome(hit.outcome)}
        </Badge>
      </Link>
    );
  }

  return (
    <Link
      href={href}
      className="group relative block rounded-xl border border-line bg-surface p-5 transition-all hover:border-line-strong hover:shadow-card"
    >
      {hit.similarity_score !== undefined && (
        <div className="absolute right-3 top-3 rounded-[5px] bg-brand-soft px-1.5 py-[2px] font-mono text-[11.5px] text-brand-ink">
          {Math.round(hit.similarity_score * 100)}% match
        </div>
      )}

      <div className="mb-2 flex items-start justify-between gap-4 pr-20">
        <div className="flex min-w-0 items-start gap-3">
          <Juris code={hit.jurisdiction} className="mt-0.5 shrink-0" />
          <h3 className="font-serif text-[19px] leading-snug text-ink transition-colors group-hover:text-brand-ink">
            {hit.case_name}
          </h3>
        </div>
        <Badge tone={outcomeTone(hit.outcome)} dot>{formatOutcome(hit.outcome)}</Badge>
      </div>

      <div className="mb-2 flex flex-wrap gap-x-2.5 gap-y-1 text-[13px] text-muted">
        <span>{hit.authority}</span>
        <span className="text-line-strong">·</span>
        <span>{formatDate(hit.decision_date)}</span>
        <span className="text-line-strong">·</span>
        <span className="capitalize">{hit.sector}</span>
        {hit.product_market_count > 0 && (
          <>
            <span className="text-line-strong">·</span>
            <span>{hit.product_market_count} market{hit.product_market_count !== 1 ? "s" : ""}</span>
          </>
        )}
      </div>

      {hit.ai_summary && (
        <p className="line-clamp-2 text-[13px] text-muted">{hit.ai_summary}</p>
      )}

      {!isSource && (
        <div className="mt-2 text-[11.5px] font-medium uppercase tracking-[0.06em] text-faint">Indexed · metadata only</div>
      )}
    </Link>
  );
}
