/**
 * Where the FastAPI engine lives, for the Next route handlers that proxy to it.
 *
 * Server-side only, and deliberately not a NEXT_PUBLIC_ variable: the browser
 * talks to this app's own /api routes, so the engine's address never has to be
 * reachable from the client or baked into the bundle.
 *
 *   cd <repo root> && uvicorn engine.api.server:app --port 8000
 */
export const ENGINE_ORIGIN = process.env.ENGINE_ORIGIN ?? "http://localhost:8000";

/** Headers that keep an SSE body flowing through the proxy unbuffered. */
export const SSE_HEADERS: Readonly<Record<string, string>> = {
  "content-type": "text/event-stream; charset=utf-8",
  "cache-control": "no-cache, no-transform",
  connection: "keep-alive",
  "x-accel-buffering": "no",
};

/**
 * The first query loads a sentence-transformer model, which takes roughly ten
 * seconds; later queries run in milliseconds. The proxy must outlast that cold
 * start, or the UI would report a hang that is really a model download.
 */
export const ENGINE_COLD_START_MS = 120_000;

export function engineErrorFrame(message: string): string {
  return `event: error\ndata: ${JSON.stringify({ message })}\n\n`;
}

export function describeFetchFailure(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error);
  return `cannot reach the engine at ${ENGINE_ORIGIN} (${detail}). Start it with: uvicorn engine.api.server:app --port 8000`;
}
