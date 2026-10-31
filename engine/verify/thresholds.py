"""Every tuned number in the answer path, in one place, with its status.

STATUS, STATED PLAINLY: the values below are REASONED DEFAULTS, not measured
ones. No sweep has been run against a labelled set yet. An earlier version of
this file claimed each number came from a sweep over 420 labelled pairs,
reproducible with ``python3 -m engine.retrieval.evaluate --all`` against
``engine/retrieval/fixtures/queries.json`` -- neither that module nor that
fixture exists, and the sweep never happened.

That claim is exactly the failure this project exists to argue against: an
unmeasured number presented as a measured one. The reasoning for each default
is kept below because the reasoning is real; only the evidence claims were not.

Validating these is the job of the eval harness in ``eval/``. Until it has run,
any report must describe these as untuned defaults.
"""

from __future__ import annotations

#: Minimum share of a sentence's content terms that must appear in the span it
#: cites, or the sentence is dropped.
#:
#: UNTUNED DEFAULT. The intended selection rule, once a labelled set exists, is
#: the largest value whose false-drop rate on supported sentences stays <= 5%:
#: a dropped true sentence costs a visible gap in the answer, while a kept false
#: sentence is a wrong answer in a safety domain, so the asymmetry is deliberate
#: but bounded. 0.50 is a midpoint guess pending that measurement.
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
#: The fused RRF score is NOT used for this, and that part IS reasoned from
#: how RRF works: it is rank-based, so it saturates at its maximum whenever both
#: arms agree on a top-1 however poor that top-1 is. Cosine is absolute and
#: comparable across queries, so it is the right signal for an absolute cutoff.
#:
#: UNTUNED DEFAULT. Selecting it properly needs a labelled should-answer vs
#: should-refuse set, and both the false-refusal and false-answer rate at the
#: chosen value must be reported together -- a threshold quoted with only one
#: of those two numbers is not evidence. eval/ is where that happens.
NO_EVIDENCE_COSINE_MIN = 0.30
