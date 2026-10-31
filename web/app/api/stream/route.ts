/**
 * Server-Sent Events replay of the mock engine. Same wire format as the FastAPI
 * service: `event: <name>` + `data: <json>`, one frame per engine event.
 *
 *   GET /api/stream?scenario=external_source
 */
import { DEFAULT_SCENARIO_ID, pickScenario, streamMockScenario, toSsePayload } from "@/lib/mockStream";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  // An explicit scenario wins, so the dev toggle is deterministic. A free-typed
  // question with no scenario param is matched on its content instead.
  const explicit = url.searchParams.get("scenario");
  const id = explicit ?? pickScenario(url.searchParams.get("q"), DEFAULT_SCENARIO_ID).id;
  const speed = Number(url.searchParams.get("speed") ?? "1");
  const controllerAbort = new AbortController();
  request.signal.addEventListener("abort", () => controllerAbort.abort(), { once: true });

  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        controller.enqueue(encoder.encode(": engine replay\n\n"));
        for await (const event of streamMockScenario(id, {
          speed: Number.isFinite(speed) ? speed : 1,
          signal: controllerAbort.signal,
        })) {
          controller.enqueue(encoder.encode(toSsePayload(event)));
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : "replay failed";
        controller.enqueue(encoder.encode(toSsePayload({ event: "error", data: { message } })));
      } finally {
        controller.close();
      }
    },
    cancel() {
      controllerAbort.abort();
    },
  });

  return new Response(body, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
