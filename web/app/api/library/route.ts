/**
 * GET  /api/library            - the documents the user has loaded
 * POST /api/library            - load one document
 *
 * Both proxy the engine. The engine is the only thing that validates an upload:
 * this route adds a size ceiling so an oversized body is rejected at the edge
 * rather than forwarded, and otherwise passes the engine's own answer through,
 * including its refusals. A refusal from the engine is a fact to show the user,
 * not an error to rewrite here -- it names what is wrong with the document.
 */
import { ENGINE_ORIGIN, describeFetchFailure } from "@/lib/engineOrigin";

export const dynamic = "force-dynamic";

/** Must stay at or below the engine's own ceiling; the engine re-checks. */
const MAX_BODY_BYTES = 2 * 1024 * 1024 + 64 * 1024;
const LIST_TIMEOUT_MS = 8_000;
/** An upload embeds its paragraphs, which loads the model on a cold engine. */
const UPLOAD_TIMEOUT_MS = 120_000;

export async function GET(): Promise<Response> {
  try {
    const response = await fetch(`${ENGINE_ORIGIN}/library`, {
      cache: "no-store",
      signal: AbortSignal.timeout(LIST_TIMEOUT_MS),
    });
    const payload = (await response.json()) as Record<string, unknown>;
    return Response.json({ reachable: true, ...payload }, { status: response.status });
  } catch (error: unknown) {
    return Response.json({
      reachable: false,
      documents: [],
      error: describeFetchFailure(error),
    });
  }
}

export async function POST(request: Request): Promise<Response> {
  const declared = request.headers.get("content-length");
  if (declared !== null && Number(declared) > MAX_BODY_BYTES) {
    return Response.json(
      { error: `the document is too large (${declared} bytes; limit ${MAX_BODY_BYTES})` },
      { status: 413 },
    );
  }

  const body = await request.text();
  if (body.length > MAX_BODY_BYTES) {
    return Response.json(
      { error: `the document is too large (${body.length} bytes; limit ${MAX_BODY_BYTES})` },
      { status: 413 },
    );
  }

  try {
    const response = await fetch(`${ENGINE_ORIGIN}/library/documents`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    });
    const payload = (await response.json()) as Record<string, unknown>;
    return Response.json(payload, { status: response.status });
  } catch (error: unknown) {
    return Response.json({ error: describeFetchFailure(error) }, { status: 502 });
  }
}
