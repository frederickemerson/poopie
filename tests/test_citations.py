"""The human-readable half of a citation: present, honest, and never invented.

Two failures are pinned here, because both are the kind that reads fine on a
demo and is wrong on paper:

1. **A citation with no document_stage.** A proposal rendered without its stage
   reads as a requirement. ``HumanReference`` therefore cannot be constructed
   without a contract ``document_stage``, and the envelope refuses any resolver
   that returns something whose stage was never checked.
2. **A fabricated page number.** Page numbers come from the Federal Register
   index and nowhere else. ``emit`` refuses a Revision whose ``start_page`` is
   not the page its own ``fr_citation`` names, and refuses a page with no
   citation beside it at all, so there is no node shape in which a made-up page
   can be written. The NPRM spreadsheet's citation prose is never parsed into a
   citation either; it is shown verbatim or reported absent.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import ContractViolation, enum  # noqa: E402
from engine.api.answer import build_envelope  # noqa: E402
from engine.api.citations import (  # noqa: E402
    EMPTY_BOOK,
    CitationStageMissing,
    HumanReference,
    ReferenceBook,
    page_report,
    reference_dicts,
    resolver_for,
    volume_of,
)
from engine.api.server import STATE as server_state  # noqa: E402
from engine.api.server import _retrieval_paragraphs, health  # noqa: E402
from engine.ingest.collect import _record  # noqa: E402
from engine.ingest.emit import GraphWriter  # noqa: E402
from engine.retrieval.search import Hit  # noqa: E402
from engine.verify.verifier import SentenceVerdict, Verification  # noqa: E402

TODAY = dt.date(2026, 10, 31)

#: One real Federal Register index response, as the API returned it.
INDEX_DOCUMENT = {
    "document_number": "2026-21864",
    "docket_ids": ["Docket No. FAA-2025-0003", "Amendment 39-23501", "AD 2026-21-12"],
    "title": "Airworthiness Directives; The Boeing Company Airplanes",
    "type": "Rule",
    "publication_date": "2026-10-27",
    "effective_on": "2026-12-01",
    "citation": "91 FR 66019",
    "start_page": 66019,
    "end_page": 66022,
    "full_text_xml_url": "https://example.invalid/2026-21864.xml",
}

REVISION_NODE = {
    "_type": "Revision",
    "revision_id": "2026-21864",
    "ad_number": "2026-21-12",
    "publication_date": "2026-10-27",
    "effective_on": "2026-10-01",
    "superseded_by": None,
    "fr_citation": "91 FR 66019",
    "start_page": 66019,
    "end_page": 66022,
    "full_text_xml_url": "https://example.invalid/2026-21864.xml",
}

NPRM_NODE = {
    "_type": "NPRM",
    "nprm_id": "FAA-2026-11814@2026-10-19",
    "record_id": "NPRM-001",
    "ad_number": None,
    "publish_date": "2026-10-19",
    "citation": "Federal Register, Volume 91 Number 200 (Monday, October 19, 2026)",
    "page_range": "66019-66022",
    "federal_register_link": "https://example.invalid/nprm",
}


def _Hit(paragraph_id, label, role, char_start=0, char_end=40) -> Hit:
    """A real retrieval Hit, so the payload shape under test is the live one."""
    return Hit(
        paragraph_id=paragraph_id,
        ad_number="2026-21-12",
        revision_id=paragraph_id.split("#", 1)[0],
        label=label,
        role=role,
        heading="Required Actions",
        text="x" * (char_end - char_start),
        char_start=char_start,
        char_end=char_end,
        score=0.0328,
        keyword_rank=1,
        dense_rank=1,
        dense_cosine=0.61,
    )


def _writer(tmp_path) -> GraphWriter:
    return GraphWriter(tmp_path / "n.jsonl", tmp_path / "e.jsonl", tmp_path / "p.jsonl")


def _book() -> ReferenceBook:
    return ReferenceBook(
        {REVISION_NODE["revision_id"]: REVISION_NODE},
        {NPRM_NODE["nprm_id"]: NPRM_NODE},
        today=TODAY,
    )


# ------------------------------------------- 1. the ingest carries the fields


def test_the_index_citation_and_pages_reach_the_revision_record():
    """fr_client requests them, collect must keep them as the index gave them."""
    record = _record(INDEX_DOCUMENT, in_window=True)
    assert record.citation == "91 FR 66019"
    assert record.start_page == 66019
    assert record.end_page == 66022
    # Derived, so it cannot disagree with the integers it came from.
    assert record.page_range == "66019-66022"


def test_a_one_page_document_has_no_range():
    record = _record({**INDEX_DOCUMENT, "end_page": 66019}, in_window=True)
    assert record.page_range == "66019"


def test_an_unreadable_page_number_is_absent_not_coerced():
    record = _record({**INDEX_DOCUMENT, "start_page": "", "end_page": None}, in_window=True)
    assert record.start_page is None
    assert record.end_page is None
    assert record.page_range is None


def test_the_revision_node_carries_the_citation_and_its_pages(tmp_path):
    from engine.ingest.build import _reference_fields

    with _writer(tmp_path) as writer:
        writer.node(
            "Revision",
            {
                "revision_id": "2026-21864",
                "ad_number": "2026-21-12",
                **_reference_fields(_record(INDEX_DOCUMENT, in_window=True)),
            },
        )
    line = json.loads((tmp_path / "n.jsonl").read_text(encoding="utf-8").strip())
    assert line["fr_citation"] == "91 FR 66019"
    assert line["start_page"] == 66019
    assert line["end_page"] == 66022


# ------------------------------------- 2. a fabricated page number is refused


@pytest.mark.parametrize(
    "bad, why",
    [
        ({"start_page": 66019}, "a page with no citation to corroborate it"),
        ({"fr_citation": "91 FR 66019", "start_page": 70000}, "page disagrees with the citation"),
        ({"fr_citation": "91 FR 66019", "start_page": 66019, "end_page": 66018}, "end before start"),
        ({"fr_citation": "Volume 91, page 66019", "start_page": 66019}, "citation is prose"),
        ({"fr_citation": "91 FR 66019", "end_page": 66022}, "end page with no start"),
        ({"fr_citation": "91 FR 66019", "start_page": 0}, "page zero"),
        ({"fr_citation": "91 FR 66019", "start_page": -4}, "negative page"),
        ({"fr_citation": "91 FR 66019", "start_page": True}, "a bool is not a page"),
    ],
)
def test_emit_refuses_a_page_number_the_citation_does_not_support(tmp_path, bad, why):
    with _writer(tmp_path) as writer:
        with pytest.raises(ContractViolation):
            writer.node("Revision", {"revision_id": "r1", "ad_number": "a", **bad})


def test_emit_accepts_a_revision_with_no_pages_at_all(tmp_path):
    """Absent is legal. Only an unsupported page number is not."""
    with _writer(tmp_path) as writer:
        writer.node("Revision", {"revision_id": "r1", "ad_number": "a"})
    line = json.loads((tmp_path / "n.jsonl").read_text(encoding="utf-8").strip())
    assert line["fr_citation"] is None and line["start_page"] is None


def test_the_cached_index_really_does_corroborate_every_page():
    """The invariant emit relies on, checked against the real cached responses.

    If the Federal Register ever stops putting the start page in the citation,
    this fails here rather than turning into a silently dropped page range.
    """
    files = glob.glob(str(ROOT / "data" / "raw" / "fr_index" / "*.json"))
    if not files:
        pytest.skip("no cached Federal Register index responses")
    checked, offenders = 0, []
    for path in files:
        for result in json.loads(Path(path).read_text(encoding="utf-8")).get("results") or []:
            citation, start = result.get("citation"), result.get("start_page")
            if citation is None or start is None:
                continue
            checked += 1
            if citation.strip() != f"{citation.split()[0]} FR {start}":
                offenders.append((result.get("document_number"), citation, start))
    assert checked > 0, "cached index responses carry no citation/start_page pairs"
    assert not offenders, f"{len(offenders)} citations do not name their start page: {offenders[:5]}"


# ---------------------------------------- 3. a citation always carries a stage


def test_a_reference_cannot_exist_without_a_contract_stage():
    for stage in ("", None, "IN_FORCE", "proposed"):
        with pytest.raises(CitationStageMissing):
            HumanReference(
                citation_id="r#a@0-1",
                document_id="r",
                source_kind=None,
                document_stage=stage,  # type: ignore[arg-type]
                stage_note="",
                ad_number=None,
                record_id=None,
                fr_citation=None,
                page_range=None,
                source_citation_text=None,
                paragraph_label="a",
                paragraph_role=None,
                federal_register_link=None,
            )


def test_every_reference_the_book_hands_out_has_a_stage():
    book = _book()
    for citation_id in (
        "2026-21864#(g)@10-20",
        "FAA-2026-11814@2026-10-19#(c)@0-9",
        "a-document-we-do-not-hold#(a)@0-1",
        "not even an id",
    ):
        reference = book.reference(citation_id)
        assert reference.document_stage in enum("document_stage")
        assert reference.document_stage in reference.display


def test_the_envelope_refuses_a_resolver_that_skipped_the_stage_check():
    with pytest.raises(CitationStageMissing):
        reference_dicts(lambda cid: {"document_stage": "EFFECTIVE"}, ["r#a@0-1"])


def _verification(citation_ids: list[str]) -> Verification:
    return Verification(
        verdicts=[
            SentenceVerdict(
                index=0,
                text="The AD requires an inspection.",
                kept=True,
                citation_ids=list(citation_ids),
                supporting_citation_id=citation_ids[0],
            )
        ],
        stage_ms=0.1,
    )


def test_every_envelope_citation_carries_its_stage_and_its_reference():
    hits = [_Hit("2026-21864#(g)", "(g)", "REQUIRED_ACTIONS")]
    envelope = build_envelope(
        answer_status="ANSWERED",
        document_stage="EFFECTIVE",
        decision=None,
        decision_unavailable=None,
        verification=_verification(["2026-21864#(g)@10-20"]),
        answer=None,
        revision_id="2026-21864",
        superseded_by=None,
        refusals=[],
        traversal=None,
        unreviewed_rules=0,
        references=resolver_for(_book(), hits),
    )
    (citation,) = envelope["citations"]
    assert citation["citation_ids"] == ["2026-21864#(g)@10-20"]
    (reference,) = citation["references"]
    assert reference["document_stage"] == "EFFECTIVE"
    assert reference["ad_number"] == "2026-21-12"
    assert reference["fr_citation"] == "91 FR 66019"
    assert reference["page_range"] == "66019-66022"
    assert reference["paragraph_role"] == "REQUIRED_ACTIONS"
    assert reference["paragraph_label"] == "(g)"


def test_an_envelope_built_without_a_book_still_states_a_stage():
    """The default resolver is an empty book, never no resolver at all."""
    envelope = build_envelope(
        answer_status="ANSWERED",
        document_stage="EFFECTIVE",
        decision=None,
        decision_unavailable=None,
        verification=_verification(["whatever#(a)@0-1"]),
        answer=None,
        revision_id=None,
        superseded_by=None,
        refusals=[],
        traversal=None,
        unreviewed_rules=0,
    )
    (reference,) = envelope["citations"][0]["references"]
    assert reference["document_stage"] == "UNKNOWN"
    assert reference["fr_citation"] is None
    assert "fr_citation" in reference["not_recorded"]
    assert "not recorded" in reference["display"]


# ------------------------------------------- 4. a proposal reads as a proposal


def test_an_nprm_citation_is_a_proposal_and_says_so():
    reference = _book().reference("FAA-2026-11814@2026-10-19#(c)@0-9", role="APPLICABILITY")
    assert reference.source_kind == "NPRM"
    assert reference.document_stage == "PROPOSED"
    assert reference.is_proposal is True
    assert "proposal" in reference.stage_note.lower()
    assert "obligation" in reference.stage_note.lower()
    # The rubric's handle for a proposal is the challenge index's record_id.
    assert reference.record_id == "NPRM-001"
    assert reference.handle == "NPRM-001"
    assert "PROPOSED" in reference.display


def test_an_nprm_without_a_record_id_says_so_rather_than_borrowing_one():
    book = ReferenceBook({}, {"x@2026-01-01": {**NPRM_NODE, "nprm_id": "x@2026-01-01", "record_id": None}})
    reference = book.reference("x@2026-01-01#(c)@0-9")
    assert reference.record_id is None
    assert "record_id" in reference.not_recorded
    assert reference.handle == "x@2026-01-01"


def test_a_proposal_never_shows_the_ad_number_it_was_adopted_as():
    """246 of the 431 built NPRM nodes carry the AD they became.

    Printing that number beside a citation to proposed text is the misreading
    the contract's fourth citation rule forbids: the adopted AD is a different
    document, with wording the proposal does not have. The handle stays the
    record_id.
    """
    adopted_outcome = {**NPRM_NODE, "ad_number": "2026-21-03"}
    reference = ReferenceBook({}, {NPRM_NODE["nprm_id"]: adopted_outcome}).reference(
        "FAA-2026-11814@2026-10-19#(c)@0-9", role="APPLICABILITY"
    )
    assert reference.ad_number is None
    assert reference.handle == "NPRM-001"
    assert "2026-21-03" not in reference.display
    assert "2026-21-03" not in json.dumps(reference.as_dict())


def test_a_resolved_proposal_renders_the_registers_own_short_citation():
    """A proposal joined to its PRORULE record reads exactly like the rubric.

    record_id, '91 FR 66019', the page range, the paragraph, and the stage --
    with nothing reported absent, because the register holds all of it.
    """
    resolved = {**NPRM_NODE, "citation": "91 FR 66019", "page_range": "66019-66022"}
    reference = ReferenceBook({}, {NPRM_NODE["nprm_id"]: resolved}).reference(
        "FAA-2026-11814@2026-10-19#(c)@0-9", role="APPLICABILITY"
    )
    assert reference.fr_citation == "91 FR 66019"
    assert reference.page_range == "66019-66022"
    assert reference.source_citation_text is None
    assert reference.not_recorded == ()
    assert reference.display == (
        "NPRM-001 · 91 FR 66019 · pp. 66019-66022 · paragraph (c) APPLICABILITY · PROPOSED"
    )


def test_the_spreadsheet_citation_prose_is_never_rendered_as_an_fr_citation():
    """233 distinct prose shapes live in that column. None is parsed."""
    reference = _book().reference("FAA-2026-11814@2026-10-19#(c)@0-9")
    assert reference.fr_citation is None
    assert "fr_citation" in reference.not_recorded
    # The source's own words are still shown, verbatim.
    assert reference.source_citation_text == NPRM_NODE["citation"]
    assert NPRM_NODE["citation"] in reference.display


def test_an_unreadable_nprm_page_range_is_reported_absent():
    node = {**NPRM_NODE, "page_range": "Pages 45118-45119"}
    book = ReferenceBook({}, {node["nprm_id"]: node})
    reference = book.reference(f"{node['nprm_id']}#(c)@0-9")
    assert reference.page_range is None
    assert "page_range" in reference.not_recorded
    assert "page range not recorded" in reference.display


def test_a_superseded_revision_reads_as_superseded():
    node = {**REVISION_NODE, "revision_id": "old", "superseded_by": "2026-21864"}
    book = ReferenceBook({"old": node}, {}, today=TODAY)
    assert book.reference("old#(c)@0-1").document_stage == "SUPERSEDED"


def test_a_revision_with_no_effective_date_is_unknown_not_effective():
    node = {**REVISION_NODE, "revision_id": "nd", "effective_on": None}
    book = ReferenceBook({"nd": node}, {}, today=TODAY)
    assert book.reference("nd#(c)@0-1").document_stage == "UNKNOWN"


def test_a_stale_build_whose_pages_disagree_shows_neither():
    node = {**REVISION_NODE, "revision_id": "drift", "start_page": 1}
    book = ReferenceBook({"drift": node}, {}, today=TODAY)
    reference = book.reference("drift#(c)@0-1")
    assert reference.fr_citation is None and reference.page_range is None


# --------------------------------------------------- 5. the retrieval payload


def test_the_retrieval_payload_carries_a_human_reference():
    hits = [_Hit("2026-21864#(g)", "(g)", "REQUIRED_ACTIONS", 10, 50)]
    rows = _retrieval_paragraphs(hits, resolver_for(_book(), hits))
    (row,) = rows
    assert row["citation_id"] == "2026-21864#(g)@10-50"
    reference = row["human_reference"]
    assert reference["fr_citation"] == "91 FR 66019"
    assert reference["page_range"] == "66019-66022"
    assert reference["document_stage"] in enum("document_stage")
    # The exact anchor is untouched by any of this.
    assert row["char_start"] == 10 and row["char_end"] == 50


def test_a_resolver_matches_a_paragraph_whose_label_lost_its_parentheses():
    hits = [_Hit("2026-21864#g", "g", "REQUIRED_ACTIONS")]
    reference = resolver_for(_book(), hits)("2026-21864#(g)@0-4")
    assert reference.paragraph_role == "REQUIRED_ACTIONS"


# ------------------------------------------------- 6. the corpus, in pages


def test_the_volume_comes_from_the_citation_and_the_year_agrees():
    assert volume_of(REVISION_NODE, date_field="publication_date") == 91
    assert volume_of(NPRM_NODE, date_field="publish_date") == 91
    # Volume 1 is 1936, so the year fixes the volume on its own.
    assert volume_of({"publication_date": "2021-01-06"}, date_field="publication_date") == 86


def test_a_volume_that_disagrees_with_its_year_is_not_trusted():
    drift = {"fr_citation": "86 FR 458", "publication_date": "2026-01-06"}
    assert volume_of(drift, date_field="publication_date") is None


def test_a_page_shared_by_two_documents_is_counted_once():
    first = {**REVISION_NODE, "revision_id": "a", "start_page": 66019, "end_page": 66022}
    second = {
        **REVISION_NODE,
        "revision_id": "b",
        "fr_citation": "91 FR 66022",
        "start_page": 66022,
        "end_page": 66025,
    }
    report = page_report(ReferenceBook({"a": first, "b": second}, {}))
    adopted = report["adopted"]
    assert adopted["span_sum"] == 8, "4 + 4 pages, counting the shared one twice"
    assert adopted["distinct_pages"] == 7, "66019..66025 is seven pages"
    assert adopted["shared_pages"] == 1
    assert report["total_distinct_pages"] == 7


def test_the_same_page_in_two_volumes_is_two_pages():
    a = {**REVISION_NODE, "revision_id": "a", "fr_citation": "91 FR 500",
         "start_page": 500, "end_page": 500, "publication_date": "2026-01-02"}
    b = {**REVISION_NODE, "revision_id": "b", "fr_citation": "86 FR 500",
         "start_page": 500, "end_page": 500, "publication_date": "2021-01-02"}
    report = page_report(ReferenceBook({"a": a, "b": b}, {}))
    assert report["adopted"]["distinct_pages"] == 2
    assert report["adopted"]["volumes"] == 2


def test_a_page_that_disagrees_with_its_citation_is_not_counted():
    bad = {**REVISION_NODE, "revision_id": "x", "start_page": 1, "end_page": 9}
    report = page_report(ReferenceBook({"x": bad}, {}))
    assert report["adopted"]["distinct_pages"] == 0
    assert report["adopted"]["documents_without_pages"] == 1
    assert report["total_distinct_pages"] == 0


def test_the_page_report_names_the_field_it_used():
    report = page_report(_book())
    assert "start_page" in report["adopted"]["field_used"]
    assert "page_range" in report["proposed"]["field_used"]


def test_an_empty_book_reports_no_pages_rather_than_an_estimate():
    report = page_report(EMPTY_BOOK)
    assert report["total_distinct_pages"] == 0
    assert report["adopted"]["documents"] == 0


def test_health_states_the_size_of_the_corpus_the_latency_target_applies_to():
    """The rubric asks for the corpus size beside the latency target.

    A figure in a README can go stale; this one is served by the running
    engine from the book it actually loaded, so the size a reader is quoted
    is the size that was measured.
    """
    size = {
        "kind": "built",
        "paragraphs": 3,
        "ad_numbers": 2,
        "revisions": 2,
        "proposals": 1,
        "federal_register_pages": 7,
        "pages": page_report(_book()),
    }
    previous = server_state.corpus_size
    server_state.corpus_size = size
    try:
        reported = health()["corpus"]
    finally:
        server_state.corpus_size = previous
    assert reported == size
    assert reported["federal_register_pages"] == 7
    assert reported["pages"]["adopted"]["field_used"]


# ---------------------------------------------------- 7. the built corpus


def _built_revisions() -> list[dict]:
    path = ROOT / "data" / "build" / "nodes.jsonl"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if record.get("_type") == "Revision":
                    out.append(record)
    return out


def test_no_built_revision_carries_a_page_its_citation_does_not_name():
    """Runs against whatever is built. A corrupt page range fails here."""
    revisions = _built_revisions()
    if not revisions:
        pytest.skip("no data/build/nodes.jsonl yet - run: make ingest")
    offenders = []
    for record in revisions:
        citation, start = record.get("fr_citation"), record.get("start_page")
        if start is None:
            continue
        if not citation or citation.strip() != f"{citation.split()[0]} FR {start}":
            offenders.append((record["revision_id"], citation, start))
    assert not offenders, f"{len(offenders)} built revisions carry an unsupported page: {offenders[:5]}"


def test_the_built_revisions_actually_carry_their_citation():
    revisions = _built_revisions()
    if not revisions:
        pytest.skip("no data/build/nodes.jsonl yet - run: make ingest")
    with_citation = sum(1 for r in revisions if r.get("fr_citation"))
    if with_citation == 0:
        pytest.skip(
            f"data/build/nodes.jsonl holds {len(revisions)} revisions and none carries "
            "fr_citation, so it predates the citation fields - rebuild with: make ingest"
        )
    assert with_citation == len(revisions), (
        f"{len(revisions) - with_citation} of {len(revisions)} built revisions have no "
        f"Federal Register citation; the index supplies one for every document"
    )


def test_a_hit_that_cannot_name_its_fields_raises_rather_than_stringifying():
    """A paragraph must never reach the browser as ``str(hit)``.

    ``_plain`` ends in ``str(obj)``, so routing a hit through it produced a
    payload whose top-level keys still validated while every paragraph in it
    was a bare string. The row is built from named fields instead, and a hit
    that cannot supply them stops the stream.
    """

    class _NotAHit:
        paragraph_id = "r#a"
        text = "..."

    with pytest.raises(TypeError, match="as_payload"):
        _retrieval_paragraphs([_NotAHit()], lambda cid: EMPTY_BOOK.reference(cid))


def test_the_retrieval_row_keeps_the_paragraph_text_and_the_exact_offsets():
    """as_payload omits text; the row must put it back or no span can be drawn."""
    hits = [_Hit("2026-21864#(g)", "(g)", "REQUIRED_ACTIONS", 10, 50)]
    (row,) = _retrieval_paragraphs(hits, resolver_for(_book(), hits))
    assert row["text"] == "x" * 40
    assert (row["char_start"], row["char_end"]) == (10, 50)
    assert row["paragraph_id"] == "2026-21864#(g)"
    assert row["role"] == "REQUIRED_ACTIONS"


def test_a_cited_proposal_is_named_in_the_envelope_limitations():
    """A sentence may cite a proposal while the answer's revision is in force."""
    nprm_paragraph = "FAA-2026-11814@2026-10-19#(c)"
    hits = [_Hit(nprm_paragraph, "(c)", "APPLICABILITY")]
    envelope = build_envelope(
        answer_status="ANSWERED",
        document_stage="EFFECTIVE",
        decision=None,
        decision_unavailable=None,
        verification=_verification([f"{nprm_paragraph}@0-9"]),
        answer=None,
        revision_id="2026-21864",
        superseded_by=None,
        refusals=[],
        traversal=None,
        unreviewed_rules=0,
        references=resolver_for(_book(), hits),
    )
    said = " ".join(envelope["limitations"])
    assert "proposals, not rules" in said
    assert "NPRM-001" in said
    assert "no obligation" in said


