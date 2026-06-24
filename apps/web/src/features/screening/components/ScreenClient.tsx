"use client";

import { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import type {
  ScreeningResult,
  ScreeningRequest,
  ConditionResult,
  JurisdictionRule,
  ReviewPeriod,
} from "@/lib/types";
import { ChatIntake } from "./ChatIntake";
import { VerificationBadges } from "@/features/screening/components/VerificationBadges";

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtNum(value: number, currency?: string): string {
  let s: string;
  if (value >= 1e12) s = `${(value / 1e12).toFixed(1).replace(/\.0$/, "")}tn`;
  else if (value >= 1e9) s = `${(value / 1e9).toFixed(1).replace(/\.0$/, "")}bn`;
  else if (value >= 1e6) s = `${(value / 1e6).toFixed(0)}m`;
  else if (value >= 1e3) s = `${(value / 1e3).toFixed(0)}k`;
  else s = value.toLocaleString();
  return currency ? `${currency} ${s}` : s;
}

function fmtShare(value: number): string {
  const pct = value <= 1 ? value * 100 : value;
  const r = Math.round(pct * 10) / 10;
  return r === Math.round(r) ? `${r.toFixed(0)}%` : `${r.toFixed(1)}%`;
}

function periodUnit(period: ReviewPeriod): string {
  if (period.day_unit) return period.day_unit;
  if (period.day_type === "working") return "working days";
  return "days";
}

// ── Status + confidence badges ────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  if (status === "triggered") {
    return (
      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[12px] font-semibold bg-neg-soft text-neg">
        Filing required
      </span>
    );
  }
  if (status === "unclear" || status === "data_insufficient") {
    return (
      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[12px] font-semibold bg-[#FFF3CD] text-[#856404]">
        {status === "data_insufficient" ? "Insufficient data" : "Unclear"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[12px] font-semibold bg-canvas text-faint border border-line">
      No filing
    </span>
  );
}

function ConfidenceDot({ confidence }: { confidence: string }) {
  const cls =
    confidence === "high" ? "bg-pos" : confidence === "medium" ? "bg-[#856404]" : "bg-neg";
  return (
    <span className="flex items-center gap-1.5 text-[12px] text-muted">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cls}`} />
      {confidence} inputs
    </span>
  );
}

// ── Condition breakdown row ───────────────────────────────────────────────────

const SCOPE_LABELS: Record<string, string> = {
  worldwide: "Worldwide",
  domestic: "Domestic",
  eu_eea: "EU/EEA",
  eu_member_state: "EU member state",
  single_member_state: "Member state",
  uk: "UK",
  us: "US",
  eea_member_state: "EEA member state",
};

const PARTY_LABELS: Record<string, string> = {
  combined: "Combined",
  acquirer_group: "Acquirer",
  target_group: "Target",
  either_party: "Either party",
  each_party: "Each party",
  each_of_at_least_two: "Each of ≥2 parties",
};

const METRIC_LABELS: Record<string, string> = {
  revenue: "Revenue",
  assets: "Assets",
  deal_value: "Deal value",
  revenue_or_assets: "Rev/assets",
  market_share: "Market share",
  incremental_share: "Incr. share",
};


function ConditionBreakdownRow({
  c,
  currency,
}: {
  c: ConditionResult;
  currency?: string;
}) {
  const isShare = c.condition_id.includes("share");
  const fmt = (v: number | undefined) =>
    v === undefined || v === null
      ? "—"
      : isShare
      ? fmtShare(v)
      : fmtNum(v, currency);

  if (c.met === null || c.met === undefined) {
    return (
      <div className="flex items-start gap-2 py-1.5 text-[12px]">
        <span className="mt-0.5 flex-shrink-0 w-4 h-4 rounded-full bg-[#FFF3CD] flex items-center justify-center text-[10px] font-bold text-[#856404]">
          ?
        </span>
        <div className="flex-1 min-w-0">
          <span className="text-muted font-mono text-[11px]">{c.condition_id}</span>
          {c.missing_data && (
            <span className="ml-1 text-[#856404]">— missing: {c.missing_data}</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2 py-1.5 text-[12px]">
      <span
        className={`mt-0.5 flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold ${
          c.met ? "bg-pos-soft text-pos" : "bg-neg-soft text-neg"
        }`}
      >
        {c.met ? "✓" : "✗"}
      </span>
      <div className="flex-1 min-w-0">
        <span className="text-faint font-mono text-[11px]">{c.condition_id}</span>
        <div className="flex flex-wrap gap-x-3 mt-0.5">
          {c.actual_value !== undefined && c.actual_value !== null && (
            <span className={c.met ? "text-pos font-medium" : "text-neg font-medium"}>
              {fmt(c.actual_value)}
            </span>
          )}
          <span className="text-faint">
            threshold: {fmt(c.threshold_value)}
          </span>
          {!c.met && c.gap !== undefined && c.gap !== null && (
            <span className="text-faint">
              gap: {fmt(Math.abs(c.gap))}
            </span>
          )}
        </div>
        {c.note && <p className="text-faint mt-0.5">{c.note}</p>}
      </div>
    </div>
  );
}

// ── Why section (test-level breakdown) ───────────────────────────────────────

function WhySection({ result }: { result: ScreeningResult }) {
  const { status, test_results, triggered_by, notes } = result;

  return (
    <div className="px-4 py-4 border-b border-line">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-faint mb-3">
        Why this result
      </p>

      {test_results.length === 0 && (
        <p className="text-[13px] text-muted">No threshold tests available for this jurisdiction.</p>
      )}

      <div className="space-y-3">
        {test_results.map((tr) => {
          const fired = triggered_by.includes(tr.test_id);
          const allMissing = tr.conditions.every((c) => c.met === null || c.met === undefined);
          const somePass = tr.conditions.some((c) => c.met === true);

          let badgeCls = "bg-canvas text-faint border border-line";
          let badgeLabel = "Not triggered";
          if (tr.excluded) {
            badgeCls = "bg-slatey-soft text-slatey";
            badgeLabel = "Excluded";
          } else if (fired) {
            badgeCls = "bg-neg-soft text-neg";
            badgeLabel = "Triggered";
          } else if (allMissing) {
            badgeCls = "bg-[#FFF3CD] text-[#856404]";
            badgeLabel = "Data missing";
          }

          return (
            <div key={tr.test_id} className="rounded-lg border border-line overflow-hidden">
              <div className="px-3 py-2 bg-canvas/60 flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <code className="text-[10px] text-faint">{tr.test_id}</code>
                  {tr.description && (
                    <p className="text-[12px] font-medium text-ink mt-0.5 leading-snug">
                      {tr.description}
                    </p>
                  )}
                </div>
                <span className={`flex-shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full ${badgeCls}`}>
                  {badgeLabel}
                </span>
              </div>

              {tr.excluded ? (
                <div className="px-3 py-2 text-[12px] text-faint">
                  {tr.exclusion_reason ?? "Transaction excluded from this test."}
                </div>
              ) : (
                <div className="px-3 divide-y divide-line/60">
                  {tr.conditions.map((c) => (
                    <ConditionBreakdownRow key={c.condition_id} c={c} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {notes.length > 0 && (
        <div className="mt-3 space-y-1">
          {notes.map((n, i) => (
            <p key={i} className="text-[12px] text-faint leading-relaxed">
              {n}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Jurisdiction profile panel content ────────────────────────────────────────

function JurisdictionProfile({ rule }: { rule: JurisdictionRule }) {
  const p1 = rule.review_periods.phase_1;
  const p2 = rule.review_periods.phase_2;
  const hasFees = rule.fees?.structure && rule.fees.structure.trim() !== "none";

  return (
    <div className="px-4 py-4 space-y-5">
      {/* Authority links */}
      <div className="flex flex-wrap gap-2">
        <a
          href={rule.authority.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-[7px] border border-line bg-canvas px-2.5 py-1.5 text-[12px] text-ink hover:bg-surface transition-colors"
        >
          {rule.authority.abbreviation} ↗
        </a>
        {rule.authority.filing_url && (
          <a
            href={rule.authority.filing_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-[7px] border border-brand/30 bg-brand-soft px-2.5 py-1.5 text-[12px] text-brand hover:bg-brand hover:text-white transition-colors"
          >
            Filing portal ↗
          </a>
        )}
      </div>

      {/* Practical info grid */}
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-faint mb-2">
          Practical next steps
        </p>
        <div className="rounded-xl border border-line bg-surface divide-y divide-line overflow-hidden">
          {/* Filing deadline */}
          {rule.filing && (
            <>
              {rule.filing.pre_closing_required && (
                <div className="px-3 py-2.5 flex items-start gap-3">
                  <span className="text-[11px] text-faint w-28 flex-shrink-0 pt-0.5">Pre-closing</span>
                  <span className="text-[12px] font-medium text-neg">Required</span>
                </div>
              )}
              {rule.filing.deadline_from_signing_days != null && (
                <div className="px-3 py-2.5 flex items-start gap-3">
                  <span className="text-[11px] text-faint w-28 flex-shrink-0 pt-0.5">From signing</span>
                  <span className="text-[12px] font-semibold text-ink">
                    {rule.filing.deadline_from_signing_days} days
                  </span>
                </div>
              )}
              {rule.filing.deadline_from_closing_days != null && (
                <div className="px-3 py-2.5 flex items-start gap-3">
                  <span className="text-[11px] text-faint w-28 flex-shrink-0 pt-0.5">From closing</span>
                  <span className="text-[12px] font-semibold text-ink">
                    {rule.filing.deadline_from_closing_days} days
                  </span>
                </div>
              )}
              {rule.filing.note && (
                <div className="px-3 py-2.5 text-[12px] text-muted leading-relaxed bg-canvas/40">
                  {rule.filing.note.trim()}
                </div>
              )}
            </>
          )}

          {/* Review periods */}
          <div className="px-3 py-2.5 flex items-start gap-3">
            <span className="text-[11px] text-faint w-28 flex-shrink-0 pt-0.5">Phase 1</span>
            <span className="text-[12px] font-semibold text-ink">
              {p1.days} {periodUnit(p1)}
              {p1.extendable_to_days && (
                <span className="font-normal text-faint ml-1">
                  (ext. to {p1.extendable_to_days})
                </span>
              )}
            </span>
          </div>
          {p2 && (
            <div className="px-3 py-2.5 flex items-start gap-3">
              <span className="text-[11px] text-faint w-28 flex-shrink-0 pt-0.5">Phase 2</span>
              <span className="text-[12px] font-semibold text-ink">
                {p2.days} {periodUnit(p2)}
                {p2.extendable_to_days && (
                  <span className="font-normal text-faint ml-1">
                    (ext. to {p2.extendable_to_days})
                  </span>
                )}
              </span>
            </div>
          )}

          {/* Fees */}
          <div className="px-3 py-2.5 flex items-start gap-3">
            <span className="text-[11px] text-faint w-28 flex-shrink-0 pt-0.5">Filing fee</span>
            <span className={`text-[12px] font-semibold ${hasFees ? "text-ink" : "text-pos"}`}>
              {hasFees ? "Fee payable" : "No fee"}
              {rule.fees?.annual_adjustment && (
                <span className="ml-1 text-[10px] font-normal text-[#856404] bg-[#FFF3CD] px-1.5 py-0.5 rounded-full">
                  annual adj.
                </span>
              )}
            </span>
          </div>
          {hasFees && rule.fees?.structure && (
            <div className="px-3 py-2.5 bg-canvas/40">
              <pre className="text-[11px] text-muted font-mono whitespace-pre-wrap leading-relaxed">
                {rule.fees.structure.trim()}
              </pre>
            </div>
          )}

          {/* Suspensory */}
          <div className="px-3 py-2.5 flex items-start gap-3">
            <span className="text-[11px] text-faint w-28 flex-shrink-0 pt-0.5">Standstill</span>
            <span className={`text-[12px] font-semibold ${rule.regime.suspensory ? "text-neg" : "text-muted"}`}>
              {rule.regime.suspensory ? "Suspensory — do not close" : "Not suspensory"}
            </span>
          </div>
        </div>
      </div>

      {/* Gun jumping quick note */}
      {rule.gun_jumping && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-faint mb-2">
            Gun-jumping risk
          </p>
          <div className="rounded-xl border border-line bg-surface px-3 py-2.5 flex flex-wrap gap-3 text-[12px]">
            {rule.gun_jumping.automatic_void && (
              <span className="text-neg font-medium">Automatic void</span>
            )}
            {rule.gun_jumping.max_fine_pct_turnover != null && (
              <span className="text-muted">
                Up to <span className="font-semibold text-neg">{rule.gun_jumping.max_fine_pct_turnover}%</span> of worldwide turnover
              </span>
            )}
            {rule.gun_jumping.max_fine_fixed != null && rule.gun_jumping.max_fine_currency && (
              <span className="text-muted">
                Max <span className="font-semibold text-neg">
                  {fmtNum(rule.gun_jumping.max_fine_fixed, rule.gun_jumping.max_fine_currency)}
                </span>
              </span>
            )}
            {rule.gun_jumping.criminal_sanctions && (
              <span className="text-neg font-medium">Criminal sanctions possible</span>
            )}
            {rule.gun_jumping.note && (
              <p className="w-full text-faint leading-relaxed">{rule.gun_jumping.note.trim()}</p>
            )}
          </div>
        </div>
      )}

      {/* View full profile link */}
      <Link
        href={`/jurisdictions/${rule.jurisdiction_id}`}
        className="block text-center text-[12px] text-brand hover:underline py-1"
      >
        View full jurisdiction profile ↗
      </Link>
    </div>
  );
}

// ── Side panel ────────────────────────────────────────────────────────────────

function JurisdictionPanel({
  result,
  onClose,
}: {
  result: ScreeningResult;
  onClose: () => void;
}) {
  const [rule, setRule] = useState<JurisdictionRule | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setRule(null);
    setLoading(true);
    const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    fetch(`${baseUrl}/jurisdictions/${result.jurisdiction_id}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { setRule(data); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [result.jurisdiction_id]);

  return (
    <div className="w-[380px] flex-shrink-0 flex flex-col border-l border-line bg-surface overflow-hidden">
      {/* Panel header */}
      <div className="px-4 py-3 border-b border-line flex items-center gap-2 bg-canvas shrink-0">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[14px] font-semibold text-ink truncate">
              {result.jurisdiction_name}
            </span>
            <StatusBadge status={result.status} />
          </div>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <ConfidenceDot confidence={result.screening_confidence ?? result.confidence} />
            <VerificationBadges
              tier={result.source_verification_tier}
              freshness={result.freshness_status}
            />
            {result.suspensory && (
              <span className="text-[11px] text-brand">Suspensory</span>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-[6px] text-faint hover:text-ink hover:bg-line/60 transition-colors text-[16px]"
          aria-label="Close panel"
        >
          ×
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto">
        {/* Why section */}
        <WhySection result={result} />

        {/* Jurisdiction profile */}
        {loading && (
          <div className="px-4 py-6 flex flex-col items-center gap-2">
            <div className="w-5 h-5 border-2 border-brand border-t-transparent rounded-full animate-spin" />
            <p className="text-[12px] text-faint">Loading jurisdiction profile…</p>
          </div>
        )}
        {rule && !loading && <JurisdictionProfile rule={rule} />}
      </div>
    </div>
  );
}

// ── Results ───────────────────────────────────────────────────────────────────

function ResultsView({
  results,
  onReset,
}: {
  results: ScreeningResult[];
  onReset: () => void;
}) {
  const [selectedResult, setSelectedResult] = useState<ScreeningResult | null>(null);

  const sorted = [...results].sort((a, b) => {
    const order: Record<string, number> = {
      triggered: 0, unclear: 1, data_insufficient: 2, not_triggered: 3,
    };
    return (order[a.status] ?? 3) - (order[b.status] ?? 3);
  });

  const filingCount = results.filter((r) => r.status === "triggered").length;
  const unclearCount = results.filter(
    (r) => r.status === "unclear" || r.status === "data_insufficient"
  ).length;

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      <div className="py-3 border-b border-line flex items-center gap-3 shrink-0 bg-canvas">
        <span className="text-[14px] font-semibold text-ink">Results</span>
        <span className="text-[12px] bg-neg-soft text-neg px-2 py-0.5 rounded-full font-medium">
          {filingCount} filing{filingCount !== 1 ? "s" : ""}
        </span>
        {unclearCount > 0 && (
          <span className="text-[12px] bg-[#FFF3CD] text-[#856404] px-2 py-0.5 rounded-full font-medium">
            {unclearCount} unclear
          </span>
        )}
        <span className="text-[12px] text-faint">{results.length} jurisdictions</span>
        <div className="flex-1" />
        {selectedResult && (
          <button
            onClick={() => setSelectedResult(null)}
            className="text-[12px] text-faint hover:text-ink"
          >
            Close panel
          </button>
        )}
        <button onClick={onReset} className="text-[12px] text-brand hover:underline">
          ← New screening
        </button>
      </div>

      {/* Table + panel */}
      <div className="flex flex-1 min-h-0">
        {/* Scrollable table */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 bg-canvas border-b border-line z-10">
              <tr>
                <th className="text-left px-6 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Jurisdiction</th>
                <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Status</th>
                <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint hidden sm:table-cell">Inputs</th>
                <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint hidden lg:table-cell">Source</th>
                <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint hidden md:table-cell">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {sorted.map((r) => {
                const isSelected = selectedResult?.jurisdiction_id === r.jurisdiction_id;
                return (
                  <tr
                    key={r.jurisdiction_id}
                    onClick={() => setSelectedResult(isSelected ? null : r)}
                    className={`cursor-pointer transition-colors ${
                      isSelected
                        ? "bg-brand-soft/30 hover:bg-brand-soft/40"
                        : r.status === "triggered"
                        ? "bg-neg-soft/10 hover:bg-neg-soft/20"
                        : "hover:bg-canvas/60"
                    }`}
                  >
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2">
                        {isSelected && (
                          <span className="w-1.5 h-1.5 rounded-full bg-brand flex-shrink-0" />
                        )}
                        <div>
                          <div className="font-medium text-ink">{r.jurisdiction_name}</div>
                          {r.suspensory && <div className="text-[11px] text-brand">Suspensory</div>}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-3 py-3 hidden lg:table-cell">
                      <VerificationBadges
                        tier={r.source_verification_tier}
                        freshness={r.freshness_status}
                      />
                    </td>
                    <td className="px-3 py-3 hidden sm:table-cell">
                      <ConfidenceDot confidence={r.screening_confidence ?? r.confidence} />
                    </td>
                    <td className="px-3 py-3 hidden md:table-cell">
                      {r.triggered_by.length > 0 ? (
                        <ul className="space-y-0.5">
                          {r.triggered_by.map((tid) => {
                            const t = r.test_results.find((tr) => tr.test_id === tid);
                            return (
                              <li key={tid} className="text-[12px] text-muted">
                                {t?.description ?? tid}
                              </li>
                            );
                          })}
                        </ul>
                      ) : (r.status === "unclear" || r.status === "data_insufficient") ? (
                        <div className="text-[12px] text-[#856404]">
                          {(() => {
                            const missing = r.test_results
                              .flatMap((t) => t.conditions)
                              .filter((c) => c.met === null || c.met === undefined)
                              .map((c) => c.missing_data)
                              .filter((v, i, a): v is string => !!v && a.indexOf(v) === i);
                            return missing.length > 0
                              ? `Missing: ${missing.join("; ")}`
                              : "Insufficient data";
                          })()}
                        </div>
                      ) : (
                        <span className="text-[12px] text-faint">
                          {r.test_results.length > 0
                            ? `${r.test_results.length} test${r.test_results.length !== 1 ? "s" : ""} checked`
                            : "—"}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {!selectedResult && (
            <p className="text-[12px] text-faint text-center py-4">
              Click a row to see the full reasoning and next steps
            </p>
          )}
        </div>

        {/* Side panel */}
        {selectedResult && (
          <JurisdictionPanel
            result={selectedResult}
            onClose={() => setSelectedResult(null)}
          />
        )}
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function ScreenClient() {
  const [results, setResults] = useState<ScreeningResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleScreeningRequest = useCallback(async (req: ScreeningRequest, selectedIds: string[]) => {
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const baseUrl =
        typeof window !== "undefined"
          ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
          : "http://localhost:8000";
      const res = await fetch(`${baseUrl}/jurisdictions/screen`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const all: ScreeningResult[] = await res.json();
      // Filter to only jurisdictions the user explicitly selected
      const filtered = selectedIds.length > 0
        ? all.filter((r) => selectedIds.includes(r.jurisdiction_id))
        : all;
      setResults(filtered);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center space-y-2">
          <div className="w-6 h-6 border-2 border-brand border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-[13px] text-muted">Screening 47 jurisdictions…</p>
        </div>
      </div>
    );
  }

  if (results) {
    return <ResultsView results={results} onReset={() => setResults(null)} />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {error && (
        <div className="mt-4 shrink-0 rounded-lg border border-neg bg-neg-soft px-4 py-3 text-[13px] text-neg">
          {error}
        </div>
      )}
      <ChatIntake onScreeningRequest={handleScreeningRequest} />
    </div>
  );
}
