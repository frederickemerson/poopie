"""The evaluation harness: a labelled question set, two arms, published numbers.

Five modules, deliberately separated by what they are allowed to know:

* ``questions``  -- the labelled set, generated from the built corpus.
* ``baseline``   -- the strawman arm: top-8 cosine, no machinery, and the
  engine's own ``write_answer``, so neither arm gets a better prompt.
* ``metrics``    -- pure functions over recorded runs. No I/O, no model, no
  engine state; everything they need is in the run record on disk.
* ``report``     -- pure rendering of those records into markdown.
* ``run``        -- the CLI that drives both arms and writes runs.jsonl,
  metrics.json and report.md.

Nothing here is allowed to change the engine's behaviour. ``run`` drives
``engine.api.server._stream`` and records what comes out of it.
"""
