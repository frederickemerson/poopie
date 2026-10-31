"""The strawman arm: Claude plus top-8 vector chunks, and nothing else.

This is the arm the engine has to beat, and it only means anything if it is an
honest one. So it is built as *the same system minus the machinery*:

* same corpus, loaded through ``engine.retrieval.corpus.load_corpus``;
* same embeddings, read from the index ``engine.retrieval.index.load_index``
  already built -- nothing is re-embedded or re-indexed here;
* same k (8), and the **same answer writer**: it calls
  ``engine.api.answer.write_answer``, the identical function
  ``engine/api/server.py`` calls, with the same system prompt, the same model
  and the same code-resolved citation offsets.

Sharing the writer rather than copying it is deliberate. A second writer, or a
second prompt, would mean any difference between the arms could be a difference
in prompting instead of a difference in architecture, and the comparison would
be worth nothing. With one writer the only things the baseline lacks are the
things being measured: no entity pass, no query plan, no graph filter, no
keyword arm, no reciprocal-rank fusion, no rules engine, no verifier and no
refusal gate. It ranks paragraphs by cosine similarity alone and answers.

**It never refuses.** That is not an oversight, it is the behaviour being
measured: a naive RAG arm that declined would not be the thing the competitive
critique in docs/positioning.md describes. Nothing here inspects the answer
afterwards, so whatever the writer says is what the arm is scored on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from engine.api.answer import AnswerOutcome, write_answer
from engine.llm.client import LLMClient
from engine.retrieval.corpus import Paragraph
from engine.retrieval.index import HybridIndex

#: Same k the engine's retrieval stage uses, so the arms see equal evidence.
TOP_K = 8
#: Ledger label for this arm's writer calls, so the two arms' spend is separable
#: in data/build/cost_ledger.jsonl. The engine's own calls bill as "answer".
LABEL = "eval_baseline_answer"


class DenseArmMissing(RuntimeError):
    """The index has no embeddings, so a cosine-only baseline cannot be run."""


@dataclass(frozen=True)
class Passage:
    """One retrieved paragraph, in the shape the engine's own stages read.

    The field names are the ones ``engine.api.answer`` and
    ``engine.verify.verifier`` get off a search ``Hit`` -- ``text``,
    ``char_start``, ``char_end``, ``paragraph_id``, ``ad_number``, ``label``,
    ``heading``, ``role`` -- so a Passage can be handed to either unchanged.
    Duck-typing rather than importing ``Hit`` keeps the baseline from depending
    on the search module it is meant to do without.
    """

    paragraph_id: str
    revision_id: str
    ad_number: str | None
    label: str
    role: str
    heading: str
    text: str
    char_start: int
    char_end: int
    score: float

    @property
    def citation_id(self) -> str:
        return f"{self.paragraph_id}@{self.char_start}-{self.char_end}"

    @classmethod
    def from_paragraph(cls, paragraph: Paragraph, score: float) -> "Passage":
        return cls(
            paragraph_id=paragraph.paragraph_id,
            revision_id=paragraph.revision_id,
            ad_number=paragraph.ad_number,
            label=paragraph.label,
            role=paragraph.role,
            heading=paragraph.heading,
            text=paragraph.text,
            char_start=paragraph.char_start,
            char_end=paragraph.char_end,
            score=score,
        )

    @classmethod
    def from_hit(cls, hit: Any) -> "Passage":
        """Adapt a ``engine.retrieval.search.Hit`` or its SSE payload dict."""
        get = hit.get if isinstance(hit, dict) else lambda k, d=None: getattr(hit, k, d)
        return cls(
            paragraph_id=str(get("paragraph_id")),
            revision_id=str(get("revision_id")),
            ad_number=get("ad_number"),
            label=str(get("label") or ""),
            role=str(get("role") or ""),
            heading=str(get("heading") or ""),
            text=str(get("text") or ""),
            char_start=int(get("char_start") or 0),
            char_end=int(get("char_end") or 0),
            score=float(get("score") or 0.0),
        )


def top_k_by_cosine(index: HybridIndex, question: str, *, k: int = TOP_K) -> list[Passage]:
    """Rank the whole corpus by cosine similarity to the question. Nothing else.

    No graph filter, no entity pass, no keyword arm, no fusion. The paragraph
    embeddings are the ones already in the index; only the question is embedded.
    """
    if index.embeddings is None:
        raise DenseArmMissing(
            "the loaded index has no embeddings, so a cosine-only baseline cannot "
            "be run. Rebuild with: python3 -m engine.retrieval.index --build"
        )
    # Imported here so a caller that only needs Passage does not pay the
    # sentence-transformers import.
    from engine.retrieval.index import embed

    vector = embed([question])[0]
    scores = index.embeddings @ vector
    depth = min(k, scores.shape[0])
    top = np.argpartition(-scores, depth - 1)[:depth]
    top = top[np.argsort(-scores[top])]
    return [
        Passage.from_paragraph(index.corpus.paragraphs[int(row)], float(scores[int(row)]))
        for row in top
    ]


@dataclass
class BaselineRun:
    """One baseline turn: what it retrieved and what the writer said."""

    passages: list[Passage]
    answer: AnswerOutcome
    stage_ms: dict[str, float]
    total_ms: float

    @property
    def sentences(self) -> list[Any]:
        return list(self.answer.sentences)

    @property
    def citation_ids(self) -> list[str]:
        return [c for s in self.answer.sentences for c in s.citation_ids]


def run_baseline(
    index: HybridIndex,
    client: LLMClient,
    question: str,
    *,
    k: int = TOP_K,
    label: str = LABEL,
) -> BaselineRun:
    """Embed, take top-k by cosine, answer. The whole arm.

    ``write_answer`` never raises -- it reports a reason instead -- so a failed
    model call shows up as an arm that said nothing, with the reason recorded,
    rather than as an exception that skips the question.
    """
    started = time.perf_counter()
    t0 = time.perf_counter()
    passages = top_k_by_cosine(index, question, k=k)
    retrieval_ms = (time.perf_counter() - t0) * 1000.0
    answer = write_answer(client, question, list(passages), label=label)
    return BaselineRun(
        passages=passages,
        answer=answer,
        stage_ms={"retrieval": retrieval_ms, "answer": answer.stage_ms},
        total_ms=(time.perf_counter() - started) * 1000.0,
    )
