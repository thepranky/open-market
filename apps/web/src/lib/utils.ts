import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Outcome, ReviewStatus } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

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

export function outcomeColor(outcome: Outcome): string {
  switch (outcome) {
    case "cleared":
      return "bg-green-100 text-green-800";
    case "cleared_with_remedies":
    case "cleared_with_conditions":
      return "bg-yellow-100 text-yellow-800";
    case "blocked":
      return "bg-red-100 text-red-800";
    case "abandoned":
      return "bg-gray-100 text-gray-700";
    case "referred":
      return "bg-blue-100 text-blue-800";
    case "pending":
    case "pending_litigation":
      return "bg-orange-100 text-orange-800";
    case "under_appeal":
      return "bg-purple-100 text-purple-800";
    case "annulled":
    case "partially_annulled":
      return "bg-pink-100 text-pink-800";
    case "upheld_on_appeal":
      return "bg-teal-100 text-teal-800";
    default:
      return "bg-gray-100 text-gray-700";
  }
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
    case "upheld_on_appeal":
      return "bg-green-100 text-green-800";
    case "challenged":
    case "pending_litigation":
    case "under_appeal":
      return "bg-orange-100 text-orange-800";
    case "annulled":
    case "partially_annulled":
      return "bg-red-100 text-red-800";
    case "withdrawn":
    case "settled":
      return "bg-gray-100 text-gray-700";
    default:
      return "bg-slate-100 text-slate-600";
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
    case "lawyer_reviewed":
      return "bg-green-100 text-green-800";
    case "spot_checked":
      return "bg-yellow-100 text-yellow-800";
    case "unreviewed":
      return "bg-red-100 text-red-700";
    default:
      return "bg-gray-100 text-gray-600";
  }
}

export function jurisdictionFlag(j: string): string {
  switch (j) {
    case "EU": return "🇪🇺";
    case "UK": return "🇬🇧";
    case "US": return "🇺🇸";
    default: return "🌐";
  }
}

export function formatDate(d: string): string {
  try {
    return new Date(d).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return d;
  }
}

export function confidencePct(score: number): string {
  return `${Math.round(score * 100)}%`;
}
