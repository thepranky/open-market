/**
 * Shared HTTP helpers for feature API modules.
 * Server-side fetches use API_INTERNAL_URL (Docker); browser uses NEXT_PUBLIC_API_URL.
 */
export function getBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export async function apiFetch<T>(path: string): Promise<T> {
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

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
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
