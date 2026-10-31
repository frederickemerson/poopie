/**
 * Says, where the answer is actually read, that a run came from a recorded
 * scenario rather than from the engine.
 *
 * The recorded scenarios in lib/scenarios are hand-authored fixtures: they
 * replay fixed frames to demonstrate one behaviour each, and they were written
 * against an earlier state of the corpus. So the same question can produce
 * different output in the two modes, and the recorded one is not a prediction
 * of what the engine would now say.
 *
 * The toolbar already names the source, but a toolbar is not where an answer
 * is read, and a small pressed-state button is exactly the kind of indicator a
 * screenshot or a screen recording drops. For an engine whose whole claim is
 * that nothing reaches the screen unverified, "this did not come from the
 * engine" has to be stated next to the thing it is true of.
 */
export function ReplayNotice() {
  return (
    <div
      role="status"
      className="shrink-0 border-b border-accent bg-accent-dim px-4 py-2"
    >
      <div className="mx-auto flex w-full max-w-[74ch] flex-wrap items-baseline gap-x-2.5 gap-y-1 lg:px-4">
        <span className="t-label text-ink">recorded scenario</span>
        <span className="t-caption text-ink-2">
          These frames are a hand-written fixture, not this engine&rsquo;s answer to your
          question. Switch the source to <span className="t-mono">live engine</span> to ask it
          for real.
        </span>
      </div>
    </div>
  );
}
