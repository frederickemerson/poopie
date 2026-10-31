/**
 * GET /api/health - proxies the engine's own GET /health.
 *
 * Always answers 200, with `reachable` saying whether the engine replied. A
 * failed probe is a fact to display, not an error to throw: on stage the
 * difference between "the corpus never loaded" and "nothing is listening on
 * 8000" is the difference between a fix and a stall.
 */
import { ENGINE_ORIGIN, describeFetchFailure } from "@/lib/engineOrigin";

export const dynamic = "force-dynamic";

const PROBE_TIMEOUT_MS = 4_000;

export async function GET(): Promise<Response> {
  try {
    const response = await fetch(`${ENGINE_ORIGIN}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    if (!response.ok) {
      return Response.json({
        reachable: false,
        origin: ENGINE_ORIGIN,
        error: `engine returned ${response.status} ${response.statusText}`,
      });
    }
    const payload = (await response.json()) as Record<string, unknown>;
    return Response.json({ reachable: true, origin: ENGINE_ORIGIN, ...payload });
  } catch (error: unknown) {
    return Response.json({
      reachable: false,
      origin: ENGINE_ORIGIN,
      error: describeFetchFailure(error),
    });
  }
}
