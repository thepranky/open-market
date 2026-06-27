import { apiFetch, apiPost } from "@/lib/api-client";
import type {
  JurisdictionRule,
  JurisdictionSummary,
  ScreeningRequest,
  ScreeningResult,
} from "@/lib/types";

export async function getJurisdictions(): Promise<JurisdictionSummary[]> {
  return apiFetch<JurisdictionSummary[]>("/jurisdictions/");
}

export async function getJurisdiction(id: string): Promise<JurisdictionRule> {
  return apiFetch<JurisdictionRule>(`/jurisdictions/${id}`);
}

export async function screenDeal(req: ScreeningRequest): Promise<ScreeningResult[]> {
  return apiPost<ScreeningResult[]>("/jurisdictions/screen", req);
}
