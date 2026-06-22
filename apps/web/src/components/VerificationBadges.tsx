// Shared verification/freshness badges for screening results and jurisdiction
// detail pages. Pure presentational — safe to render from server or client.

// Amber "attention" styling, matching the arbitrary palette used elsewhere.
export const WARN_BADGE = "bg-[#FFF3CD] text-[#856404]";

export function VerificationBadges({
  tier = 0,
  freshness = "unknown",
  regression,
  className = "",
}: {
  tier?: number;
  freshness?: string;
  regression?: string;
  className?: string;
}) {
  const tierLabel =
    tier >= 2 ? "Source verified" : tier >= 1 ? "Passages linked" : "Unverified source";
  const tierCls =
    tier >= 2 ? "bg-pos-soft text-pos" : tier >= 1 ? "bg-brand-soft text-brand" : WARN_BADGE;
  const stale = freshness === "stale" || freshness === "drift_detected";

  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className}`}>
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${tierCls}`}
      >
        {tierLabel}
      </span>
      {stale && (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${WARN_BADGE}`}
        >
          Stale data
        </span>
      )}
      {regression === "passed" && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-pos-soft text-pos">
          Regression passed
        </span>
      )}
    </div>
  );
}
