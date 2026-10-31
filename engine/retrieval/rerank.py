"""Cross-encoder reranking over the fused (RRF) candidate window.

A bi-encoder embeds query and paragraph separately; a cross-encoder reads them
together and scores the pair, which is slower but sharper. It is used here as a
*second pass only*: the graph filter and RRF decide which paragraphs are
candidates, the cross-encoder reorders the top ``RERANK_WINDOW`` of them.

Properties this module guarantees, each covered by tests/test_rerank.py:

* It only permutes the candidates it is given. It cannot introduce a paragraph
  the graph filter excluded, and (via ``select_top``) it cannot push out the
  last paragraph of an AD the query named.
* The model is loaded once per process. A failed load is cached too, so a
  laptop with no network pays the download timeout once, not on every query.
* Failure never raises into retrieval. ``rerank_candidates`` returns a
  ``RerankOutcome`` whose ``applied`` is False and whose ``reason`` says why;
  the caller keeps the RRF order and reports that reason on the result.
* Identical input gives identical order: ties on the model score fall back to
  the incoming RRF position.

Whether this is *on* by default is decided by measurement, not assumption: see
``docs/reranking.md`` and ``RERANK_DEFAULT`` in ``engine/retrieval/search.py``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Sequence

#: Pinned by name, like the embedding model, so results reproduce across machines.
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
#: Candidates scored per query. Deeper than the 8 returned so a paragraph the
#: fusion ranked 9th-24th can still reach the top.
RERANK_WINDOW = 24
#: Truncation, in tokens, for a (query, paragraph) pair. The model's own limit.
RERANK_MAX_LENGTH = 512

log = logging.getLogger(__name__)

_lock = threading.Lock()
_model: object | None = None
#: Set when a load failed; subsequent calls fail fast with the same reason.
_load_failure: str | None = None
_warned: set[str] = set()


class RerankUnavailable(RuntimeError):
    """The cross-encoder could not be loaded or run. The caller degrades."""


@dataclass(frozen=True)
class RerankOutcome:
    """What a rerank attempt did. ``order`` indexes into the input candidates."""

    order: list[int]
    scores: list[float | None]
    applied: bool
    reason: str | None = None


def reset_for_tests() -> None:
    """Forget the cached model and cached failure."""
    global _model, _load_failure
    with _lock:
        _model = None
        _load_failure = None
        _warned.clear()


def _load_model():
    """The CrossEncoder, loaded once. Raises ``RerankUnavailable`` on failure."""
    global _model, _load_failure
    with _lock:
        if _model is not None:
            return _model
        if _load_failure is not None:
            raise RerankUnavailable(_load_failure)
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            _load_failure = f"sentence-transformers is not importable: {exc}"
            raise RerankUnavailable(_load_failure) from exc
        try:
            _model = CrossEncoder(RERANK_MODEL, max_length=RERANK_MAX_LENGTH)
        except (OSError, ValueError, RuntimeError) as exc:
            _load_failure = (
                f"cannot load {RERANK_MODEL}: {type(exc).__name__}: {exc}. It is "
                f"downloaded on first use; with no network retrieval keeps the "
                f"RRF order."
            )
            raise RerankUnavailable(_load_failure) from exc
        return _model


def warm_up() -> str | None:
    """Load the model now (e.g. at server start). Returns the failure reason, if any."""
    try:
        _load_model()
    except RerankUnavailable as exc:
        _warn_once(str(exc))
        return str(exc)
    return None


def _warn_once(reason: str) -> None:
    if reason not in _warned:
        _warned.add(reason)
        log.warning("reranking disabled for this request, using RRF order: %s", reason)


def score_pairs(query: str, texts: Sequence[str]) -> list[float]:
    """Cross-encoder relevance logits, one per text. Raises ``RerankUnavailable``."""
    model = _load_model()
    try:
        raw = model.predict(  # type: ignore[attr-defined]
            [(query, t) for t in texts], show_progress_bar=False
        )
    except (RuntimeError, ValueError, OSError) as exc:
        raise RerankUnavailable(f"{RERANK_MODEL} failed while scoring: {exc}") from exc
    scores = [float(s) for s in raw]
    if len(scores) != len(texts):
        raise RerankUnavailable(
            f"{RERANK_MODEL} returned {len(scores)} scores for {len(texts)} texts"
        )
    return scores


def rerank_candidates(
    query: str,
    texts: Sequence[str],
    *,
    scorer: Callable[[str, Sequence[str]], list[float]] | None = None,
) -> RerankOutcome:
    """Order ``texts`` (already in RRF order) by cross-encoder score, best first.

    Never raises for a model problem: on failure the identity order comes back
    with ``applied=False`` and the reason. ``scorer`` is injectable for tests.
    """
    identity = list(range(len(texts)))
    if len(texts) < 2:
        return RerankOutcome(identity, [None] * len(texts), False, "fewer than 2 candidates")
    try:
        scores = (scorer or score_pairs)(query, texts)
    except RerankUnavailable as exc:
        _warn_once(str(exc))
        return RerankOutcome(identity, [None] * len(texts), False, str(exc))
    # Python's sort is stable: equal scores keep their incoming RRF position.
    order = sorted(identity, key=lambda i: -scores[i])
    return RerankOutcome(order, [scores[i] for i in identity], True, None)


def select_top(
    order: Sequence[int],
    k: int,
    required_groups: Sequence[Sequence[int]] = (),
) -> list[int]:
    """The first ``k`` of ``order``, keeping one member of every required group.

    A required group is the set of candidate positions belonging to an AD the
    query named. If reranking would leave a group with no representative in the
    top ``k`` (although it had one before reranking), its best-ranked member
    replaces the lowest-ranked non-protected result. Groups with no member in
    ``order`` are ignored: nothing to protect.
    """
    chosen = list(order[:k])
    protected: set[int] = set()
    for group in required_groups:
        members = set(group)
        present = [i for i in chosen if i in members]
        if present:
            protected.add(present[0])
            continue
        best = next((i for i in order if i in members), None)
        if best is None:
            continue
        victim = next((i for i in reversed(chosen) if i not in protected), None)
        if victim is None:
            continue
        chosen[chosen.index(victim)] = best
        protected.add(best)
    return sorted(chosen, key=list(order).index)
