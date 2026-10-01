// Server-side API client. Data changes daily, so nothing is cached here (fetch default in Next 16).
import "server-only";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(503, `Can't reach the StockEYE API at ${API_URL}. Start it with: python -m dse_screener api`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? `API ${path} failed with HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** Like api(), but returns null on 404 (e.g. no saved screen yet). */
export async function apiOrNull<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
