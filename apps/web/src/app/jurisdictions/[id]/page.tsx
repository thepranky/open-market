import { getJurisdiction } from "@/lib/api";
import { notFound } from "next/navigation";
import { SourcePill } from "@/components/SourcePill";
import { VerificationBadges } from "@/components/VerificationBadges";
import type {
  ThresholdCondition,
  ThresholdTest,
  SourceType,
  MetricType,
  SourcePassage,
  JurisdictionScope,
  MinorityThresholds,
  MinorityThresholdRule,
  GunJumping,
  FdiScreening,
  Fees,
  ReviewPeriod,
  PractitionerNote,
} from "@/lib/types";

// ── Formatting helpers ────────────────────────────────────────────────────────

const FX_TO_USD: Record<string, number> = {
  EUR: 0.92, GBP: 0.79, CNY: 7.24, CAD: 1.37, BRL: 5.10,
  JPY: 150.0, KRW: 1370.0, INR: 84.0, AUD: 1.53, ZAR: 18.5,
  TRY: 32.0, MXN: 17.0, PLN: 4.0, ILS: 3.7, AED: 3.67,
  SAR: 3.75, NTD: 32.0, ARS: 1050.0, NGN: 1600.0, NZD: 1.63,
  RUB: 90.0, COP: 4200.0, KES: 130.0, EGP: 50.0, SGD: 1.35,
  HUF: 370.0, CZK: 23.0, DKK: 6.9, SEK: 10.5, NOK: 10.8,
  CHF: 0.9, RON: 4.6,
};

function fmtNum(value: number): string {
  if (value >= 1e12) return `${(value / 1e12).toFixed(1).replace(/\.0$/, "")}tn`;
  if (value >= 1e9)  return `${(value / 1e9).toFixed(1).replace(/\.0$/, "")}bn`;
  if (value >= 1e6)  return `${(value / 1e6).toFixed(0)}m`;
  if (value >= 1e3)  return `${(value / 1e3).toFixed(0)}k`;
  return value.toLocaleString();
}

