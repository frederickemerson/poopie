"""Hybrid search: FTS5 bm25 + dense cosine, fused with reciprocal rank fusion.

Reciprocal rank fusion rather than a weighted score sum, for one reason: bm25
and cosine are not on comparable scales, and any weighted sum of them needs two
numbers tuned per corpus (a weight and a normalisation). RRF needs neither --
it consumes only the *rank* each arm assigns, so it is scale-free and has one
constant, ``k``, which the original paper (Cormack, Clarke & Buettcher 2009)
fixes at 60 and which we have not touched. A fused score that depends on no
tuned weight is one fewer thing to overfit on a demo.

The fused score is the sum of ``1 / (k + rank)`` over the arms that returned the
paragraph; with two arms its maximum is ``2 / (k + 1)`` = 0.0328.

That maximum is reached whenever both arms happen to agree on a top-1, *however
bad that top-1 is*, so the fused score orders results and says nothing about
whether any of them answers the question. Measured on this corpus, an entirely
out-of-scope query ("MEL dispatch limit for an inoperative APU") scores the
full 0.0328. So the fused score is deliberately NOT the NO_EVIDENCE signal.
``SearchResult.top_cosine`` carries the dense arm's raw cosine for the best
fused hit -- an absolute, query-comparable number -- and that is what the
refusal layer thresholds. See docs/retrieval.md for the tuning evidence.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.retrieval.corpus import Paragraph  # noqa: E402
from engine.retrieval.entities import Entities  # noqa: E402
from engine.retrieval.graph_filter import FilterResult, filter_candidates  # noqa: E402
from engine.retrieval.index import HybridIndex, _indexed_text, embed  # noqa: E402
from engine.retrieval.rerank import (  # noqa: E402
    RERANK_WINDOW,
    rerank_candidates,
    select_top,
)

#: RRF constant from the original paper. Not a tuned parameter.
RRF_K = 60
#: How deep each arm goes before fusion. Deeper than the 8 we return so a
#: paragraph ranked well by one arm and poorly by the other can still surface.
ARM_DEPTH = 40
#: Maximum rowids to inline in an FTS5 `rowid IN (...)` intersection. Beyond
#: this the statement gets long enough that filtering in Python is cheaper.
_MAX_INLINE_ROWIDS = 900

#: Whether `search` reranks when the caller does not say. Set from the measured
#: comparison in docs/reranking.md, not from a belief that rerankers help.
RERANK_DEFAULT = False

_TOKEN = re.compile(r"[0-9a-z][0-9a-z\-/]*", re.IGNORECASE)
#: Query-side stopwords only. The index keeps everything; dropping these from
#: the *query* stops an all-stopword clause from matching the whole corpus.
_STOPWORDS = frozenset(
    """a an and are as at be been by do does for from has have how i if in into is it
    its me my of on or our that the their there this to was what when where which who
    why will with you your am can could should would tell show give""".split()
)


@dataclass(frozen=True)
class Hit:
    """One retrieved paragraph, carrying everything a citation needs."""

    paragraph_id: str
    ad_number: str | None
    revision_id: str
    label: str
    role: str
    heading: str
    text: str
    char_start: int
    char_end: int
    score: float
    keyword_rank: int | None
    dense_rank: int | None
    dense_cosine: float | None
    #: Cross-encoder logit, None when this hit was not reranked.
    rerank_score: float | None = None

    @property
    def citation_id(self) -> str:
        return f"{self.paragraph_id}@{self.char_start}-{self.char_end}"

    def as_payload(self) -> dict[str, object]:
        return {
            "paragraph_id": self.paragraph_id,
            "ad_number": self.ad_number,
            "revision_id": self.revision_id,
            "label": self.label,
            "role": self.role,
            "heading": self.heading,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "citation_id": self.citation_id,
            "score": round(self.score, 6),
            "keyword_rank": self.keyword_rank,
            "dense_rank": self.dense_rank,
            "dense_cosine": (
                None if self.dense_cosine is None else round(self.dense_cosine, 4)
            ),
            "rerank_score": (
                None if self.rerank_score is None else round(self.rerank_score, 4)
            ),
        }


@dataclass
class SearchResult:
    hits: list[Hit]
    filter_report: dict[str, object]
    arms: list[str]
    top_score: float
    #: Dense cosine of the best fused hit, 0.0 when the dense arm did not run.
    #: The absolute evidence signal; `top_score` is an ordering signal only.
    top_cosine: float = 0.0
    #: "off" (not requested), "applied", or "fallback" (requested but the model
    #: was unavailable, so hits are in RRF order). `rerank_reason` says why.
    rerank_status: str = "off"
    rerank_reason: str | None = None

    def paragraph_ids(self) -> set[str]:
        return {h.paragraph_id for h in self.hits}


def fts5_query(text: str) -> str:
    """A safe FTS5 MATCH expression: quoted tokens OR-ed together.

    Every token is wrapped in double quotes, which makes it a literal phrase and
    neutralises FTS5's own operators, so no user input can become syntax. An
    empty result means the query was all stopwords, and the caller runs the dense
    arm alone rather than issuing a MATCH that would error.
    """
    tokens: list[str] = []
    for match in _TOKEN.finditer(text):
        token = match.group(0).strip("-/").casefold()
        if len(token) < 2 or token in _STOPWORDS:
            continue
        tokens.append(token.replace('"', ""))
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens))


def _keyword_ranks(
    index: HybridIndex, query: str, candidate_rows: list[int] | None
) -> dict[int, int]:
    """row -> 1-based rank by bm25 (most negative first)."""
    match = fts5_query(query)
    if not match:
        return {}
    sql = (
        "SELECT rowid FROM paragraphs WHERE paragraphs MATCH ? "
        "{restrict} ORDER BY bm25(paragraphs) LIMIT ?"
    )
    params: list[object] = [match]
    restrict = ""
    if candidate_rows is not None and len(candidate_rows) <= _MAX_INLINE_ROWIDS:
        placeholders = ",".join("?" * len(candidate_rows))
        restrict = f"AND rowid IN ({placeholders})"
        params.extend(r + 1 for r in candidate_rows)
    params.append(ARM_DEPTH if restrict or candidate_rows is None else ARM_DEPTH * 8)
    try:
        rows = index.db.execute(sql.format(restrict=restrict), params).fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"FTS5 rejected MATCH {match!r}: {exc}") from exc

    allowed = set(candidate_rows) if candidate_rows is not None else None
    ranks: dict[int, int] = {}
    for row in rows:
        zero = int(row["rowid"]) - 1
        if allowed is not None and zero not in allowed:
            continue
        if zero not in ranks:
            ranks[zero] = len(ranks) + 1
        if len(ranks) >= ARM_DEPTH:
            break
    return ranks


def _dense_ranks(
    index: HybridIndex, query: str, candidate_rows: list[int] | None
) -> tuple[dict[int, int], dict[int, float]]:
    """row -> rank, and row -> raw cosine. Both are needed: the rank feeds RRF,
    the cosine is the only absolute match-quality number in the pipeline."""
    if index.embeddings is None:
        return {}, {}
    vector = embed([query])[0]
    rows = (
        np.asarray(candidate_rows, dtype=np.int64)
        if candidate_rows is not None
        else np.arange(index.embeddings.shape[0], dtype=np.int64)
    )
    if rows.size == 0:
        return {}, {}
    scores = index.embeddings[rows] @ vector
    depth = min(ARM_DEPTH, rows.size)
    top = np.argpartition(-scores, depth - 1)[:depth]
    top = top[np.argsort(-scores[top])]
    ranks = {int(rows[i]): rank for rank, i in enumerate(top, start=1)}
    cosines = {int(rows[i]): float(scores[i]) for i in top}
    return ranks, cosines


def _paragraph(index: HybridIndex, row: int) -> Paragraph:
    return index.corpus.paragraphs[row]


def search(
    index: HybridIndex,
    query: str,
    entities: Entities,
    *,
    k: int = 8,
    revision_scope: str = "current",
    revision_ids: list[str] | None = None,
    prefiltered: FilterResult | None = None,
    rerank: bool | None = None,
) -> SearchResult:
    """Graph filter, then both arms over the survivors, then RRF.

    ``rerank`` adds a cross-encoder pass over the top ``RERANK_WINDOW`` fused
    candidates (``None`` means ``RERANK_DEFAULT``). It only reorders paragraphs
    the filter and fusion already chose; if the model is unavailable the RRF
    order is kept and ``rerank_status`` is ``"fallback"`` with the reason.
    """
    if rerank is None:
        rerank = RERANK_DEFAULT
    result = prefiltered or filter_candidates(
        index.corpus,
        entities,
        revision_scope=revision_scope,
        revision_ids=revision_ids,
    )
    rows = [
        index.corpus.row_of[pid]
        for pid in result.paragraph_ids
        if pid in index.corpus.row_of
    ]
    if not rows:
        return SearchResult(
            hits=[],
            filter_report=result.as_report(),
            arms=[],
            top_score=0.0,
            top_cosine=0.0,
        )
    whole_corpus = len(rows) == len(index.corpus.paragraphs)
    candidate_rows = None if whole_corpus else rows

    keyword = _keyword_ranks(index, query, candidate_rows)
    dense, cosines = _dense_ranks(index, query, candidate_rows)
    arms = [name for name, got in (("keyword", keyword), ("dense", dense)) if got]

    fused: dict[int, float] = {}
    for ranks in (keyword, dense):
        for row, rank in ranks.items():
            fused[row] = fused.get(row, 0.0) + 1.0 / (RRF_K + rank)

    window = max(k, RERANK_WINDOW) if rerank else k
    ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:window]
    rerank_scores: dict[int, float] = {}
    rerank_status, rerank_reason = "off", None
    top_cosine_row = ordered[0][0] if ordered else None
    if rerank and ordered:
        ordered, rerank_scores, rerank_status, rerank_reason = _apply_rerank(
            index, query, entities, ordered, k
        )
    ordered = ordered[:k]
    hits = [
        Hit(
            paragraph_id=(p := _paragraph(index, row)).paragraph_id,
            ad_number=p.ad_number,
            revision_id=p.revision_id,
            label=p.label,
            role=p.role,
            heading=p.heading,
            text=p.text,
            char_start=p.char_start,
            char_end=p.char_end,
            score=score,
            keyword_rank=keyword.get(row),
            dense_rank=dense.get(row),
            dense_cosine=cosines.get(row),
            rerank_score=rerank_scores.get(row),
        )
        for row, score in ordered
    ]
    return SearchResult(
        hits=hits,
        filter_report=result.as_report(),
        arms=arms,
        top_score=hits[0].score if hits else 0.0,
        # The refusal layer's absolute signal stays anchored to the RRF winner,
        # so enabling reranking cannot move the NO_EVIDENCE threshold's meaning.
        top_cosine=cosines.get(top_cosine_row, 0.0) if hits else 0.0,
        rerank_status=rerank_status,
        rerank_reason=rerank_reason,
    )


def _apply_rerank(
    index: HybridIndex,
    query: str,
    entities: Entities,
    ordered: list[tuple[int, float]],
    k: int,
) -> tuple[list[tuple[int, float]], dict[int, float], str, str | None]:
    """Reorder the RRF window; on model failure return it untouched with a reason."""
    paragraphs = [_paragraph(index, row) for row, _ in ordered]
    outcome = rerank_candidates(query, [_indexed_text(p) for p in paragraphs])
    if not outcome.applied:
        return ordered, {}, "fallback", outcome.reason
    named = set(entities.ad_numbers)
    groups = [
        [i for i, p in enumerate(paragraphs) if p.ad_number == ad] for ad in sorted(named)
    ]
    chosen = select_top(outcome.order, k, groups)
    scores = {ordered[i][0]: s for i, s in enumerate(outcome.scores) if s is not None}
    return [ordered[i] for i in chosen], scores, "applied", None