def test_a_citation_with_no_page_range_is_declared_uncheckable_on_paper():
    stale = {**REVISION_NODE, "revision_id": "old", "fr_citation": None,
             "start_page": None, "end_page": None}
    hits = [_Hit("old#(g)", "(g)", "REQUIRED_ACTIONS")]
    envelope = build_envelope(
        answer_status="ANSWERED",
        document_stage="EFFECTIVE",
        decision=None,
        decision_unavailable=None,
        verification=_verification(["old#(g)@0-9"]),
        answer=None,
        revision_id="old",
        superseded_by=None,
        refusals=[],
        traversal=None,
        unreviewed_rules=0,
        references=resolver_for(ReferenceBook({"old": stale}, {}, today=TODAY), hits),
    )
    said = " ".join(envelope["limitations"])
    assert "no Federal Register citation or page range recorded" in said
    assert "not against a printed page" in said


def test_a_fully_referenced_citation_adds_no_such_limitation():
    hits = [_Hit("2026-21864#(g)", "(g)", "REQUIRED_ACTIONS")]
    envelope = build_envelope(
        answer_status="ANSWERED",
        document_stage="EFFECTIVE",
        decision=None,
        decision_unavailable=None,
        verification=_verification(["2026-21864#(g)@0-9"]),
        answer=None,
        revision_id="2026-21864",
        superseded_by=None,
        refusals=[],
        traversal=None,
        unreviewed_rules=0,
        references=resolver_for(_book(), hits),
    )
    said = " ".join(envelope["limitations"])
    assert "printed page" not in said
    assert "proposals, not rules" not in said


def test_the_two_page_counts_agree_once_the_build_carries_citations():
    """The built nodes and the cached index must give the same page count.

    They are the same three values: the ingest copies ``citation``,
    ``start_page`` and ``end_page`` off the index response. If the counts
    diverge, the ingest derived them instead of copying them.
    """
    from engine.api.citations import corpus_pages

    revisions = _built_revisions()
    if not revisions or not any(r.get("fr_citation") for r in revisions):
        pytest.skip("built nodes carry no fr_citation yet - rebuild with: make ingest")
    if not list((ROOT / "data" / "raw" / "fr_index").glob("*.json")):
        pytest.skip("no cached Federal Register index responses")
    from_nodes = corpus_pages()
    from_index = corpus_pages(from_index=True)
    assert from_nodes["adopted"]["distinct_pages"] == from_index["adopted"]["distinct_pages"]
    assert from_nodes["adopted"]["span_sum"] == from_index["adopted"]["span_sum"]
    assert from_nodes["total_distinct_pages"] == from_index["total_distinct_pages"]
