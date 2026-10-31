"""The newest revisions in the corpus, read from node metadata alone.

"What are the latest ADs?" is answerable, and it is not answerable by the
answer writer. Everything the question asks for -- ``publication_date``,
``effective_on``, ``fr_citation``, ``is_current``, and the make and product
type of the AD -- lives on *Revision* and *AD* nodes. None of it lives in
paragraph text. So there is no span for a model to quote, and nothing for
``engine.verify.verifier`` to re-check verbatim: a quote wrapped around a date
that is held in metadata would be a fabrication dressed as a citation, not a
citation. This module therefore answers in code. There is no model call
anywhere in it, and the server routes the contract intent ``recent`` straight
past the writer and the verifier to the rows below.

Three design points worth knowing:

* **Latest means latest IN THIS CORPUS.** The corpus is a fixed harvest, not a
  live feed, so every listing carries ``corpus_earliest``, ``corpus_latest``
  and ``total_available``. A caller can then say "the newest of the 2,161
  revisions held, which run to 2026-10-27" instead of implying the engine knows
  what the Federal Register published this morning. The window is computed from
  the rows themselves, never quoted from a document that can go stale.
* **The order is total, so it is reproducible.** 20 revisions share
  2021-02-23 in the built corpus. Sorting on the date alone would leave their
  order to whatever the file happened to hold, which makes the same question
  answerable two different ways. Rows are ordered by ``publication_date``
  descending, then ``ad_number`` and ``revision_id`` ascending -- and
  ``revision_id`` is unique, so no two rows can tie.
* **It is ordered once, at load.** The server builds the index at startup from
  nodes it has already read, so answering is a slice of a tuple rather than a
  sort of the corpus. The engine's claim is speed; a per-query sort of every
  revision would be paid on every query for no reason.

A revision whose ``publication_date`` the source did not record is kept and
sorted last rather than dropped. Dropping it would make ``total_available``
quietly disagree with the corpus, and an undated revision is a gap in the
harvest, not a row that does not exist.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import ContractViolation, enum, node_types  # noqa: E402

#: How many rows a listing returns when the caller does not say.
DEFAULT_LIMIT = 10

#: What the listing's order is, as prose for the UI to print beside the rows.
#: It names the field the rows are sorted on, not just "newest first", because
#: publication is not the same event as taking effect: row one here can have an
#: ``effective_on`` later than row two's.
ORDERED_BY = "publication_date descending"

#: The contract intent this module answers. Read against ``enums.intent`` at
#: import rather than trusted as a literal: a rename in the contract must fail
#: loudly here, not silently stop routing and bring the refusal back.
INTENT = "recent"
if INTENT not in enum("intent"):
    raise ContractViolation(
        f"{INTENT!r} is not a contract intent; contract has {enum('intent')}"
    )

#: The row's keys, split by the node each one is copied from. A row is a join
#: of two nodes and nothing else: no field here is derived, inferred or
#: reformatted, so every value a caller renders is a value the Federal Register
#: index supplied.
REVISION_FIELDS = (
    "ad_number",
    "publication_date",
    "effective_on",
    "fr_citation",
    "is_current",
)
PRODUCT_FIELDS = ("make", "product_type")
ROW_FIELDS = REVISION_FIELDS + PRODUCT_FIELDS

for _ntype, _fields in (("Revision", REVISION_FIELDS), ("AD", PRODUCT_FIELDS)):
    _declared = set(node_types()[_ntype]["fields"])
    _absent = [f for f in _fields if f not in _declared]
    if _absent:
        raise ContractViolation(
            f"a listing row reads {_absent} off a {_ntype} node, and the contract "
            f"does not declare them there"
        )


def _text(value: Any) -> str | None:
    """A string field as the source wrote it, or None when it holds nothing.

    An empty string and a missing key are the same fact -- the source did not
    record this -- and a row that reported one as ``""`` would render as a blank
    cell that looks like a value.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row(
    revision: Mapping[str, Any], product: Mapping[str, Any] | None
) -> dict[str, Any]:
    """One listing row: a Revision node joined to its AD node.

    ``make`` and ``product_type`` are null when the AD node carries none, which
    is the case for 63 of the 2,117 ADs in the built corpus. Null is the honest
    report; the alternative is guessing a manufacturer from an AD number.
    """
    product = product or {}
    return {
        "ad_number": _text(revision.get("ad_number")),
        "publication_date": _text(revision.get("publication_date")),
        "effective_on": _text(revision.get("effective_on")),
        "fr_citation": _text(revision.get("fr_citation")),
        "is_current": bool(revision.get("is_current")),
        "make": _text(product.get("make")),
        "product_type": _text(product.get("product_type")),
    }


