"""The listing path: what "latest" is allowed to claim, and where it comes from.

Asking "what are the latest ADs?" used to be refused OUT_OF_SCOPE, on the
grounds that the question names no directive, no docket and no aircraft. It
names none by nature -- it is a question about the index, and the index answers
it exactly. These tests pin the two halves of answering it honestly.

**The rows are metadata, not prose.** Publication dates and Federal Register
citations live on Revision and AD nodes, not inside paragraph text. So this
path runs no answer writer and no verifier: there is no span to quote, and a
quote invented to satisfy the citation format would be a fabrication. The test
below asserts the absence of those events, because "we skipped the verifier" is
only safe while there is also no prose to verify.

**"Latest" means latest in THIS corpus.** The corpus is a fixed harvest ending
2026-10-27, not a live feed. Every listing therefore carries the window it is
newest within, and those three numbers are tested against the corpus they
describe rather than against constants, so a re-ingest cannot leave the UI
quoting a range the engine no longer holds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import contract, sse_events, validate_event  # noqa: E402
from engine.graph.recent import (  # noqa: E402
    DEFAULT_LIMIT,
    INTENT,
    ROW_FIELDS,
    RecentIndex,
    is_recent_intent,
)
from engine.retrieval.plan import QueryPlan  # noqa: E402

# Three ADs published on two days, deliberately out of order in the source and
# deliberately sharing a date: the shared date is where an unstable sort shows.
REVISIONS = [
    {
        "revision_id": "26-02000",
        "ad_number": "2026-21-12",
        "publication_date": "2026-10-27",
        "effective_on": "2026-12-01",
        "fr_citation": "91 FR 67442",
        "is_current": True,
    },
    {
        "revision_id": "24-01000",
        "ad_number": "2024-05-01",
        "publication_date": "2024-03-11",
        "effective_on": "2024-04-15",
        "fr_citation": "89 FR 17001",
        "is_current": False,
        "superseded_by": "26-02000",
    },
    {
        "revision_id": "26-01999",
        "ad_number": "2026-21-07",
        "publication_date": "2026-10-27",
        "effective_on": "2026-12-01",
        "fr_citation": "91 FR 67452",
        "is_current": True,
    },
]

PRODUCTS = {
    "2026-21-12": {"ntype": "AD", "make": "Boeing", "product_type": "Aircraft"},
    "2026-21-07": {"ntype": "AD", "make": "Boeing", "product_type": "Aircraft"},
    # A real shape in the built corpus: 63 of 2,117 ADs record no product type
    # and 2 record no make.
    "2024-05-01": {"ntype": "AD", "make": "", "product_type": None},
}


def index() -> RecentIndex:
    return RecentIndex.build(REVISIONS, PRODUCTS)


# --------------------------------------------------------------- the ordering


def test_the_listing_is_ordered_by_publication_date_newest_first():
    # Arrange
    listing = index().latest()

    # Act
    dates = [row["publication_date"] for row in listing.rows]

    # Assert
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-10-27"
    # The order is stated beside the rows, naming the field it sorted on.
    # Publication is not the same event as taking effect, and a reader who
    # assumes "newest first" means "soonest deadline first" is wrong.
    assert "publication_date" in listing.ordered_by
    assert "descending" in listing.ordered_by


def test_revisions_published_the_same_day_come_back_in_one_fixed_order():
    """A date is not a unique key, so the date alone cannot settle the order.

    20 revisions share 2021-02-23 in the built corpus. Sorting on the date
    alone leaves their order to whatever the source file happened to hold,
    which makes one question answerable two different ways. The tie breaks on
    ad_number then revision_id, and revision_id is unique, so there are no ties
    left to break.
    """
    # Arrange: the same revisions, in two different source orders.
    forwards = RecentIndex.build(REVISIONS, PRODUCTS).latest()
    backwards = RecentIndex.build(list(reversed(REVISIONS)), PRODUCTS).latest()

    # Assert
    assert forwards.rows == backwards.rows
    same_day = [r["ad_number"] for r in forwards.rows if r["publication_date"] == "2026-10-27"]
    assert same_day == ["2026-21-07", "2026-21-12"]


# ------------------------------------------------------------- the honest window


def test_the_window_reported_is_the_corpus_the_rows_came_from():
    """"Latest" is latest in this corpus, and the corpus has to say so.

    The engine holds a fixed harvest. Without the window, ten rows from 2026
    read as "these are the newest ADs in existence", which the engine cannot
    know. corpus_earliest, corpus_latest and total_available are what let a
    caller say "the newest 2 of 3 held, which run to 2026-10-27" instead.
    """
    listing = index().latest(2)

    assert listing.corpus_earliest == "2024-03-11"
    assert listing.corpus_latest == "2026-10-27"
    # Not the number returned: the number it could have drawn from.
    assert listing.total_available == len(REVISIONS)
    assert len(listing.rows) == 2


def test_an_empty_corpus_reports_no_window_rather_than_a_made_up_one():
    listing = RecentIndex.build([], {}).latest()

    assert listing.rows == ()
    assert listing.total_available == 0
    assert listing.corpus_earliest is None and listing.corpus_latest is None


def test_the_default_listing_length_is_fixed_and_small():
    """Ten is the default because the answer is read, not scrolled."""
    assert DEFAULT_LIMIT == 10
    assert len(RecentIndex.build(REVISIONS * 10, PRODUCTS).latest().rows) == DEFAULT_LIMIT


# ----------------------------------------------------------------- the rows


def test_every_row_carries_exactly_the_keys_the_contract_declares():
    """The row shape is the interface the UI builds its table from.

    One extra key here is a column nothing renders; one missing key is a blank
    cell. Both are pinned, and the field names are checked against the node
    types they are copied from so a row cannot carry a field the contract does
    not declare on the node it came from.
    """
    rows = index().latest().rows

    for row in rows:
        assert set(row) == set(ROW_FIELDS), f"row shape drifted: {sorted(row)}"

    revision_fields = set(contract()["node_types"]["Revision"]["fields"])
    ad_fields = set(contract()["node_types"]["AD"]["fields"])
    for field in ROW_FIELDS:
        assert field in revision_fields | ad_fields, (
            f"{field!r} is on no contract node, so no node can supply it"
        )


def test_a_row_copies_its_values_off_the_nodes_and_derives_nothing():
    newest = index().latest().rows[0]

    assert newest == {
        "ad_number": "2026-21-07",
        "publication_date": "2026-10-27",
        "effective_on": "2026-12-01",
        "fr_citation": "91 FR 67452",
        "is_current": True,
        "make": "Boeing",
        "product_type": "Aircraft",
    }


def test_a_product_the_ad_node_does_not_record_is_null_not_a_guess():
    """An absent make is reported absent. Nothing infers it from an AD number."""
    rows = {row["ad_number"]: row for row in index().latest().rows}
    unlabelled = rows["2024-05-01"]

    assert unlabelled["make"] is None
    assert unlabelled["product_type"] is None
    # And a superseded revision still says so, rather than being hidden: it was
    # published, and the question was what was published.
    assert unlabelled["is_current"] is False


# ---------------------------------------------------------------- the event


def test_the_listing_payload_is_the_shape_the_contract_declares():
    payload = index().latest().sse_payload(stage_ms=0.4)

    # Raises ContractViolation on a missing or undeclared key.
    validate_event("listing", payload)
    assert set(payload) == set(sse_events()["listing"]["payload"])
    # It must survive the trip the server sends it on.
    assert json.loads(json.dumps(payload))["rows"][0]["ad_number"] == "2026-21-07"


def stream_events() -> list[tuple[str, dict]]:
    """The server's listing path, as (event name, payload) pairs."""
    import time

    from engine.api.server import _recent_events

    chunks = "".join(_recent_events(index(), time.perf_counter(), {})).split("\n\n")
    out = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        head, _, body = chunk.partition("\n")
        out.append(
            (head.removeprefix("event: "), json.loads(body.removeprefix("data: ")))
        )
    return out


