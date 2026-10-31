/**
 * The real SSE client.
 *
 * It POSTs to the Next route at /api/stream, which proxies straight through to
 * the FastAPI service's POST /stream. POST rather than EventSource for two
 * reasons: the engine takes a body (`q` plus an optional `tail_number`), and
 * EventSource reconnects on close, which would re-run a query every time the
 * engine finished one.
 *
 * Every frame goes through createEventNormaliser before it reaches the caller,
 * so the reducer sees the shapes declared in events.ts whichever source
 * answered.
 */
import { SSE_PAYLOAD_KEYS, type SseEventName } from "./contract";
import type { EngineSource } from "./engineSource";
import type { EngineEvent } from "./events";
import { createEventNormaliser } from "./liveWire";

export const ENGINE_STREAM_URL = process.env.NEXT_PUBLIC_ENGINE_STREAM_URL ?? "/api/stream";

export interface StreamHandlers {
  readonly onEvent: (event: EngineEvent) => void;
  readonly onClose?: () => void;
  readonly onTransportError?: (message: string) => void;
}

export interface StreamParams {
  readonly query: string;
  /** Applicability needs one aircraft; a model alone matches hundreds. */
  readonly tailNumber?: string | null;
  readonly source?: EngineSource;
  /** Mock only: which recorded scenario to replay. */
  readonly scenario?: string;
}

function isEngineEventName(name: string): name is SseEventName {
  return Object.prototype.hasOwnProperty.call(SSE_PAYLOAD_KEYS, name);
}

interface RawFrame {
  readonly name: string;
  readonly data: string;
}

/** Parse one `event:`/`data:` block. Comment-only frames (": ...") yield null. */
function parseFrame(block: string): RawFrame | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") name = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  return { name, data: data.join("\n") };
}

/**
 * Subscribe to one engine run. Returns a cancel function; calling it aborts the
 * request, which propagates through the proxy and stops the engine generator.
 */
export function openEngineStream(params: StreamParams, handlers: StreamHandlers): () => void {
  const controller = new AbortController();
  const normalise = createEventNormaliser(params.query);
  let closed = false;

  const close = () => {
    if (closed) return;
    closed = true;
    controller.abort();
    handlers.onClose?.();
  };

  const emit = (frame: RawFrame) => {
    if (!isEngineEventName(frame.name)) {
      // An event the contract does not declare is a drift signal, not something
      // to render. It is surfaced rather than dropped silently.
      handlers.onTransportError?.(`undeclared event "${frame.name}" off the wire`);
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(frame.data);
    } catch {
      handlers.onTransportError?.(`malformed ${frame.name} payload`);
      return;
    }
    handlers.onEvent(normalise(frame.name, parsed));
    if (frame.name === "done" || frame.name === "error") close();
  };

  void (async () => {
    try {
      const response = await fetch(ENGINE_STREAM_URL, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify({
          q: params.query,
          tail_number: params.tailNumber ?? null,
          source: params.source ?? "engine",
          scenario: params.scenario ?? null,
        }),
        signal: controller.signal,
        cache: "no-store",
      });

      if (!response.ok || response.body === null) {
        handlers.onTransportError?.(
          `stream request failed: ${response.status} ${response.statusText}`.trim(),
        );
        close();
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let split = buffer.indexOf("\n\n");
        while (split >= 0) {
          const frame = parseFrame(buffer.slice(0, split));
          buffer = buffer.slice(split + 2);
          if (frame) emit(frame);
          split = buffer.indexOf("\n\n");
        }
      }

      const tail = parseFrame(buffer);
      if (tail) emit(tail);
      close();
    } catch (error: unknown) {
      if (closed || controller.signal.aborted) return;
      const message = error instanceof Error ? error.message : "stream transport failed";
      handlers.onTransportError?.(message);
      close();
    }
  })();

  return close;
}
