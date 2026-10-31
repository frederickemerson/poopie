"""Every tuned number in the answer path, in one place, with its evidence.

Each value below names the sweep that produced it and the rates measured at it.
Reproduce all of them with::

    AD_RETRIEVAL_CORPUS=fixture python3 -m engine.retrieval.evaluate --all

Nothing here was set by looking at a demo. A change to any of these must come
with a re-run of that command and an update to docs/retrieval.md.
"""

from __future__ import annotations

#: Minimum share of a sentence's content terms that must appear in the span it
#: cites, or the sentence is dropped.
#:
#: Tuned by sweeping 0.30..0.90 over 420 labelled sentence/citation pairs built
#: from the corpus (verbatim quotes, Sonnet paraphrases of real paragraphs,
#: cross-cited sentences from a different AD, and number-mutated sentences).
#: Chosen as the largest value whose false-drop rate on supported sentences is
#: still <= 5%, because in this product a dropped true sentence costs a visible
#: gap in the answer while a kept false sentence is a wrong answer in a safety
#: domain -- so the asymmetry is deliberate but bounded.
#: Measured at this value: see docs/retrieval.md "Verifier".
TERM_COVERAGE_MIN = 0.50

#: Digit-bearing terms are not averaged into coverage; every one must be present.
#: This is a rule, not a tuned threshold, and is stated here so it is visible
#: alongside the numbers it overrides.
REQUIRE_NUMERIC_SUPPORT = True

#: If fewer than this share of the writer's sentences survive verification, the
#: whole answer is converted to a refusal rather than shown thinned. A half-
#: verified answer in a safety domain reads as a complete one.
MIN_KEPT_FRACTION = 0.60

#: An answer must keep at least this many sentences to be shown at all.
MIN_KEPT_SENTENCES = 1

#: Dense-arm cosine of the best retrieved paragraph, below which the engine
#: refuses NO_EVIDENCE.
#:
#: The fused RRF score is NOT used for this: RRF is rank-based, so it saturates
#: at its maximum whenever both arms agree on a top-1 however poor that top-1
#: is, and an out-of-scope query was measured at the full 0.0328. Cosine is
#: absolute and comparable across queries.
#:
#: Tuned by sweeping over the labelled query set in
#: engine/retrieval/fixtures/queries.json (should-answer vs should-refuse).
#: Both rates at the chosen value are reported in docs/retrieval.md.
NO_EVIDENCE_COSINE_MIN = 0.30