def test_the_listing_path_emits_no_prose_and_no_verification():
    """No answer_delta, no verification, no refusal: there is nothing to verify.

    The verifier's job is to check that a drafted sentence quotes a retrieved
    paragraph verbatim. This path drafts no sentence, because the facts it
    reports are node fields that no paragraph states. Skipping the verifier is
    only safe while that holds, so the absence of prose is asserted here beside
    the absence of the check on it.
    """
    names = [name for name, _ in stream_events()]

    assert names == ["listing", "done"]
    assert "answer_delta" not in names
    assert "verification" not in names
    assert "refusal" not in names


def test_the_listing_path_finishes_answered_not_refused():
    """The refusal this replaces was the bug, so the status has to change too.

    A caller that only reads answer_status must see this question succeed; a
    REFUSED envelope beside a full table of rows is the same wrong answer in a
    new place.
    """
    payloads = dict(stream_events())
    envelope = payloads["done"]["envelope"]

    # The rows the UI draws reach it on the listing event, with their window.
    assert payloads["listing"]["rows"][0]["ad_number"] == "2026-21-07"
    assert payloads["listing"]["corpus_latest"] == "2026-10-27"
    assert payloads["listing"]["total_available"] == len(REVISIONS)

    assert envelope["answer_status"] == "ANSWERED"
    # Nothing was cited because nothing was claimed in prose, and the envelope
    # says what it does not establish rather than leaving it implied.
    assert envelope["citations"] == []
    assert envelope["applicability_result"] is None
    assert envelope["evaluated_conditions"]["unavailable"]


# ---------------------------------------------------------------- the routing


def test_a_question_without_a_plan_does_not_take_this_path():
    """Planning is advisory, and a plan it could not produce is not a recency question.

    plan_query returns None with no API key and when the budget cap is reached.
    The engine's behaviour in that case must be exactly what it was before this
    path existed, so None must not route here -- and must not be guessed at
    from the question text either.
    """
    assert is_recent_intent(None) is False


