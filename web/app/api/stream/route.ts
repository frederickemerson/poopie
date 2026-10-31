/**
 * The engine stream, as Server-Sent Events.
 *
 *   POST /api/stream   {"q": "...", "tail_number": "N845AM", "source": "engine"}
 *
 * With source "engine" (the default) this proxies POST {ENGINE_ORIGIN}/stream
 * and hands the upstream body straight back, unbuffered and untouched, so the
 * browser sees each stage the moment the engine flushes it.
 *
 * With source "mock" it replays a recorded scenario in the same wire format.
 * That path is the demo's parachute: if the engine dies on stage, one toolbar
 * click keeps the presentation running.
 *
 *   GET /api/stream?scenario=external_source   replays the mock over curl.
 */
import {
  ENGINE_COLD_START_MS,
  ENGINE_ORIGIN,
  SSE_HEADERS,
  describeFetchFailure,
  engineErrorFrame,
} from "@/lib/engineOrigin";
import { DEFAULT_SCENARIO_ID, pickScenario, streamMockScenario, toSsePayload } from "@/lib/mockStream";

export const dynamic = "force-dynamic";

interface StreamRequest {
  readonly q?: unknown;
  readonly tail_number?: unknown;
  readonly source?: unknown;
  readonly scenario?: unknown;
  readonly speed?: unknown;
}

function mockResponse(scenarioId: string, speed: number, signal: AbortSignal): Response {
  const abort = new AbortController();
  signal.addEventListener("abort", () => abort.abort(), { once: true });

  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        controller.enqueue(encoder.encode(": engine replay\n\n"));
        for await (const event of streamMockScenario(scenarioId, {
          speed: Number.isFinite(speed) ? speed : 1,
          signal: abort.signal,
        })) {
          controller.enqueue(encoder.encode(toSsePayload(event)));
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : "replay failed";
        controller.enqueue(encoder.encode(engineErrorFrame(message)));
      } finally {
        controller.close();
      }
    },
    cancel() {
      abort.abort();
    },
  });

  return new Response(body, { headers: SSE_HEADERS });
}

/** A single `error` frame, so a dead backend reads as a stated failure. */
function errorResponse(message: string): Response {
  return new Response(engineErrorFrame(message), { headers: SSE_HEADERS });
}

async function proxyToEngine(
  q: string,
  tailNumber: string | null,
  signal: AbortSignal,
): Promise<Response> {
  const timeout = AbortSignal.timeout(ENGINE_COLD_START_MS);
  let upstream: Response;
  try {
    upstream = await fetch(`${ENGINE_ORIGIN}/stream`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify({ q, tail_number: tailNumber }),
      signal: AbortSignal.any([signal, timeout]),
      cache: "no-store",
    });
  } catch (error: unknown) {
    if (signal.aborted) return new Response(null, { status: 499 });
    return errorResponse(describeFetchFailure(error));
  }

  if (!upstream.ok || upstream.body === null) {
    const detail = await upstream.text().catch(() => "");
    return errorResponse(
      `engine returned ${upstream.status} ${upstream.statusText}${detail ? `: ${detail.slice(0, 400)}` : ""}`,
    );
  }

  // Pass the upstream body through by reference: no buffering, no re-encoding.
  return new Response(upstream.body, { headers: SSE_HEADERS });
}

export async function POST(request: Request): Promise<Response> {
  let payload: StreamRequest;
  try {
    payload = (await request.json()) as StreamRequest;
  } catch {
    return errorResponse("stream request body was not JSON");
  }

  const q = typeof payload.q === "string" ? payload.q.trim() : "";
  const scenario = typeof payload.scenario === "string" ? payload.scenario : null;
  const speed = typeof payload.speed === "number" ? payload.speed : 1;

  if (payload.source === "mock") {
    const id = scenario ?? pickScenario(q, DEFAULT_SCENARIO_ID).id;
    return mockResponse(id, speed, request.signal);
  }

  if (q === "") return errorResponse("no question was submitted");

  const tailNumber = typeof payload.tail_number === "string" && payload.tail_number !== ""
    ? payload.tail_number
    : null;

  return proxyToEngine(q, tailNumber, request.signal);
}

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const explicit = url.searchParams.get("scenario");
  const id = explicit ?? pickScenario(url.searchParams.get("q"), DEFAULT_SCENARIO_ID).id;
  const speed = Number(url.searchParams.get("speed") ?? "1");
  return mockResponse(id, speed, request.signal);
}
