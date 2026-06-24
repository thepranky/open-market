"use client";

import Link from "next/link";
import type { EntityCase } from "@/lib/types";
import { cn, formatDate, jurisdictionFlag } from "@/lib/utils";

interface StatusChipProps {
  label: string;
  count: number;
  colorClass: string;
}

function StatusChip({ label, count, colorClass }: StatusChipProps) {
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium", colorClass)}>
      {label}
      <span className="bg-white/40 rounded-full px-1 tabular-nums">{count}</span>
    </span>
  );
}

const DEFINITION_STATUS_COLORS: Record<string, string> = {
  defined: "bg-emerald-100 text-emerald-800",
  left_open: "bg-amber-100 text-amber-800",
  discussed: "bg-slate-100 text-slate-700",
  segmented: "bg-blue-100 text-blue-800",
  considered: "bg-purple-100 text-purple-800",
};

const OUTCOME_COLORS: Record<string, string> = {
  cleared: "bg-emerald-100 text-emerald-800",
  cleared_with_conditions: "bg-amber-100 text-amber-800",
  cleared_with_remedies: "bg-amber-100 text-amber-800",
  blocked: "bg-red-100 text-red-800",
  abandoned: "bg-slate-100 text-slate-700",
  referred: "bg-blue-100 text-blue-800",
  pending: "bg-slate-100 text-slate-700",
};

interface EntityDetailPanelProps {
  title: string;
  subtitle?: string;
  /** Record<statusLabel, count> — for definition_status or outcome */
  statusBreakdown?: Record<string, number>;
  statusColorMap?: Record<string, string>;
  cases: EntityCase[];
  onExpand?: () => void;
  onClose: () => void;
  expandLabel?: string;
  expandLoading?: boolean;
  entityType?: "market" | "theory" | "other";
}

export function EntityDetailPanel({
  title,
  subtitle,
  statusBreakdown,
  statusColorMap,
  cases,
  onExpand,
  onClose,
  expandLabel = "Expand in graph",
  expandLoading = false,
  entityType = "other",
}: EntityDetailPanelProps) {
  const colorMap =
    statusColorMap ??
    (entityType === "market" ? DEFINITION_STATUS_COLORS : OUTCOME_COLORS);

  return (
    <div className="w-72 shrink-0 flex flex-col border-l border-slate-200 bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 p-4 border-b border-slate-100">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 leading-snug break-words">
            {title}
          </h3>
          {subtitle && (
            <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 text-slate-400 hover:text-slate-700 transition-colors text-lg leading-none"
          aria-label="Close panel"
        >
          ×
        </button>
      </div>

      {/* Status breakdown chips */}
      {statusBreakdown && Object.keys(statusBreakdown).length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pt-3 pb-2">
          {Object.entries(statusBreakdown)
            .sort(([, a], [, b]) => b - a)
            .map(([status, count]) => (
              <StatusChip
                key={status}
                label={status.replace(/_/g, " ")}
                count={count}
                colorClass={colorMap[status] ?? "bg-slate-100 text-slate-700"}
              />
            ))}
        </div>
      )}

      {/* Case list */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-50">
        {cases.length === 0 ? (
          <p className="text-xs text-slate-400 px-4 py-3">No cases found.</p>
        ) : (
          cases.map((ec) => (
            <Link
              key={ec.case_id}
              href={`/cases/${ec.case_id}`}
              className="flex items-start gap-2 px-4 py-2.5 hover:bg-slate-50 transition-colors group"
            >
              <span className="text-base shrink-0 mt-0.5">
                {jurisdictionFlag(ec.jurisdiction as "EU" | "UK" | "US")}
              </span>
              <div className="min-w-0">
                <p className="text-xs font-medium text-slate-900 group-hover:text-blue-700 leading-snug break-words">
                  {ec.case_name}
                </p>
                <p className="text-xs text-slate-400 mt-0.5">
                  {ec.authority} · {formatDate(ec.decision_date).slice(0, 4)}
                  {ec.definition_status && (
                    <span
                      className={cn(
                        "ml-1.5 px-1 py-0 rounded text-xs",
                        DEFINITION_STATUS_COLORS[ec.definition_status] ?? "text-slate-500"
                      )}
                    >
                      {ec.definition_status.replace(/_/g, " ")}
                    </span>
                  )}
                  {ec.similarity !== undefined && (
                    <span className="ml-1.5 text-violet-600">
                      {Math.round(ec.similarity * 100)}%
                    </span>
                  )}
                </p>
              </div>
            </Link>
          ))
        )}
      </div>

      {/* Footer actions */}
      <div className="border-t border-slate-100 p-3 flex gap-2">
        {onExpand && (
          <button
            onClick={onExpand}
            disabled={expandLoading || cases.length === 0}
            className="flex-1 text-xs bg-slate-800 text-white rounded-lg py-2 hover:bg-slate-700 disabled:opacity-40 transition-colors"
          >
            {expandLoading ? "Adding…" : expandLabel}
          </button>
        )}
        <Link
          href={`/explore?q=${encodeURIComponent(title)}`}
          className="flex-1 text-center text-xs bg-slate-100 text-slate-700 rounded-lg py-2 hover:bg-slate-200 transition-colors"
        >
          View in explore →
        </Link>
      </div>
    </div>
  );
}