@pytest.mark.parametrize("intent", [i for i in contract()["enums"]["intent"] if i != INTENT])
def test_no_other_intent_takes_this_path(intent):
    """An ordinary topic search must not be swallowed by the listing.

    "recent fuel pump ADs" is a search with a topic; answering it with the ten
    newest directives in the corpus would be confidently off-subject.
    """
    assert is_recent_intent(QueryPlan(intent=intent)) is False


def test_the_recent_intent_is_the_contract_value_and_routes():
    assert INTENT in contract()["enums"]["intent"]
    assert is_recent_intent(QueryPlan(intent=INTENT, topic="latest ADs")) is True


@pytest.mark.parametrize(
    "named",
    [
        {"ad_number": "2026-21-07"},
        {"docket_id": "FAA-2026-1234"},
        {"aircraft": {"model": "737-800"}},
    ],
)
def test_a_plan_that_names_a_subject_is_not_a_question_about_the_corpus(named):
    """"The latest revision of AD 2026-21-07" is about that AD, not about 2,161.

    The classifier can mislabel, and the cost of a mislabel here is a confident
    table of unrelated directives in place of the one the engineer asked about.
    The guard reads the fields the planner extracted -- ad_number, docket_id,
    aircraft -- and never the wording, so the question falls through to the
    ordinary path that can answer it.
    """
    assert is_recent_intent(QueryPlan(intent=INTENT, **named)) is False


def test_the_planner_prompt_describes_the_class_without_swallowing_a_search():
    """The classifier is the only model in this path, so its brief is pinned.

    The failure mode is not a missed listing, it is a captured search: a prompt
    that says "recent" without saying "names no directive, docket or aircraft"
    sends every question containing the word "recent" to a table of the ten
    newest ADs.
    """
    from engine.retrieval.plan import SYSTEM

    assert f'"{INTENT}"' in SYSTEM
    lowered = SYSTEM.lower()
    for guard in ("newest", "latest", "names no directive", "topic"):
        assert guard in lowered, f"the planner prompt does not mention {guard!r}"


# ------------------------------------------------------- against the real corpus


def test_the_built_corpus_answers_the_question_it_used_to_refuse():
    """The live check: the index really does hold what the refusal denied.

    Deliberately asserted against the file rather than against the numbers in
    the issue (2,161 revisions ending 2026-10-27). A re-ingest moves those
    numbers, and a test that pins them would then fail for being right. What
    must stay true is that the listing's window is the corpus's own window.
    """
    nodes = ROOT / "data" / "build" / "nodes.jsonl"
    if not nodes.exists():
        pytest.skip("no data/build/nodes.jsonl yet - run the ingest")

    revisions, products = [], {}
    for line in nodes.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("_type") == "Revision":
            revisions.append(record)
        elif record.get("_type") == "AD":
            products[str(record["ad_number"])] = record
    if not revisions:
        pytest.skip("the built corpus holds no revisions")

    listing = RecentIndex.build(revisions, products).latest()

    dates = [str(r.get("publication_date") or "") for r in revisions]
    assert listing.total_available == len(revisions)
    assert listing.corpus_latest == max(dates)
    assert listing.corpus_earliest == min(d for d in dates if d)
    assert [row["publication_date"] for row in listing.rows] == sorted(
        (row["publication_date"] for row in listing.rows), reverse=True
    )
    assert listing.rows[0]["publication_date"] == listing.corpus_latest
    # Every row is citable the way a reader cites: by AD number and by the
    # Federal Register. A row that cannot be looked up is not an answer.
    for row in listing.rows:
        assert row["ad_number"], f"a listing row has no AD number: {row}"
        assert row["fr_citation"], f"{row['ad_number']} has no Federal Register citation"


# ------------------------------------------------- narrowing to one year


def test_a_year_filter_counts_the_matches_not_the_corpus():
    """``total_available`` is what the rows are the head of.

    Left as the corpus size it would read as "10 of 2,161", when the honest
    claim for a year-scoped question is "10 of the 317 published that year".
    """
    listing = index().published_in("2024")

    assert listing.filter_label == "published in 2024"
    assert listing.total_available == sum(
        1 for r in REVISIONS if r["publication_date"].startswith("2024-")
    )
    assert all(r["publication_date"].startswith("2024-") for r in listing.rows)


def test_a_year_outside_the_corpus_returns_no_rows_but_keeps_the_window():
    """An empty list alone would read as "the FAA published none that year".

    The corpus window still travels, so the reader can see the question fell
    outside what this engine holds rather than outside what exists.
    """
    listing = index().published_in("1995")

    assert listing.rows == ()
    assert listing.total_available == 0
    assert listing.corpus_earliest and listing.corpus_latest
    assert listing.filter_label == "published in 1995"


def test_the_unfiltered_listing_still_reports_no_filter():
    assert index().latest().filter_label is None
    assert index().latest().sse_payload(1.0)["filter"] is None


def test_the_filter_travels_on_the_contract_payload():
    payload = index().published_in("2024").sse_payload(2.0)

    assert payload["filter"] == "published in 2024"
    validate_event("listing", payload)