@dataclass(frozen=True)
class Listing:
    """The answer to "what is newest", with the window it is newest within."""

    rows: tuple[dict[str, Any], ...]
    ordered_by: str
    corpus_earliest: str | None
    corpus_latest: str | None
    total_available: int
    #: What the rows were narrowed to, in prose, or None for the whole corpus.
    #: It travels with the answer because "the 10 newest" and "the 10 newest of
    #: the 212 published in 2025" are different claims, and the reader cannot
    #: tell them apart from the rows alone.
    filter_label: str | None = None

    def sse_payload(self, stage_ms: float) -> dict[str, Any]:
        """The contract's ``listing`` payload, named by this object itself.

        The payload is built here rather than assembled at the call site for
        the same reason a retrieval hit builds its own: a shape put together
        field by field in the server is a shape that can drift from the
        contract one key at a time.
        """
        return {
            "rows": [dict(row) for row in self.rows],
            "filter": self.filter_label,
            "ordered_by": self.ordered_by,
            "corpus_earliest": self.corpus_earliest,
            "corpus_latest": self.corpus_latest,
            "total_available": self.total_available,
            "stage_ms": stage_ms,
        }


@dataclass(frozen=True)
class RecentIndex:
    """Every revision in the corpus, ordered newest first, once.

    Built at startup. ``latest`` is a slice, so the cost of answering does not
    grow with the corpus.
    """

    rows: tuple[dict[str, Any], ...]
    corpus_earliest: str | None
    corpus_latest: str | None

    @property
    def total_available(self) -> int:
        """How many revisions the listing could have drawn from.

        The count the UI needs to say "10 of 2,161", so it is the number of
        revisions held, not the number returned.
        """
        return len(self.rows)

    def latest(self, limit: int = DEFAULT_LIMIT) -> Listing:
        """The ``limit`` most recently published revisions.

        A limit of 0 or less returns no rows and still reports the window: an
        empty listing with a real corpus range says "nothing was asked for",
        where an empty listing with no range would read as "nothing is held".
        """
        rows = self.rows[: max(0, limit)]
        return Listing(
            rows=rows,
            ordered_by=ORDERED_BY,
            corpus_earliest=self.corpus_earliest,
            corpus_latest=self.corpus_latest,
            total_available=self.total_available,
        )

    def published_in(self, year: str, limit: int = DEFAULT_LIMIT) -> Listing:
        """The ``limit`` newest revisions published in ``year``.

        ``total_available`` counts the matches, not the corpus, because that is
        what the reader is being shown the head of. The corpus window still
        travels, so a year outside it returns no rows next to the range that
        explains why -- which is an answer, where a bare empty list would read
        as "no directives were published that year".

        The rows are already ordered, so filtering preserves that order and the
        slice stays the head of the match set.
        """
        matched = tuple(
            row for row in self.rows if str(row.get("publication_date") or "").startswith(f"{year}-")
        )
        return Listing(
            rows=matched[: max(0, limit)],
            ordered_by=ORDERED_BY,
            corpus_earliest=self.corpus_earliest,
            corpus_latest=self.corpus_latest,
            total_available=len(matched),
            filter_label=f"published in {year}",
        )

    # ------------------------------------------------------------- building

    @classmethod
    def build(
        cls,
        revisions: Iterable[Mapping[str, Any]],
        products: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> RecentIndex:
        """Order the revisions once, joining each to its AD node.

        ``revisions`` are Revision node records and ``products`` maps an
        ``ad_number`` to its AD node. Both come from nodes the caller has
        already loaded -- see ``ad_products`` and ``from_ad_graph`` -- so
        building this index re-reads nothing from disk.
        """
        products = products or {}
        records = list(revisions)
        # Two stable sorts, not one compound key: the ties have to break
        # ascending while the dates run descending, and Python's sort is
        # stable, so the second pass keeps the first pass's order within each
        # date. revision_id is unique, so the result is a total order.
        records.sort(
            key=lambda r: (
                str(r.get("ad_number") or ""),
                str(r.get("revision_id") or ""),
            )
        )
        records.sort(key=lambda r: str(r.get("publication_date") or ""), reverse=True)

        dates = sorted(
            {d for d in (_text(r.get("publication_date")) for r in records) if d}
        )
        return cls(
            rows=tuple(
                _row(r, products.get(str(r.get("ad_number") or ""))) for r in records
            ),
            corpus_earliest=dates[0] if dates else None,
            corpus_latest=dates[-1] if dates else None,
        )

    @classmethod
    def from_ad_graph(cls, ad_graph: Any) -> RecentIndex:
        """Build from an ``engine.graph.loader.ADGraph``.

        The standalone route, for the CLI below and for a check against the
        built corpus. The service does not use it: at startup it already holds
        the Revision records and the AD nodes, and loading the whole graph a
        second time to re-read them would be slower for no new information.
        """
        revisions = [ad_graph.attrs(r) for r in ad_graph.nodes_of_type("Revision")]
        return cls.build(revisions, ad_products(ad_graph.graph))


def ad_products(graph: Any) -> dict[str, dict[str, Any]]:
    """``{ad_number: AD node}`` from any loaded graph.

    Duck-typed on ``.nodes(data=True)`` so the retrieval corpus's graph and the
    general ``ADGraph`` both work: each carries ``make`` and ``product_type``
    on its AD nodes, and neither is re-read from disk here.
    """
    return {
        str(node): dict(data)
        for node, data in graph.nodes(data=True)
        if data.get("ntype") == "AD"
    }


def is_recent_intent(plan: Any) -> bool:
    """True only when the plan asks what is newest in the corpus as a whole.

    Planning is advisory and returns ``None`` when there is no API key or the
    budget cap is reached. ``None`` is not a question about recency, so it is
    not routed here: the caller's behaviour without a plan must be exactly what
    it was before this module existed, and nothing here second-guesses a
    missing plan from the question's wording.

    The intent alone is not quite enough. A question that names a directive, a
    docket or an aircraft is a question about that subject, whatever label the
    classifier put on it -- "the latest revision of AD 2026-21-07" is answered
    from that AD's revisions, not from a table of the whole corpus. Those
    fields are the plan's own structured output, so the check is on what the
    planner extracted and never on the wording. ``topic`` is deliberately not
    one of them: the planner fills it with the user's own phrase ("latest ADs")
    for exactly the question this path exists to answer.
    """
    if plan is None or getattr(plan, "intent", None) != INTENT:
        return False
    if getattr(plan, "ad_number", None) or getattr(plan, "docket_id", None):
        return False
    return not any((getattr(plan, "aircraft", None) or {}).values())


def main(argv: list[str] | None = None) -> int:
    """Print the newest rows in the built corpus, with the window they sit in."""
    import argparse
    import json

    from engine.graph.loader import load_graph

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)

    listing = RecentIndex.from_ad_graph(load_graph()).latest(args.limit)
    print(
        f"{len(listing.rows)} of {listing.total_available} revisions, "
        f"{listing.ordered_by}; corpus runs "
        f"{listing.corpus_earliest} to {listing.corpus_latest}"
    )
    for row in listing.rows:
        print(json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
