import Link from "next/link";
import type { CaseSearchHit } from "@/lib/types";
import { formatDate, outcomeTone, formatOutcome } from "@/lib/utils";
import { Badge } from "./Badge";
import { Juris } from "./Juris";

export function SemanticCaseCard({ hit }: { hit: CaseSearchHit }) {
  const isSource = hit.data_layer === "canonical";
  const href = isSource ? `/cases/${hit.case_id}` : `/indexed-cases/${hit.case_id}`;

  return (
    <Link
      href={href}
      className="block relative bg-surface border border-line rounded-xl p-5 hover:border-line-strong hover:shadow-card transition-all group"
    >
      {hit.similarity_score !== undefined && (
        <div className="absolute top-3 right-3 text-[11.5px] font-mono text-brand-ink bg-brand-soft rounded-[5px] px-1.5 py-[2px]">
          {Math.round(hit.similarity_score * 100)}% match
        </div>
      )}

      <div className="flex items-start justify-between gap-4 mb-2 pr-20">
        <div className="flex items-start gap-3 min-w-0">
          <Juris code={hit.jurisdiction} className="mt-0.5 shrink-0" />
          <h3 className="font-serif text-[19px] text-ink leading-snug group-hover:text-brand-ink transition-colors">
            {hit.case_name}
          </h3>
        </div>
        <Badge tone={outcomeTone(hit.outcome)} dot>{formatOutcome(hit.outcome)}</Badge>
      </div>

      <div className="flex flex-wrap gap-x-2.5 gap-y-1 text-[13px] text-muted mb-2">
        <span>{hit.authority}</span>
        <span className="text-line-strong">·</span>
        <span>{formatDate(hit.decision_date)}</span>
        <span className="text-line-strong">·</span>
        <span className="capitalize">{hit.sector}</span>
        {hit.product_market_count > 0 && (
          <><span className="text-line-strong">·</span><span>{hit.product_market_count} market{hit.product_market_count !== 1 ? "s" : ""}</span></>
        )}
      </div>

      {hit.ai_summary && (
        <p className="text-[13px] text-muted line-clamp-2">{hit.ai_summary}</p>
      )}

      {!isSource && (
        <div className="mt-2 text-[11.5px] font-medium text-faint uppercase tracking-[0.06em]">Indexed · metadata only</div>
      )}
    </Link>
  );
}
