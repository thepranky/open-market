import { getJurisdiction } from "@/lib/api";
import { notFound } from "next/navigation";
import type {
  ThresholdCondition,
  ThresholdTest,
  SourceType,
  MetricType,
  SourcePassage,
  JurisdictionScope,
  GunJumping,
  FdiScreening,
  Fees,
  ReviewPeriod,
} from "@/lib/types";

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtVal(value: number, currency?: string, metric?: MetricType): string {
  if (metric === "market_share" || metric === "incremental_share") {
    const pct = value <= 1 ? value * 100 : value;
    const r = Math.round(pct * 10) / 10;
    return r === Math.round(r) ? `${r.toFixed(0)}%` : `${r.toFixed(1)}%`;
  }
  let s: string;
  if (value >= 1e12) s = `${(value / 1e12).toFixed(1).replace(/\.0$/, "")}tn`;
  else if (value >= 1e9) s = `${(value / 1e9).toFixed(1).replace(/\.0$/, "")}bn`;
  else if (value >= 1e6) s = `${(value / 1e6).toFixed(0)}m`;
  else if (value >= 1e3) s = `${(value / 1e3).toFixed(0)}k`;
  else s = value.toLocaleString();
  return currency ? `${currency} ${s}` : s;
}

const PARTY_LABELS: Record<string, string> = {
  combined: "Combined",
  acquirer_group: "Acquirer",
  target_group: "Target",
  either_party: "Either party",
  each_party: "Each party",
  each_of_at_least_two: "Each of ≥2 parties",
};

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

const METRIC_LABELS: Record<string, string> = {
  revenue: "Revenue",
  assets: "Assets",
  deal_value: "Deal value",
  revenue_or_assets: "Revenue or assets",
  market_share: "Market share",
  incremental_share: "Incremental share",
};

// ── Review period formatting ──────────────────────────────────────────────────

function singularize(n: number, unit: string): string {
  if (n === 1) return unit.replace(/months$/, "month").replace(/weeks$/, "week").replace(/days$/, "day");
  return unit;
}

function periodUnit(period: ReviewPeriod): string {
  if (period.day_unit) return period.day_unit;
  if (period.day_type === "working") return "working days";
  return "days";
}

function fmtPeriodLabel(period: ReviewPeriod): string {
  const unit = singularize(period.days, periodUnit(period));
  return `${period.days} ${unit}`;
}

function fmtExtendedLabel(period: ReviewPeriod): string | null {
  if (!period.extendable_to_days) return null;
  const rawUnit = period.day_unit_extended ?? periodUnit(period);
  const unit = singularize(period.extendable_to_days, rawUnit);
  return `Extendable to ${period.extendable_to_days} ${unit}`;
}

// ── Source type badge ─────────────────────────────────────────────────────────

const SOURCE_STYLES: Record<SourceType, { label: string; cls: string }> = {
  primary_legislation:   { label: "Primary legislation",  cls: "bg-brand-soft text-brand" },
  official_guidance:     { label: "Official guidance",     cls: "bg-pos-soft text-pos" },
  authority_announcement:{ label: "Authority notice",      cls: "bg-slatey-soft text-slatey" },
  practitioner:          { label: "Practitioner",          cls: "bg-neg-soft text-neg" },
};

function SourceChip({ type, href }: { type: SourceType; href?: string }) {
  const s = SOURCE_STYLES[type] ?? SOURCE_STYLES.practitioner;
  const cls = `inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap ${s.cls}`;
  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={`${cls} hover:opacity-80 underline-offset-2 hover:underline`}>
        {s.label} ↗
      </a>
    );
  }
  return <span className={cls}>{s.label}</span>;
}

// ── Condition row ─────────────────────────────────────────────────────────────

