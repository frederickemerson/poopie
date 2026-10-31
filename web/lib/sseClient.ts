/**
 * The real SSE client. Pointed at the Next route handler that replays the mock
 * stream; change ENGINE_STREAM_URL (or set NEXT_PUBLIC_ENGINE_STREAM_URL) to the
 * FastAPI endpoint and nothing else moves.
 */
import { SSE_PAYLOAD_KEYS, type SseEventName } from "./contract";
import type { EngineEvent } from "./events";

export const ENGINE_STREAM_URL =
  process.env.NEXT_PUBLIC_ENGINE_STREAM_URL ?? "/api/stream";

export interface StreamHandlers {
  readonly onEvent: (event: EngineEvent) => void;
  readonly onClose?: () => void;
  readonly onTransportError?: (message: string) => void;
}

const EVENT_NAMES = Object.keys(SSE_PAYLOAD_KEYS) as SseEventName[];

/**
 * Subscribe to one engine run. Returns a cancel function.
 * `query` and `scenario` are passed through as search params so the same client
 * works against the replay route and against the real engine.
 */
export function openEngineStream(
  params: { readonly query?: string; readonly scenario?: string },
  handlers: StreamHandlers,
): () => void {
  const url = new URL(ENGINE_STREAM_URL, window.location.origin);
  if (params.query) url.searchParams.set("q", params.query);
  if (params.scenario) url.searchParams.set("scenario", params.scenario);

  const source = new EventSource(url.toString());
  let closed = false;

  const close = () => {
    if (closed) return;
    closed = true;
    source.close();
    handlers.onClose?.();
  };

  for (const name of EVENT_NAMES) {
    source.addEventListener(name, (raw) => {
      const message = raw as MessageEvent<string>;
      try {
        const data = JSON.parse(message.data) as never;
        handlers.onEvent({ event: name, data } as EngineEvent);
      } catch {
        handlers.onTransportError?.(`malformed ${name} payload`);
        return;
      }
      if (name === "done" || name === "error") close();
    });
  }

  source.onerror = () => {
    if (!closed) handlers.onTransportError?.("stream transport closed unexpectedly");
    close();
  };

  return close;
}
