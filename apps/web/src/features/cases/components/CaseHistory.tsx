import { cn, caseHistoryStatusColor, caseHistoryStatusLabel, formatDate } from "@/lib/utils";
import type { CaseHistory, CaseHistoryEvent } from "@/lib/types";
import { Badge } from "@/components/Badge";

function HistoryEvent({ event, isLast }: { event: CaseHistoryEvent; isLast: boolean }) {
  return (
    <li className="relative">
      <span className={cn(
        "absolute -left-4 top-1 w-[7px] h-[7px] rounded-full ring-2 ring-surface",
        isLast ? "bg-brand" : "bg-line-strong",
      )} />
      <div className="font-mono text-[11.5px] text-faint">
        {event.event_date ? formatDate(event.event_date) : "Date unknown"}
        {event.forum && <span className="ml-2 text-muted">{event.forum}</span>}
        {event.case_number && <span className="ml-1">({event.case_number})</span>}
      </div>
      <div className="text-[13.5px] text-ink leading-snug mt-0.5">{event.title}</div>
      {event.outcome && (
        <div className="text-[12px] text-muted mt-0.5 capitalize">{event.outcome.replace(/_/g, " ")}</div>
      )}
      {event.summary && (
        <p className="text-[12.5px] text-muted leading-relaxed mt-1">{event.summary}</p>
      )}
      {event.source_url && (
        <a href={event.source_url} target="_blank" rel="noopener noreferrer"
          className="text-[12px] text-brand-ink hover:underline mt-1 inline-block">
          Source ↗
        </a>
      )}
    </li>
  );
}

export function CaseHistoryPanel({ history }: { history?: CaseHistory | null }) {
  const status = history?.status ?? "unknown";
  const events = [...(history?.events ?? [])].sort((a, b) => {
    if (!a.event_date && !b.event_date) return 0;
    if (!a.event_date) return 1;
    if (!b.event_date) return -1;
    return b.event_date.localeCompare(a.event_date);
  });

  return (
    <div className="bg-surface border border-line rounded-xl p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-3">Case history</p>

      <div className="mb-4">
        <span className={cn("inline-flex items-center px-2 py-[3px] rounded-[5px] text-[12px] font-medium leading-none", caseHistoryStatusColor(status))}>
          {caseHistoryStatusLabel(status)}
        </span>
      </div>

      {events.length > 0 ? (
        <ol className="relative space-y-4 pl-4">
          <span className="absolute left-[3px] top-1.5 bottom-1.5 w-px bg-line" />
          {events.map((event, i) => (
            <HistoryEvent key={i} event={event} isLast={i === 0} />
          ))}
        </ol>
      ) : (
        <p className="text-[12.5px] text-faint">No events recorded.</p>
      )}
    </div>
  );
}