function ConditionRow({
  c,
  passages,
}: {
  c: ThresholdCondition;
  passages: SourcePassage[];
}) {
  const linked = passages.filter((p) => p.supports_conditions.includes(c.condition_id));
  return (
    <div className="py-3 px-4 border-b border-line last:border-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-1.5">
        <span className="text-[13px] font-medium text-ink w-28 flex-shrink-0">
          {PARTY_LABELS[c.party] ?? c.party}
        </span>
        <span className="text-[13px] text-muted w-28 flex-shrink-0">
          {SCOPE_LABELS[c.scope] ?? c.scope}
        </span>
        <span className="text-[13px] text-muted w-28 flex-shrink-0">
          {METRIC_LABELS[c.metric] ?? c.metric}
        </span>
        <span className="text-[13px] font-semibold text-ink flex-shrink-0">
          {c.operator}{" "}{fmtVal(c.value, c.currency, c.metric)}
        </span>
        <div className="flex-shrink-0">
          <SourceChip type={c.source_type} href={c.source_url ?? c.verified_via?.[0]} />
        </div>
      </div>
      {c.note && (
        <p className="mt-1.5 text-[12px] text-faint leading-relaxed">
          {c.note.trim()}
        </p>
      )}
      {c.source && (
        <p className="mt-0.5 text-[11px] text-faint italic">
          {c.source_url ? (
            <a href={c.source_url} target="_blank" rel="noopener noreferrer"
               className="hover:underline text-brand/70">
              {c.source} ↗
            </a>
          ) : c.source}
        </p>
      )}
      {c.verified_via && c.verified_via.length > 0 && (
        <p className="mt-0.5 text-[11px] text-faint">
          Also cited in:{" "}
          {c.verified_via.map((url, i) => {
            const host = (() => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } })();
            return (
              <span key={url}>
                {i > 0 && ", "}
                <a href={url} target="_blank" rel="noopener noreferrer"
                   className="hover:underline text-faint underline-offset-2">
                  {host} ↗
                </a>
              </span>
            );
          })}
        </p>
      )}
      {/* Source passages for this condition */}
      {linked.map((p) => (
        <div key={p.passage_id} className="mt-2 rounded-lg border border-line bg-canvas/60 px-3 py-2">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-faint">
              Source text
            </span>
            <span className="text-[11px] text-brand font-medium">{p.article_reference}</span>
            <a
              href={p.document_url}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto text-[11px] text-brand hover:underline flex-shrink-0"
            >
              {p.document_title.split("(")[0].trim()} ↗
            </a>
          </div>
          <blockquote className="text-[12px] text-muted leading-relaxed border-l-2 border-brand/30 pl-2.5 font-mono">
            {p.quoted_text.trim()}
          </blockquote>
        </div>
      ))}
    </div>
  );
}

// ── Scope section ─────────────────────────────────────────────────────────────

const TRIGGER_LABELS: Record<string, string> = {
  merger: "Merger / consolidation",
  share_acquisition: "Share acquisition",
  asset_acquisition: "Asset acquisition",
  joint_venture: "Joint venture (full-function)",
  minority_stake: "Minority stake",
};

