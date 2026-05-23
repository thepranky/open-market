import { cn, caseHistoryStatusColor, caseHistoryStatusLabel, formatDate } from "@/lib/utils";
import type { CaseHistory, CaseHistoryEvent } from "@/lib/types";

function HistoryEvent({ event }: { event: CaseHistoryEvent }) {
  return (
    <div className="relative pl-4 pb-4 last:pb-0">
      <span className="absolute left-0 top-1.5 w-2 h-2 rounded-full bg-slate-300 ring-2 ring-white" />
      <div className="text-xs text-slate-400 mb-0.5">
        {event.event_date ? formatDate(event.event_date) : "Date unknown"}
        {event.forum && (
          <span className="ml-2 text-slate-500">{event.forum}</span>
        )}
        {event.case_number && (
          <span className="ml-1 text-slate-400">({event.case_number})</span>
        )}
      </div>
      <div className="text-sm font-medium text-slate-700 mb-0.5">{event.title}</div>
      {event.outcome && (
        <div className="text-xs text-slate-500 mb-1">
          Outcome: <span className="capitalize">{event.outcome.replace(/_/g, " ")}</span>
        </div>
      )}
      {event.summary && (
        <p className="text-xs text-slate-600 leading-relaxed mb-1">
          {event.summary}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5 items-center">
        {event.source_url && (
          <a
            href={event.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-brand-600 hover:underline"
          >
            Source ↗
          </a>
        )}
      </div>
    </div>
  );
}

export function CaseHistoryPanel({
  history,
}: {
  history?: CaseHistory | null;
}) {
  const status = history?.status ?? "unknown";
  // Sort newest-first; events without a date fall to the bottom
  const events = [...(history?.events ?? [])].sort((a, b) => {
    if (!a.event_date && !b.event_date) return 0;
    if (!a.event_date) return 1;
    if (!b.event_date) return -1;
    return b.event_date.localeCompare(a.event_date);
  });

  return (
    <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
      <h3 className="text-sm font-semibold text-slate-700 mb-3">Case history</h3>

      <div className="mb-3">
        <span
          className={cn(
            "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
            caseHistoryStatusColor(status)
          )}
        >
          {caseHistoryStatusLabel(status)}
        </span>
      </div>

      {events.length > 0 ? (
        <div className="border-l-2 border-slate-200 ml-1 mt-3">
          {events.map((event, i) => (
            <HistoryEvent key={i} event={event} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-400">No case events recorded.</p>
      )}
    </div>
  );
}
