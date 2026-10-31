"""The evaluation harness: a labelled question set, two arms, published numbers.

Four modules, deliberately separated by what they are allowed to know:

* ``questions``  -- the labelled set, generated from the built corpus.
* ``baseline``   -- the strawman arm (top-8 cosine, no machinery) plus the one
  answer writer both arms share, so neither gets a better prompt.
* ``metrics``    -- pure functions over recorded runs. No I/O, no model, no
  engine state; everything they need is in the run record on disk.
* ``run``        -- the CLI that drives both arms and writes runs.jsonl and
  report.md.

Nothing here is allowed to change the engine's behaviour. ``run`` wires the
engine's own stage functions together exactly as ``engine.api.server`` does and
records what comes out.
"""
