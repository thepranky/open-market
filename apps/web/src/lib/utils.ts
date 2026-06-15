import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { DefinitionStatus, Outcome, ReviewStatus } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Outcome ──────────────────────────────────────────────────────────────────

export function formatOutcome(outcome: Outcome): string {
  const labels: Record<Outcome, string> = {
    cleared: "Cleared",
    cleared_with_remedies: "Cleared with Conditions",
    cleared_with_conditions: "Cleared with Conditions",
    blocked: "Blocked",
    abandoned: "Abandoned",
    referred: "Referred",
    pending: "Pending",
    pending_litigation: "Pending Litigation",
    under_appeal: "Under Appeal",
    annulled: "Annulled",
    partially_annulled: "Partially Annulled",
    upheld_on_appeal: "Upheld on Appeal",
    unknown: "Unknown",
  };
  return labels[outcome] ?? outcome;
}

export function outcomeTone(outcome: Outcome): "pos" | "ai" | "neg" | "slatey" {
  switch (outcome) {
    case "cleared": return "pos";
    case "cleared_with_remedies":
    case "cleared_with_conditions": return "ai";
    case "blocked": return "neg";
    default: return "slatey";
  }
}

// ── Definition status ────────────────────────────────────────────────────────

export function defnLabel(status: DefinitionStatus): string {
  const labels: Record<DefinitionStatus, string> = {
    defined: "Defined",
    discussed: "Discussed",
    segmented: "Segmented",
    left_open: "Left open",
  };
  return labels[status] ?? status;
}

export function defnTone(status: DefinitionStatus): "pos" | "ai" | "seg" | "slatey" {
  switch (status) {
    case "defined": return "pos";
    case "left_open": return "ai";
    case "segmented": return "seg";
    default: return "slatey";
  }
}

// ── Jurisdiction ─────────────────────────────────────────────────────────────

const JURIS_META: Record<string, { authority: string }> = {
  EU: { authority: "European Commission" },
  UK: { authority: "Competition & Markets Authority" },
  US: { authority: "DOJ / FTC" },
};

export function jurisdictionAuthority(j: string): string {
  return JURIS_META[j]?.authority ?? j;
}

// Kept for any remaining callers
export function jurisdictionFlag(j: string): string {
  switch (j) {
    case "EU": return "🇪🇺";
    case "UK": return "🇬🇧";
    case "US": return "🇺🇸";
    default: return "🌐";
  }
}

// Kept for any remaining callers
export function outcomeColor(outcome: Outcome): string {
  switch (outcome) {
    case "cleared": return "bg-pos-soft text-pos-ink";
    case "cleared_with_remedies":
    case "cleared_with_conditions": return "bg-ai-soft text-ai-ink";
    case "blocked": return "bg-neg-soft text-neg-ink";
    case "abandoned": return "bg-slatey-soft text-slatey-ink";
    case "referred": return "bg-seg-soft text-seg-ink";
    default: return "bg-slatey-soft text-slatey-ink";
  }
}

// ── Dates & misc ─────────────────────────────────────────────────────────────

export function formatDate(d: string): string {
  try {
    return new Date(d).toLocaleDateString("en-GB", {
      day: "numeric", month: "short", year: "numeric",
    });
  } catch {
    return d;
  }
}

export function confidencePct(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function caseHistoryStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    final_no_known_challenge: "Final — no known challenge",
    challenged: "Challenged",
    pending_litigation: "Pending litigation",
    under_appeal: "Under appeal",
    upheld: "Upheld on appeal",
    upheld_on_appeal: "Upheld on appeal",
    annulled: "Annulled",
    partially_annulled: "Partially annulled",
    withdrawn: "Withdrawn",
    settled: "Settled",
    unknown: "Unknown",
  };
  return labels[status] ?? status;
}

export function caseHistoryStatusColor(status: string): string {
  switch (status) {
    case "final_no_known_challenge":
    case "upheld":
    case "upheld_on_appeal": return "bg-pos-soft text-pos-ink";
    case "challenged":
    case "pending_litigation":
    case "under_appeal": return "bg-ai-soft text-ai-ink";
    case "annulled":
    case "partially_annulled": return "bg-neg-soft text-neg-ink";
    default: return "bg-slatey-soft text-slatey-ink";
  }
}

export function reviewStatusLabel(status: ReviewStatus): string {
  const labels: Record<ReviewStatus, string> = {
    unreviewed: "Unreviewed",
    spot_checked: "Spot-checked",
    lawyer_reviewed: "Lawyer-reviewed",
  };
  return labels[status] ?? status;
}

export function reviewStatusColor(status: ReviewStatus): string {
  switch (status) {
    case "lawyer_reviewed": return "bg-pos-soft text-pos-ink";
    case "spot_checked": return "bg-ai-soft text-ai-ink";
    default: return "bg-neg-soft text-neg-ink";
  }
}

const CONCEPT_PREFIXES = ["toh_", "sector_", "proc_", "market_"] as const;

export function formatConceptId(id: string): string {
  let label = id;
  for (const prefix of CONCEPT_PREFIXES) {
    if (label.startsWith(prefix)) { label = label.slice(prefix.length); break; }
  }
  return label.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

export function conceptCategoryColor(conceptId: string): string {
  if (conceptId.startsWith("toh_"))    return "bg-seg-soft text-seg-ink border border-seg";
  if (conceptId.startsWith("sector_")) return "bg-slatey-soft text-slatey-ink border border-line-strong";
  if (conceptId.startsWith("proc_"))   return "bg-brand-soft text-brand-ink border border-brand";
  return "bg-slatey-soft text-slatey-ink border border-line-strong";
}
