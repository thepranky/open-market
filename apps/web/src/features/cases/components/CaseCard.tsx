import Link from "next/link";
import type { CaseRecord } from "@/lib/types";
import { formatDate, outcomeTone, formatOutcome, defnTone, defnLabel } from "@/lib/utils";
import { Badge } from "@/components/Badge";
import { Juris } from "./Juris";

interface CaseCardProps {
  case_: CaseRecord;
  compact?: boolean;
}

export function CaseCard({ case_: c, compact = false }: CaseCardProps) {
  const markets = c.product_markets_considered.slice(0, 3);
  const moreM = c.product_markets_considered.length - markets.length;
  const cites = c.source_passages.length;

  if (compact) {
    return (
      <Link
        href={`/cases/${c.case_id}`}
        className="group flex items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-2.5 transition-all hover:border-line-strong hover:shadow-card"
      >
        <Juris code={c.jurisdiction} className="shrink-0" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-medium text-ink group-hover:text-brand-ink transition-colors">
            {c.case_name}
          </h3>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted">
            <span>{formatDate(c.decision_date)}</span>
            <span className="text-line-strong">·</span>
            <span className="capitalize">{c.sector}</span>
            <span className="text-line-strong">·</span>
            <span className="text-faint">
              {c.product_markets_considered.length} markets · {cites} cites
            </span>
          </div>
        </div>
        <Badge tone={outcomeTone(c.outcome)} dot className="shrink-0">
          {formatOutcome(c.outcome)}
        </Badge>
      </Link>
    );
  }

  return (
    <Link
      href={`/cases/${c.case_id}`}
      className="block rounded-xl border border-line bg-surface p-5 transition-all hover:border-line-strong hover:shadow-card group"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1.5 flex items-center gap-2.5">
            <Juris code={c.jurisdiction} />
            <span className="font-mono text-[11.5px] text-faint">{c.case_id.toUpperCase().slice(0, 10)}</span>
            <span className="inline-flex items-center gap-1 whitespace-nowrap text-[11.5px] font-medium text-pos-ink">
              <svg width={13} height={13} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 10.5l4 4 8-9" /></svg>
              Source-reviewed
            </span>
          </div>
          <h3 className="font-serif text-[21px] leading-snug text-ink transition-colors group-hover:text-brand-ink">
            {c.case_name}
          </h3>
        </div>
        <Badge tone={outcomeTone(c.outcome)} dot>{formatOutcome(c.outcome)}</Badge>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-muted">
        <span>{c.authority}</span>
        <span className="text-line-strong">·</span>
        <span>{formatDate(c.decision_date)}</span>
        <span className="text-line-strong">·</span>
        <span className="capitalize">{c.sector}</span>
        <span className="text-line-strong">·</span>
        <span className="capitalize">{c.procedure_stage.replace(/_/g, " ")}</span>
      </div>

      {markets.length > 0 && (
        <div className="mt-4 space-y-1.5">
          {markets.map((m) => (
            <div key={m.market_id} className="flex items-center gap-2.5 rounded-[7px] border border-line bg-canvas px-3 py-2">
              <span className="flex-1 truncate text-[13.5px] text-ink">{m.name}</span>
              <Badge tone={defnTone(m.definition_status)}>{defnLabel(m.definition_status)}</Badge>
            </div>
          ))}
          {moreM > 0 && (
            <div className="pl-1 text-[12.5px] text-faint">+{moreM} more product market{moreM > 1 ? "s" : ""}</div>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {c.theories_of_harm.slice(0, 2).map((t) => (
            <span key={t.theory_id} className="inline-flex max-w-[280px] items-center gap-1.5 rounded-[6px] border border-line bg-canvas px-2.5 py-1 text-[12.5px] text-muted">
              <span className="h-1 w-1 shrink-0 rounded-full bg-faint" />
              <span className="truncate">{t.name.length > 46 ? t.name.slice(0, 44) + "…" : t.name}</span>
            </span>
          ))}
        </div>
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap font-mono text-[12px] text-faint">
          {c.product_markets_considered.length} markets · {cites} citations
        </span>
      </div>
    </Link>
  );
}