function ScopeSection({ scope }: { scope: JurisdictionScope }) {
  return (
    <section className="mb-8">
      <h2 className="text-[15px] font-semibold text-ink mb-3">Scope &amp; trigger events</h2>
      <div className="rounded-xl border border-line bg-surface divide-y divide-line overflow-hidden">
        {scope.trigger_events.length > 0 && (
          <div className="px-4 py-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint mb-2">
              Transaction types covered
            </p>
            <div className="flex flex-wrap gap-1.5">
              {scope.trigger_events.map((ev) => (
                <span
                  key={ev}
                  className="px-2.5 py-1 rounded-full text-[12px] bg-brand-soft text-brand font-medium"
                >
                  {TRIGGER_LABELS[ev] ?? ev}
                </span>
              ))}
            </div>
          </div>
        )}
        {scope.concentration_definition && (
          <div className="px-4 py-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint mb-1.5">
              Definition of concentration
            </p>
            <p className="text-[13px] text-muted leading-relaxed">
              {scope.concentration_definition.trim()}
            </p>
            {scope.concentration_definition_source && (
              <p className="mt-1 text-[11px] text-faint italic">
                {scope.concentration_definition_url ? (
                  <a href={scope.concentration_definition_url} target="_blank" rel="noopener noreferrer"
                     className="hover:underline text-brand/70">
                    {scope.concentration_definition_source} ↗
                  </a>
                ) : scope.concentration_definition_source}
              </p>
            )}
          </div>
        )}
        {scope.control_threshold && (
          <div className="px-4 py-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint mb-1.5">
              Control threshold
            </p>
            <p className="text-[13px] text-muted leading-relaxed">{scope.control_threshold.trim()}</p>
          </div>
        )}
        {scope.intra_group_exempt != null && (
          <div className="px-4 py-3 flex items-center gap-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint">
              Intra-group transactions
            </p>
            <span
              className={`text-[12px] font-medium px-2 py-0.5 rounded-full ${
                scope.intra_group_exempt
                  ? "bg-pos-soft text-pos"
                  : "bg-neg-soft text-neg"
              }`}
            >
              {scope.intra_group_exempt ? "Exempt" : "Not exempt"}
            </span>
          </div>
        )}
        {scope.foreign_to_foreign_rule && (
          <div className="px-4 py-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint mb-1.5">
              Foreign-to-foreign transactions
            </p>
            <p className="text-[13px] text-muted leading-relaxed">
              {scope.foreign_to_foreign_rule.trim()}
            </p>
          </div>
        )}
        {scope.substantive_test && (
          <div className="px-4 py-3 flex flex-wrap items-start gap-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint w-40 flex-shrink-0 pt-0.5">
              Substantive test
            </p>
            <div className="flex-1 min-w-0">
              <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[12px] font-semibold mb-1 ${
                scope.substantive_test === "siec" ? "bg-brand-soft text-brand" :
                scope.substantive_test === "slc"  ? "bg-pos-soft text-pos" :
                "bg-slatey-soft text-slatey"
              }`}>
                {scope.substantive_test === "dominance"          ? "Dominance test" :
                 scope.substantive_test === "siec"               ? "SIEC" :
                 scope.substantive_test === "slc"                ? "SLC (substantial lessening of competition)" :
                 scope.substantive_test === "dominance_and_siec" ? "Dominance + SIEC" :
                 scope.substantive_test}
              </span>
              {scope.substantive_test_url && (
                <a href={scope.substantive_test_url} target="_blank" rel="noopener noreferrer"
                   className="ml-2 text-[11px] text-brand/70 hover:underline">
                  Source ↗
                </a>
              )}
              {scope.substantive_test_note && (
                <p className="text-[12px] text-muted leading-relaxed mt-0.5">{scope.substantive_test_note.trim()}</p>
              )}
            </div>
          </div>
        )}
        {scope.note && (
          <div className="px-4 py-3 bg-canvas/40">
            <p className="text-[12px] text-muted leading-relaxed">{scope.note.trim()}</p>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Gun-jumping section ───────────────────────────────────────────────────────

function GunJumpingSection({ gj }: { gj: GunJumping }) {
  return (
    <section className="mb-8">
      <h2 className="text-[15px] font-semibold text-ink mb-3">
        Standstill obligation &amp; gun-jumping consequences
      </h2>
      <div className="rounded-xl border border-line bg-surface divide-y divide-line overflow-hidden">
        <div className="px-4 py-3 flex flex-wrap gap-4">
          {gj.automatic_void != null && (
            <div>
              <p className="text-[11px] text-faint uppercase tracking-wide mb-0.5">Automatic void</p>
              <span className={`text-[13px] font-semibold ${gj.automatic_void ? "text-neg" : "text-muted"}`}>
                {gj.automatic_void ? "Yes" : "No"}
              </span>
            </div>
          )}
          {gj.voidable != null && (
            <div>
              <p className="text-[11px] text-faint uppercase tracking-wide mb-0.5">Voidable</p>
              <span className={`text-[13px] font-semibold ${gj.voidable ? "text-neg" : "text-muted"}`}>
                {gj.voidable ? "Yes" : "No"}
              </span>
            </div>
          )}
          {gj.max_fine_pct_turnover != null && (
            <div>
              <p className="text-[11px] text-faint uppercase tracking-wide mb-0.5">Max fine</p>
              <span className="text-[13px] font-semibold text-neg">
                {gj.max_fine_pct_turnover}% of worldwide turnover
              </span>
            </div>
          )}
          {gj.max_fine_fixed != null && gj.max_fine_currency && (
            <div>
              <p className="text-[11px] text-faint uppercase tracking-wide mb-0.5">Max fixed fine</p>
              <span className="text-[13px] font-semibold text-neg">
                {fmtVal(gj.max_fine_fixed, gj.max_fine_currency)}
              </span>
            </div>
          )}
          {gj.criminal_sanctions != null && (
            <div>
              <p className="text-[11px] text-faint uppercase tracking-wide mb-0.5">Criminal sanctions</p>
              <span className={`text-[13px] font-semibold ${gj.criminal_sanctions ? "text-neg" : "text-muted"}`}>
                {gj.criminal_sanctions ? "Yes" : "No"}
              </span>
            </div>
          )}
        </div>
        {gj.legal_basis && (
          <div className="px-4 py-2">
            <p className="text-[11px] text-faint italic">
              {gj.legal_basis_url ? (
                <a href={gj.legal_basis_url} target="_blank" rel="noopener noreferrer"
                   className="hover:underline text-brand/70">
                  {gj.legal_basis} ↗
                </a>
              ) : gj.legal_basis}
            </p>
          </div>
        )}
        {gj.note && (
          <div className="px-4 py-3 bg-canvas/40">
            <p className="text-[13px] text-muted leading-relaxed">{gj.note.trim()}</p>
          </div>
        )}
      </div>
    </section>
  );
}

// ── FDI screening section ─────────────────────────────────────────────────────

function FdiSection({ fdi }: { fdi: FdiScreening }) {
  return (
    <section className="mb-8">
      <h2 className="text-[15px] font-semibold text-ink mb-3">
        FDI / national security screening
      </h2>
      <div className="rounded-xl border border-line bg-surface overflow-hidden">
        <div className="px-4 py-3 flex flex-wrap items-center gap-3 border-b border-line">
          <span
            className={`text-[12px] font-semibold px-2.5 py-1 rounded-full ${
              fdi.applicable ? "bg-neg-soft text-neg" : "bg-slatey-soft text-slatey"
            }`}
          >
            {fdi.applicable ? "FDI screening applicable" : "No unified FDI regime"}
          </span>
          {fdi.regime_name && (
            <span className="text-[13px] font-medium text-ink">{fdi.regime_name}</span>
          )}
          <div className="ml-auto flex items-center gap-3">
            {fdi.legislation_url && (
              <a href={fdi.legislation_url} target="_blank" rel="noopener noreferrer"
                 className="text-[12px] text-brand/70 hover:underline">
                Legislation ↗
              </a>
            )}
            {fdi.url && (
              <a href={fdi.url} target="_blank" rel="noopener noreferrer"
                 className="text-[12px] text-brand hover:underline">
                Authority ↗
              </a>
            )}
          </div>
        </div>
        {fdi.note && (
          <div className="px-4 py-3">
            <p className="text-[13px] text-muted leading-relaxed">{fdi.note.trim()}</p>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Fees section ──────────────────────────────────────────────────────────────

function FeesSection({ fees }: { fees: Fees }) {
  const hasFees = fees.structure && fees.structure.trim() !== "none";
  return (
    <section className="mb-8">
      <h2 className="text-[15px] font-semibold text-ink mb-3">Filing fees</h2>
      <div className="rounded-xl border border-line bg-surface overflow-hidden">
        <div className="px-4 py-3 flex items-center gap-3 border-b border-line">
          <span className={`text-[12px] font-semibold px-2.5 py-1 rounded-full ${
            hasFees ? "bg-neg-soft text-neg" : "bg-pos-soft text-pos"
          }`}>
            {hasFees ? "Fee payable" : "No filing fee"}
          </span>
          {fees.annual_adjustment && (
            <span className="text-[10px] bg-[#FFF3CD] text-[#856404] px-2 py-0.5 rounded-full font-medium">
              Adjusted annually
            </span>
          )}
          {fees.source_url && (
            <a href={fees.source_url} target="_blank" rel="noopener noreferrer"
               className="ml-auto text-[12px] text-brand hover:underline flex-shrink-0">
              Source ↗
            </a>
          )}
        </div>
        {hasFees && (
          <pre className="px-4 py-3 text-[12px] text-muted font-mono whitespace-pre-wrap leading-relaxed border-b border-line">
            {fees.structure!.trim()}
          </pre>
        )}
        {fees.source && (
          <p className="px-4 py-2 text-[11px] text-faint italic">
            {fees.source_url ? (
              <a href={fees.source_url} target="_blank" rel="noopener noreferrer"
                 className="hover:underline text-brand/70">
                {fees.source} ↗
              </a>
            ) : fees.source}
            {fees.source_type && (
              <> · <SourceChip type={fees.source_type} href={fees.source_url} /></>
            )}
          </p>
        )}
        {fees.note && (
          <div className="px-4 py-3 bg-canvas/40">
            <p className="text-[12px] text-muted leading-relaxed">{fees.note.trim()}</p>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Threshold test card ───────────────────────────────────────────────────────

function TestCard({ test, passages }: { test: ThresholdTest; passages: SourcePassage[] }) {
  const isIndicative = test.status === "indicative_only";
  return (
    <div className="rounded-xl border border-line bg-surface overflow-hidden mb-4">
      <div className="px-4 py-3 bg-canvas border-b border-line flex flex-wrap items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-0.5">
            <code className="text-[11px] text-faint font-mono">{test.test_id}</code>
            {test.annual_adjustment && (
              <span className="text-[10px] bg-[#FFF3CD] text-[#856404] px-1.5 py-0.5 rounded-full font-medium">
                Annual update
              </span>
            )}
            {isIndicative && (
              <span className="text-[10px] bg-slatey-soft text-slatey px-1.5 py-0.5 rounded-full font-medium">
                Indicative only
              </span>
            )}
            {test.effective_date && (
              <span className="text-[10px] text-faint">
                Effective {test.effective_date}
              </span>
            )}
          </div>
          <p className="text-[13px] font-medium text-ink leading-snug">{test.description}</p>
        </div>
        {test.source_url && (
          <a
            href={test.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-shrink-0 text-[12px] text-brand hover:underline"
          >
            Source ↗
          </a>
        )}
      </div>

      {/* Conditions header */}
      <div className="px-4 pt-2 pb-1 bg-canvas/50 border-b border-line">
        <div className="flex flex-wrap gap-x-4 text-[11px] font-medium uppercase tracking-wide text-faint">
          <span className="w-28">Party</span>
          <span className="w-28">Scope</span>
          <span className="w-28">Metric</span>
          <span>Threshold</span>
        </div>
      </div>

      {/* Conditions */}
      <div>
        {test.conditions.map((c) => (
          <ConditionRow key={c.condition_id} c={c} passages={passages} />
        ))}
      </div>

      {/* Exceptions */}
      {test.exceptions.length > 0 && (
        <div className="px-4 py-3 border-t border-line bg-canvas/30">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint mb-2">Exceptions</p>
          {test.exceptions.map((ex) => (
            <div key={ex.exception_id} className="text-[12px] text-muted mb-1">
              <span className="font-medium text-ink">{ex.exception_id}: </span>
              {ex.description}
            </div>
          ))}
        </div>
      )}

      {/* Exclusions */}
      {test.exclusions.length > 0 && (
        <div className="px-4 py-3 border-t border-line bg-canvas/30">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint mb-2">Exclusions</p>
          {test.exclusions.map((ex) => (
            <div key={ex.exclusion_id} className="text-[12px] text-muted mb-1">
              <span className="font-medium text-ink">{ex.exclusion_id}: </span>
              {ex.description}
            </div>
          ))}
        </div>
      )}

      {/* Test note */}
      {test.note && (
        <div className="px-4 py-3 border-t border-line bg-canvas/20">
          <p className="text-[12px] text-muted leading-relaxed">{test.note.trim()}</p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default async function JurisdictionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let rule;
  try {
    rule = await getJurisdiction(id);
  } catch {
    notFound();
  }

  const mandatory = rule.regime.mandatory;
  const suspensory = rule.regime.suspensory;
  const p1 = rule.review_periods.phase_1;
  const p2 = rule.review_periods.phase_2;

  return (
    <div className="px-6 py-8 max-w-4xl">
      {/* Header */}
      <div className="mb-6">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <h1 className="text-[22px] font-semibold text-ink mr-1">{rule.jurisdiction_name}</h1>
          <span className="text-[13px] font-medium text-faint">{rule.authority.abbreviation}</span>
          {mandatory ? (
            <span className="text-[11px] bg-pos-soft text-pos px-2 py-0.5 rounded-full font-medium">Mandatory</span>
          ) : (
            <span className="text-[11px] bg-slatey-soft text-slatey px-2 py-0.5 rounded-full font-medium">Voluntary</span>
          )}
          {suspensory && (
            <span className="text-[11px] bg-brand-soft text-brand px-2 py-0.5 rounded-full font-medium">Suspensory</span>
          )}
        </div>
        <p className="text-[13px] text-muted">{rule.authority.name}</p>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        {[
          { label: "Phase 1", value: fmtPeriodLabel(p1) },
          { label: "Phase 2", value: p2 ? fmtPeriodLabel(p2) : "—" },
          { label: "Tests", value: String(rule.threshold_tests.length) },
          { label: "Last verified", value: rule.last_verified },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-line bg-surface px-4 py-3">
            <p className="text-[11px] text-faint uppercase tracking-wide mb-0.5">{s.label}</p>
            <p className="text-[14px] font-semibold text-ink">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Authority links */}
      <div className="flex flex-wrap gap-2 mb-8">
        <a
          href={rule.authority.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-[7px] border border-line bg-surface px-3 py-1.5 text-[13px] text-ink hover:bg-canvas transition-colors"
        >
          {rule.authority.abbreviation} website ↗
        </a>
        <a
          href={rule.authority.filing_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-[7px] border border-brand/30 bg-brand-soft px-3 py-1.5 text-[13px] text-brand hover:bg-brand hover:text-white transition-colors"
        >
          Filing portal ↗
        </a>
      </div>

      {/* Scope / trigger events */}
      {rule.scope && <ScopeSection scope={rule.scope} />}

      {/* Threshold tests */}
      <section className="mb-8">
        <h2 className="text-[15px] font-semibold text-ink mb-4">
          Threshold tests
          <span className="ml-2 text-[12px] font-normal text-faint">
            (tests are OR&#8217;d; conditions within each test are AND&#8217;d)
          </span>
        </h2>
        {rule.threshold_tests.map((t) => (
          <TestCard key={t.test_id} test={t} passages={rule.source_passages ?? []} />
        ))}
      </section>

      {/* Filing deadlines */}
      {rule.filing && (
        <section className="mb-8">
          <h2 className="text-[15px] font-semibold text-ink mb-3">Filing</h2>
          <div className="rounded-xl border border-line bg-surface p-4 text-[13px] text-muted space-y-1.5">
            <div className="flex gap-2">
              <span className="font-medium text-ink w-36 flex-shrink-0">Pre-closing required</span>
              <span>{rule.filing.pre_closing_required ? "Yes" : "No"}</span>
            </div>
            {rule.filing.deadline_from_signing_days != null && (
              <div className="flex gap-2">
                <span className="font-medium text-ink w-36 flex-shrink-0">Deadline (signing)</span>
                <span>{rule.filing.deadline_from_signing_days} days</span>
              </div>
            )}
            {rule.filing.deadline_from_closing_days != null && (
              <div className="flex gap-2">
                <span className="font-medium text-ink w-36 flex-shrink-0">Deadline (closing)</span>
                <span>{rule.filing.deadline_from_closing_days} days</span>
              </div>
            )}
            {rule.filing.note && (
              <p className="mt-2 pt-2 border-t border-line text-[12px] leading-relaxed">{rule.filing.note.trim()}</p>
            )}
          </div>
        </section>
      )}

      {/* Filing fees */}
      {rule.fees && <FeesSection fees={rule.fees} />}

      {/* Review periods */}
      <section className="mb-8">
        <h2 className="text-[15px] font-semibold text-ink mb-3">Review periods</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          {[
            { label: "Phase 1", period: p1 },
            { label: "Phase 2", period: p2 },
          ].filter((x) => x.period).map(({ label, period }) => {
            const extLabel = fmtExtendedLabel(period);
            return (
              <div key={label} className="rounded-xl border border-line bg-surface p-4">
                <p className="text-[11px] text-faint uppercase tracking-wide mb-1.5">{label}</p>
                <p className="text-[18px] font-bold text-ink mb-0.5">
                  {period.days}
                  <span className="text-[13px] font-normal text-muted ml-1">
                    {periodUnit(period)}
                  </span>
                </p>
                {extLabel && (
                  <p className="text-[12px] text-faint">{extLabel}</p>
                )}
                {period.legal_basis && (
                  <p className="mt-1.5 text-[11px] text-faint italic">{period.legal_basis}</p>
                )}
                {period.note && (
                  <p className="mt-2 pt-2 border-t border-line text-[12px] text-muted leading-relaxed">
                    {period.note.trim()}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Gun-jumping */}
      {rule.gun_jumping && <GunJumpingSection gj={rule.gun_jumping} />}

      {/* FDI screening */}
      {rule.fdi_screening && <FdiSection fdi={rule.fdi_screening} />}

      {/* Legal basis */}
      {rule.legal_basis?.length > 0 && (
        <section className="mb-8">
          <h2 className="text-[15px] font-semibold text-ink mb-3">Legal basis</h2>
          <div className="space-y-2">
            {rule.legal_basis.map((lb, i) => (
              <div key={i} className="rounded-xl border border-line bg-surface p-4">
                <div className="flex flex-wrap items-start gap-2 mb-1">
                  <p className="flex-1 text-[13px] font-medium text-ink">{lb.citation}</p>
                  <SourceChip type={lb.source_type ?? "primary_legislation"} href={lb.url} />
                </div>
                {lb.note && (
                  <p className="text-[12px] text-muted leading-relaxed mt-1">{lb.note.trim()}</p>
                )}
                {lb.url && (
                  <a
                    href={lb.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1.5 inline-block text-[11px] text-brand hover:underline"
                  >
                    {lb.url}
                  </a>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Notes */}
      {rule.notes?.length > 0 && (
        <section className="mb-8">
          <h2 className="text-[15px] font-semibold text-ink mb-3">Notes</h2>
          <ul className="space-y-2">
            {rule.notes.map((note, i) => (
              <li
                key={i}
                className="rounded-xl border border-line bg-surface px-4 py-3 text-[13px] text-muted leading-relaxed"
              >
                {note.trim()}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
