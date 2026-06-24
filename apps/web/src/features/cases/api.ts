import { apiFetch } from "@/lib/api-client";
import type {
  AppStats,
  CaseRecord,
  CaseSearchHit,
  EntityCase,
  GraphNeighbourhood,
  GraphNeighborhoodResponse,
  IndexedCaseDetail,
  MarketSummary,
  SectorMarket,
  SectorSummary,
  SimilarMarket,
  TheorySummary,
} from "@/lib/types";

export async function getCases(params?: {
  jurisdiction?: string;
  sector?: string;
  outcome?: string;
  theory?: string;
  year_from?: number;
  year_to?: number;
}): Promise<CaseRecord[]> {
  const qs = new URLSearchParams();
  if (params?.jurisdiction) qs.set("jurisdiction", params.jurisdiction);
  if (params?.sector) qs.set("sector", params.sector);
  if (params?.outcome) qs.set("outcome", params.outcome);
  if (params?.theory) qs.set("theory", params.theory);
  if (params?.year_from) qs.set("year_from", String(params.year_from));
  if (params?.year_to) qs.set("year_to", String(params.year_to));
  const query = qs.toString() ? `?${qs}` : "";
  return apiFetch<CaseRecord[]>(`/cases${query}`);
}

export async function getAppStats(): Promise<AppStats> {
  return apiFetch<AppStats>("/graph/stats");
}

export async function getCase(caseId: string): Promise<CaseRecord> {
  return apiFetch<CaseRecord>(`/cases/${caseId}`);
}

export async function searchCases(q: string): Promise<CaseRecord[]> {
  return apiFetch<CaseRecord[]>(`/search?q=${encodeURIComponent(q)}`);
}

export async function getCaseGraph(caseId: string): Promise<GraphNeighbourhood> {
  return apiFetch<GraphNeighbourhood>(`/graph/case/${caseId}`);
}

export async function getIndexedCases(params?: {
  jurisdiction?: string;
  sector?: string;
  outcome?: string;
  year_from?: number;
  year_to?: number;
}): Promise<IndexedCaseDetail[]> {
  const qs = new URLSearchParams();
  if (params?.jurisdiction) qs.set("jurisdiction", params.jurisdiction);
  if (params?.sector) qs.set("sector", params.sector);
  if (params?.outcome) qs.set("outcome", params.outcome);
  if (params?.year_from) qs.set("year_from", String(params.year_from));
  if (params?.year_to) qs.set("year_to", String(params.year_to));
  const query = qs.toString() ? `?${qs}` : "";
  return apiFetch<IndexedCaseDetail[]>(`/indexed-cases${query}`);
}

export async function getIndexedCase(caseId: string): Promise<IndexedCaseDetail> {
  return apiFetch<IndexedCaseDetail>(`/indexed-cases/${caseId}`);
}

export async function searchIndexedCases(q: string): Promise<IndexedCaseDetail[]> {
  return apiFetch<IndexedCaseDetail[]>(
    `/search/all?q=${encodeURIComponent(q)}&scope=indexed`
  );
}

export async function getGraphNeighborhood(
  caseId: string,
  opts?: { depth?: number; includeIndexed?: boolean }
): Promise<GraphNeighborhoodResponse> {
  const qs = new URLSearchParams();
  if (opts?.depth !== undefined) qs.set("depth", String(opts.depth));
  if (opts?.includeIndexed !== undefined) qs.set("include_indexed", String(opts.includeIndexed));
  const query = qs.toString() ? `?${qs}` : "";
  return apiFetch<GraphNeighborhoodResponse>(`/graph/neighborhood/${caseId}${query}`);
}

export async function searchAllCases(q: string): Promise<
  { data_layer: string; case_id: string; case_name: string }[]
> {
  if (!q.trim()) return [];
  return apiFetch(`/search/all?q=${encodeURIComponent(q)}`);
}

export async function searchSemantic(
  q: string,
  topK = 10
): Promise<CaseSearchHit[]> {
  return apiFetch<CaseSearchHit[]>(
    `/search/semantic?q=${encodeURIComponent(q)}&top_k=${topK}`
  );
}

export async function getGraphMarkets(): Promise<MarketSummary[]> {
  return apiFetch<MarketSummary[]>("/graph/markets");
}

export async function getGraphMarket(
  name: string,
  semantic = false
): Promise<{ market_name: string; cases: EntityCase[]; mode: string }> {
  return apiFetch(
    `/graph/market/${encodeURIComponent(name)}?semantic=${semantic}`
  );
}

export async function getGraphTheories(): Promise<TheorySummary[]> {
  return apiFetch<TheorySummary[]>("/graph/theories");
}

export async function getGraphTheory(
  name: string,
  semantic = false
): Promise<{ theory_name: string; cases: EntityCase[]; mode: string }> {
  return apiFetch(
    `/graph/theory/${encodeURIComponent(name)}?semantic=${semantic}`
  );
}

export async function getGraphSectors(): Promise<SectorSummary[]> {
  return apiFetch<SectorSummary[]>("/graph/sectors");
}

export async function getGraphSectorMarkets(sector: string): Promise<SectorMarket[]> {
  return apiFetch<SectorMarket[]>(`/graph/sector/${encodeURIComponent(sector)}/markets`);
}

export async function getGraphSimilarMarkets(
  name: string,
  limit = 10
): Promise<SimilarMarket[]> {
  return apiFetch<SimilarMarket[]>(
    `/graph/markets/similar?name=${encodeURIComponent(name)}&limit=${limit}`
  );
}
