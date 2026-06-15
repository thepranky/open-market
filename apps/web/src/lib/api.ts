import type {
  AppStats,
  CaseRecord,
  CaseSearchHit,
  EntityCase,
  GraphNeighbourhood,
  GraphNeighborhoodResponse,
  IndexedCaseDetail,
  JurisdictionRule,
  JurisdictionSummary,
  MarketSummary,
  ScreeningRequest,
  ScreeningResult,
  SectorSummary,
  SectorMarket,
  SimilarMarket,
  TheorySummary,
} from "./types";

/**
 * Server-side fetches run inside the Docker network and must use the
 * internal service name (API_INTERNAL_URL = http://api:8000).
 * Browser fetches use the host-visible URL (NEXT_PUBLIC_API_URL = http://localhost:8000).
 * typeof window is the standard Next.js guard for server vs browser.
 */
function getBaseUrl(): string {
  if (typeof window === "undefined") {
    // Server-side (Docker container or Node.js)
    return process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  }
  // Browser
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

async function apiFetch<T>(path: string): Promise<T> {
  const baseUrl = getBaseUrl();
  const url = `${baseUrl}${path}`;
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (err) {
    throw new Error(`Could not reach API at ${url}: ${err instanceof Error ? err.message : err}`);
  }
  if (!res.ok) {
    throw new Error(`API ${res.status} at ${url}`);
  }
  return res.json() as Promise<T>;
}

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

// ── Semantic search ──────────────────────────────────────────────────────────

// ── Jurisdiction threshold endpoints ─────────────────────────────────────────

export async function getJurisdictions(): Promise<JurisdictionSummary[]> {
  return apiFetch<JurisdictionSummary[]>("/jurisdictions/");
}

export async function getJurisdiction(id: string): Promise<JurisdictionRule> {
  return apiFetch<JurisdictionRule>(`/jurisdictions/${id}`);
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const baseUrl = getBaseUrl();
  const url = `${baseUrl}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (err) {
    throw new Error(`Could not reach API at ${url}: ${err instanceof Error ? err.message : err}`);
  }
  if (!res.ok) throw new Error(`API ${res.status} at ${url}`);
  return res.json() as Promise<T>;
}

export async function screenDeal(req: ScreeningRequest): Promise<ScreeningResult[]> {
  return apiPost<ScreeningResult[]>("/jurisdictions/screen", req);
}

export async function searchSemantic(
  q: string,
  topK = 10
): Promise<CaseSearchHit[]> {
  return apiFetch<CaseSearchHit[]>(
    `/search/semantic?q=${encodeURIComponent(q)}&top_k=${topK}`
  );
}

// ── Entity-centric graph endpoints ───────────────────────────────────────────

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

// ── Drill-down navigation graph ───────────────────────────────────────────────

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
