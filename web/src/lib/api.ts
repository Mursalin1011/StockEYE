// Server-side API client. Data changes daily, so nothing is cached here (fetch default in Next 16).
import "server-only";
import { unstable_rethrow } from "next/navigation";
import { connection } from "next/server";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string): Promise<T> {
  // Render per request: without this, `next build` prerenders data pages and calls the API at build time.
  await connection();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch (e) {
    unstable_rethrow(e); // Next's own control-flow errors (dynamic usage, redirect, notFound) aren't connection failures
    throw new ApiError(503, `Can't reach the StockEYE API at ${API_URL}. Start it with: python -m dse_screener api`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? `API ${path} failed with HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** POST JSON to the API (e.g. a trade-lab simulation). Errors carry the API's readable detail. */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  await connection();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    unstable_rethrow(e);
    throw new ApiError(503, `Can't reach the StockEYE API at ${API_URL}. Start it with: python -m dse_screener api`);
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(res.status, typeof data.detail === "string" ? data.detail : `API ${path} failed with HTTP ${res.status}`);
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