function fmtVal(value: number, currency?: string, metric?: MetricType): string {
  if (metric === "market_share" || metric === "incremental_share") {
    const pct = value <= 1 ? value * 100 : value;
    const r = Math.round(pct * 10) / 10;
    return r === Math.round(r) ? `${r.toFixed(0)}%` : `${r.toFixed(1)}%`;
  }
  const base = currency ? `${currency} ${fmtNum(value)}` : fmtNum(value);
  if (!currency || currency === "USD") return base;
  const rate = FX_TO_USD[currency];
  if (!rate) return base;
  const usd = value / rate;
  return `${base} (≈ USD ${fmtNum(usd)})`;
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

// ── Condition row ─────────────────────────────────────────────────────────────

function ConditionRow({
  c,
  passages,
}: {
  c: ThresholdCondition;
  passages: SourcePassage[];
}) {
  // Derive pills from source passages linked to this condition
  const seenUrls = new Set<string>();
  const pills: Array<{ type: SourceType; href: string; quotedText?: string; articleRef?: string }> = [];

  for (const p of passages) {
    if (p.supports_conditions.includes(c.condition_id) && !seenUrls.has(p.document_url)) {
      seenUrls.add(p.document_url);
      pills.push({ type: p.source_type, href: p.document_url, quotedText: p.quoted_text, articleRef: p.article_reference });
    }
  }

  // Fallback: use the condition's own source_url if no passages are linked
  if (pills.length === 0 && c.source_url) {
    pills.push({ type: c.source_type, href: c.source_url });
  }

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
        {pills.length > 0 && (
          <div className="flex flex-wrap gap-1.5 flex-shrink-0">
            {pills.map((p, i) => (
              <SourcePill key={i} type={p.type} href={p.href} quotedText={p.quotedText} articleRef={p.articleRef} />
            ))}
          </div>
        )}
      </div>
      {c.note && (
        <p className="mt-1.5 text-[12px] text-faint leading-relaxed">{c.note.trim()}</p>
      )}
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
    <section id="scope" className="mb-8">
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
            {scope.concentration_definition_url && (
              <div className="mt-2">
                <SourcePill
                  type="official_guidance"
                  href={scope.concentration_definition_url}
                  label={scope.concentration_definition_source}
                />
              </div>
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
              <div className="flex flex-wrap items-center gap-2 mb-1">
                <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[12px] font-semibold ${
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
                  <SourcePill type="primary_legislation" href={scope.substantive_test_url} />
                )}
              </div>
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

// ── Minority thresholds section ───────────────────────────────────────────────

const REL_LABELS: Record<string, string> = {
  horizontal:     "Horizontal (competitors)",
  vertical:       "Vertical (supply chain)",
  conglomerate:   "Conglomerate",
  non_horizontal: "Non-horizontal (vertical + conglomerate)",
  any:            "Any relationship",
};

const STANDARD_LABELS: Record<string, { label: string; cls: string }> = {
  percentage_based:   { label: "Percentage-based thresholds", cls: "bg-neg-soft text-neg" },
  material_influence: { label: "Material influence standard", cls: "bg-brand-soft text-brand" },
  control_based:      { label: "Decisive influence / control standard", cls: "bg-slatey-soft text-slatey" },
  any_acquisition:    { label: "Any acquisition reviewable", cls: "bg-neg-soft text-neg" },
  none:               { label: "Not applicable", cls: "bg-pos-soft text-pos" },
};

const RIGHTS_LABELS: Record<string, string> = {
  board_seat:      "Board seat / director appointment",
  veto_ordinary:   "Veto over ordinary decisions",
  veto_strategic:  "Veto over strategic decisions (business plan, budget)",
};

function MinorityRuleRow({ rule }: { rule: MinorityThresholdRule }) {
  return (
    <div className="py-3 px-4 border-b border-line last:border-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-1.5">
        <span className="text-[13px] font-medium text-ink w-56 flex-shrink-0">
          {REL_LABELS[rule.relationship_type] ?? rule.relationship_type}
        </span>
        <span className="text-[13px] font-semibold text-ink flex-shrink-0">
          {rule.pct_threshold != null
            ? `${rule.operator} ${rule.pct_threshold}%`
            : "Any stake"}
        </span>
        {rule.rights_required && (
          <span className="text-[12px] px-2 py-0.5 rounded-full bg-slatey-soft text-slatey flex-shrink-0">
            + {RIGHTS_LABELS[rule.rights_required] ?? rule.rights_required.replace(/_/g, " ")}
          </span>
        )}
        {rule.source_url && (
          <SourcePill type={rule.source_type} href={rule.source_url} />
        )}
      </div>
      {rule.note && (
        <p className="mt-1.5 text-[12px] text-faint leading-relaxed">{rule.note.trim()}</p>
      )}
    </div>
  );
}

function MinorityThresholdsSection({ mt }: { mt: MinorityThresholds }) {
  const stdStyle = STANDARD_LABELS[mt.standard] ?? STANDARD_LABELS.control_based;
  return (
    <section id="minority-stakes" className="mb-8">
      <h2 className="text-[15px] font-semibold text-ink mb-3">Minority stake acquisitions</h2>
      <div className="rounded-xl border border-line bg-surface divide-y divide-line overflow-hidden">
        <div className="px-4 py-3 flex flex-wrap items-center gap-2">
          <span className={`text-[12px] font-semibold px-2.5 py-1 rounded-full ${stdStyle.cls}`}>
            {stdStyle.label}
          </span>
          <span className={`text-[12px] font-medium px-2.5 py-1 rounded-full ${
            mt.applies ? "bg-neg-soft text-neg" : "bg-pos-soft text-pos"
          }`}>
            {mt.applies ? "Minority stakes can trigger filing" : "Minority stakes generally not caught"}
          </span>
        </div>
        {mt.note && (
          <div className="px-4 py-3">
            <p className="text-[13px] text-muted leading-relaxed">{mt.note.trim()}</p>
          </div>
        )}
        {mt.rules.length > 0 && (
          <>
            <div className="px-4 pt-2 pb-1 bg-canvas/50">
              <div className="flex flex-wrap gap-x-4 text-[11px] font-medium uppercase tracking-wide text-faint">
                <span className="w-56">Relationship type</span>
                <span>Threshold</span>
              </div>
            </div>
            <div>
              {mt.rules.map((r) => (
                <MinorityRuleRow key={r.rule_id} rule={r} />
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

// ── Gun-jumping section ───────────────────────────────────────────────────────

function GunJumpingSection({ gj }: { gj: GunJumping }) {
  return (
    <section id="gun-jumping" className="mb-8">
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
        {gj.legal_basis_url && (
          <div className="px-4 py-2.5">
            <SourcePill
              type="primary_legislation"
              href={gj.legal_basis_url}
              label={gj.legal_basis}
            />
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
    <section id="fdi-screening" className="mb-8">
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
          <div className="ml-auto flex items-center gap-2">
            {fdi.legislation_url && (
              <SourcePill type="primary_legislation" href={fdi.legislation_url} />
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
    <section id="filing-fees" className="mb-8">
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
            <div className="ml-auto">
              <SourcePill
                type={fees.source_type ?? "official_guidance"}
                href={fees.source_url}
                label={fees.source}
              />
            </div>
          )}
        </div>
        {hasFees && (
          <div className="px-4 py-3 text-[12px] text-muted whitespace-pre-wrap leading-relaxed border-b border-line">
            {fees.structure!.trim()}
          </div>
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
          <div className="flex-shrink-0">
            <SourcePill
              type="primary_legislation"
              href={test.source_url}
              label={test.legal_basis || undefined}
            />
          </div>
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

// ── Practitioner notes section ────────────────────────────────────────────────

function PractitionerNotesSection({ notes }: { notes: PractitionerNote[] }) {
  if (!notes || notes.length === 0) return null;
  return (
    <section className="mb-8">
      <h2 className="text-[15px] font-semibold text-ink mb-1">Practitioner resources</h2>
      <p className="text-[12px] text-muted mb-3">
        Selected practitioner guides and firm notes on this jurisdiction&apos;s merger control regime.
      </p>
      <div className="space-y-3">
        {notes.map((n, i) => (
          <a
            key={i}
            href={n.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-xl border border-line bg-surface px-4 py-3 hover:border-brand/40 hover:bg-canvas transition-colors group"
          >
            <div className="flex flex-wrap items-start gap-x-3 gap-y-1 mb-1">
              <p className="text-[13px] font-medium text-ink group-hover:text-brand transition-colors flex-1 min-w-0">
                {n.title} ↗
              </p>
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-neg-soft text-neg whitespace-nowrap flex-shrink-0">
                Practitioner
              </span>
            </div>
            <p className="text-[12px] text-faint mb-1">{n.firm}{n.date ? ` · ${n.date}` : ""}</p>
            <p className="text-[12px] text-muted leading-relaxed">{n.summary}</p>
          </a>
        ))}
      </div>
    </section>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function fmtVerifiedDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

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
    <div className="px-6 py-8 lg:px-8">
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
        <VerificationBadges
          tier={rule.verification?.source_verification_tier}
          freshness={rule.verification?.freshness_status}
          regression={rule.verification?.regression_status}
          className="mt-2"
        />
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        {[
          { label: "Phase 1", value: fmtPeriodLabel(p1) },
          { label: "Phase 2", value: p2 ? fmtPeriodLabel(p2) : "—" },
          { label: "Tests", value: String(rule.threshold_tests.length) },
          { label: "Last updated", value: fmtVerifiedDate(rule.last_verified) },
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

      {/* Minority stake thresholds */}
      {rule.minority_thresholds && <MinorityThresholdsSection mt={rule.minority_thresholds} />}

      {/* Threshold tests */}
      <section id="threshold-tests" className="mb-8">
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

      {/* Filing */}
      {rule.filing && (
        <section id="filing" className="mb-8">
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
      <section id="review-periods" className="mb-8">
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
        <section id="legal-basis" className="mb-8">
          <h2 className="text-[15px] font-semibold text-ink mb-3">Legal basis</h2>
          <div className="space-y-2">
            {rule.legal_basis.map((lb, i) => (
              <div key={i} className="rounded-xl border border-line bg-surface p-4">
                <div className="flex flex-wrap items-start gap-2 mb-1">
                  <p className="flex-1 text-[13px] font-medium text-ink">{lb.citation}</p>
                  {lb.url && (
                    <SourcePill type={lb.source_type ?? "primary_legislation"} href={lb.url} />
                  )}
                </div>
                {lb.note && (
                  <p className="text-[12px] text-muted leading-relaxed mt-1">{lb.note.trim()}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Notes */}
      {rule.notes?.length > 0 && (
        <section id="notes" className="mb-8">
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

      {/* Practitioner resources */}
      {rule.practitioner_notes && rule.practitioner_notes.length > 0 && (
        <PractitionerNotesSection notes={rule.practitioner_notes} />
      )}
    </div>
  );
}
