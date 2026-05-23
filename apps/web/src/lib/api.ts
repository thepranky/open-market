import type { CaseRecord, GraphNeighbourhood } from "./types";

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
}): Promise<CaseRecord[]> {
  const qs = new URLSearchParams();
  if (params?.jurisdiction) qs.set("jurisdiction", params.jurisdiction);
  if (params?.sector) qs.set("sector", params.sector);
  if (params?.outcome) qs.set("outcome", params.outcome);
  const query = qs.toString() ? `?${qs}` : "";
  return apiFetch<CaseRecord[]>(`/cases${query}`);
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
