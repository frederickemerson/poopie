/**
 * GET /api/blast/{revision_id} - proxies the engine's GET /blast/{revision_id}.
 *
 * The engine runs the rules engine over every aircraft in the built fleet for
 * one revision and returns the counts plus a cell per aircraft. Nothing is
 * recomputed here: the grid and the proof tree must never be able to disagree,
 * and the only way to guarantee that is for both to come from the same decide().
 */
import { ENGINE_ORIGIN, describeFetchFailure } from "@/lib/engineOrigin";

export const dynamic = "force-dynamic";

const BLAST_TIMEOUT_MS = 30_000;

export async function GET(
  _request: Request,
  context: { params: Promise<{ revision_id: string }> },
): Promise<Response> {
  const { revision_id } = await context.params;
  if (!revision_id) {
    return Response.json({ error: "no revision_id given" }, { status: 400 });
  }

  try {
    const response = await fetch(`${ENGINE_ORIGIN}/blast/${encodeURIComponent(revision_id)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(BLAST_TIMEOUT_MS),
    });
    if (!response.ok) {
      return Response.json(
        { error: `engine returned ${response.status} ${response.statusText}` },
        { status: 502 },
      );
    }
    return Response.json(await response.json());
  } catch (error: unknown) {
    return Response.json({ error: describeFetchFailure(error) }, { status: 502 });
  }
}
