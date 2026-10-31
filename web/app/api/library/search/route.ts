/**
 * POST /api/library/search - search only the documents the user loaded.
 *
 * A separate endpoint from /api/stream on purpose. "What do my own documents
 * say about X" and "what must I do about X" are different questions with
 * different standing, and the engine answers them from different scopes: this
 * one never touches the adopted-AD corpus, and /api/stream never touches a user
 * document unless it is asked to.
 */
import { ENGINE_ORIGIN, describeFetchFailure } from "@/lib/engineOrigin";

export const dynamic = "force-dynamic";

const TIMEOUT_MS = 120_000;
const MAX_QUERY_CHARS = 500;

export async function POST(request: Request): Promise<Response> {
  let payload: { readonly q?: unknown; readonly k?: unknown };
  try {
    payload = (await request.json()) as { q?: unknown; k?: unknown };
  } catch {
    return Response.json({ error: "the search body was not JSON" }, { status: 400 });
  }

  const q = typeof payload.q === "string" ? payload.q.trim().slice(0, MAX_QUERY_CHARS) : "";
  if (q === "") {
    return Response.json({ error: "no search text was submitted" }, { status: 400 });
  }
  const k = typeof payload.k === "number" && Number.isFinite(payload.k) ? payload.k : 8;

  try {
    const response = await fetch(`${ENGINE_ORIGIN}/library/search`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ q, k }),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const result = (await response.json()) as Record<string, unknown>;
    return Response.json(result, { status: response.status });
  } catch (error: unknown) {
    return Response.json({ error: describeFetchFailure(error) }, { status: 502 });
  }
}
