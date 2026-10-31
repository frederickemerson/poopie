"""Proposals are indexed, retrievable and citable -- and can never oblige anyone.

The challenge's own dataset is 431 NPRMs and the organizers ask for their full
text, so proposals ARE in the corpus. That makes the fence load-bearing rather
than theoretical, and these are the tests of the fence.

The fence has three independent layers, and each is tested separately so that
breaking one does not pass by hiding behind another:

1. **File separation.** Proposal paragraphs are written to
   ``nprm_paragraphs.jsonl``, never to ``paragraphs.jsonl``. The rules
   extractor -- which turns a paragraph into an ``Action`` with a
   ``compliance_time`` -- reads only the latter and has no stage check of its
   own, so the separation is what makes it safe, not a filter someone has to
   remember.
2. **Default retrieval scope.** The graph filter returns adopted rules unless a
   caller asks for proposals by name.
3. **The obligation fence.** ``engine.graph.stage.may_establish_obligation``
   refuses a proposal paragraph outright, whatever its heading says.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import ContractViolation, enum  # noqa: E402
from engine import paths  # noqa: E402
from engine.graph.pages import page_range as fr_page_range  # noqa: E402
from engine.graph.stage import (  # noqa: E402
    ADOPTED_NOT_YET_EFFECTIVE,
    EFFECTIVE,
    PROPOSED,
    SOURCE_KIND_NPRM,
    SOURCE_KIND_REVISION,
    SUPERSEDED,
    may_establish_obligation,
    obligation_refusal,
    split_obligation_evidence,
)
from engine.ingest.emit import GraphWriter  # noqa: E402
from engine.retrieval.corpus import Paragraph, load_corpus  # noqa: E402
from engine.retrieval.graph_filter import (  # noqa: E402
    ALL_SOURCE_KINDS,
    DEFAULT_SOURCE_KINDS,
    PROPOSALS_ONLY,
    filter_candidates,
)
from engine.retrieval.entities import Entities  # noqa: E402

BUILD = ROOT / "data" / "build"

#: Roles an NPRM paragraph really does carry. A proposal's section headings are
#: word for word the final rule's, so these are the exact labels that make a
#: text-based check impossible and a source_kind check necessary.
OBLIGATION_SHAPED_ROLES = ("COMPLIANCE", "REQUIRED_ACTIONS", "APPLICABILITY")


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _proposal(role: str = "COMPLIANCE", **over) -> Paragraph:
    base = dict(
        paragraph_id="NPRM-001#f",
        revision_id=None,
        label="f",
        role=role,
        heading="Compliance",
        text="Comply with this AD within the compliance times specified.",
        char_start=0,
        char_end=10,
        ordinal=5,
        nprm_id="NPRM-001",
        source_kind=SOURCE_KIND_NPRM,
        document_stage=PROPOSED,
    )
    base.update(over)
    return Paragraph(**base)


# =====================================================================
# Layer 3: the obligation fence
# =====================================================================

def test_a_proposal_paragraph_cannot_establish_an_obligation():
    """THE test. If this passes while returning True, a proposal can be read as
    law and every other guarantee in this file is decoration."""
    assert may_establish_obligation(SOURCE_KIND_NPRM, PROPOSED) is False
    assert obligation_refusal(SOURCE_KIND_NPRM, PROPOSED) is not None


def test_a_proposal_whose_heading_says_compliance_is_still_refused():
    """The trap. An NPRM's "(f) Compliance" paragraph is word for word the final
    rule's, so nothing readable in the text distinguishes them. Only the parent
    document type does."""
    for role in OBLIGATION_SHAPED_ROLES:
        paragraph = _proposal(role=role)
        assert paragraph.role == role
        assert (
            may_establish_obligation(paragraph.source_kind, paragraph.document_stage)
            is False
        ), f"a proposal's {role} paragraph must not establish an obligation"


def test_mislabelling_a_proposal_as_adopted_does_not_let_it_through():
    """Belt and braces: both the kind and the stage are checked, so a record
    that lies about one is still refused on the other."""
    assert may_establish_obligation(SOURCE_KIND_NPRM, EFFECTIVE) is False
    assert may_establish_obligation(SOURCE_KIND_REVISION, PROPOSED) is False
    assert may_establish_obligation(None, EFFECTIVE) is False
    assert may_establish_obligation("", "") is False


def test_an_adopted_revision_can_establish_an_obligation():
    """The converse, so the fence cannot be satisfied by refusing everything --
    which would be a different and equally wrong answer."""
    assert may_establish_obligation(SOURCE_KIND_REVISION, EFFECTIVE) is True
    assert may_establish_obligation(SOURCE_KIND_REVISION, ADOPTED_NOT_YET_EFFECTIVE) is True
    assert may_establish_obligation(SOURCE_KIND_REVISION, SUPERSEDED) is True
    assert obligation_refusal(SOURCE_KIND_REVISION, EFFECTIVE) is None


def test_splitting_evidence_reports_what_it_set_aside():
    """A caller must be able to say what it dropped, not quietly shrink."""
    adopted = Paragraph(
        "2026-21387#f", "2026-21387", "f", "COMPLIANCE", "Compliance",
        "text", 0, 4, 5, source_kind=SOURCE_KIND_REVISION, document_stage=EFFECTIVE,
    )
    eligible, excluded = split_obligation_evidence([_proposal(), adopted])
    assert [p.paragraph_id for p in eligible] == ["2026-21387#f"]
    assert len(excluded) == 1
    assert excluded[0]["paragraph_id"] == "NPRM-001#f"
    assert excluded[0]["document_stage"] == PROPOSED
    assert excluded[0]["reason"]


def test_every_stage_a_proposal_can_carry_is_a_contract_value():
    assert PROPOSED in enum("document_stage")
    assert SOURCE_KIND_NPRM in enum("source_kind")
    assert SOURCE_KIND_REVISION in enum("source_kind")


# =====================================================================
# Layer 1: file separation
# =====================================================================

def test_the_rules_extractor_reads_only_the_citable_file():
    """Pinned because the separation is only a guarantee while this holds."""
    from engine.rules import cli

    parser = cli.build_parser()
    default = parser.parse_args(["extract"]).paragraphs
    assert Path(default) == paths.PARAGRAPHS_JSONL
    assert paths.PARAGRAPHS_JSONL != paths.NPRM_PARAGRAPHS_JSONL


def test_no_proposal_paragraph_is_in_the_citable_file():
    paragraphs = _jsonl(paths.PARAGRAPHS_JSONL)
    if not paragraphs:
        pytest.skip("no built paragraphs yet")
    leaked = [
        p["paragraph_id"]
        for p in paragraphs
        if p.get("nprm_id") or p.get("source_kind") != SOURCE_KIND_REVISION
    ]
    assert not leaked, f"proposals reached the citable file: {leaked[:5]}"
    assert all(p.get("revision_id") for p in paragraphs)
    assert all(p.get("document_stage") != PROPOSED for p in paragraphs)


def test_the_writer_refuses_to_put_a_proposal_in_the_citable_file(tmp_path):
    """Behaviour, not just the current artifact: a future build cannot do it
    either, even by forgetting to pass the second path."""
    writer = GraphWriter(
        tmp_path / "nodes.jsonl", tmp_path / "edges.jsonl", tmp_path / "paragraphs.jsonl"
    )
    try:
        with pytest.raises(ContractViolation, match="nprm_paragraphs"):
            writer.node(
                "Paragraph",
                {
                    "paragraph_id": "NPRM-001#f",
                    "revision_id": None,
                    "nprm_id": "NPRM-001",
                    "source_kind": SOURCE_KIND_NPRM,
                    "document_stage": PROPOSED,
                    "label": "f",
                    "role": "COMPLIANCE",
                    "heading": "Compliance",
                    "text": "t",
                    "char_start": 0,
                    "char_end": 1,
                    "ordinal": 0,
                },
            )
    finally:
        writer.close()
    assert (tmp_path / "paragraphs.jsonl").read_text() == ""


def test_the_writer_routes_by_source_kind_not_by_call_order(tmp_path):
    paths_ = [tmp_path / n for n in ("nodes.jsonl", "edges.jsonl", "p.jsonl", "n.jsonl")]
    with GraphWriter(*paths_) as writer:
        writer.node(
            "Paragraph",
            {
                "paragraph_id": "NPRM-001#f", "revision_id": None,
                "nprm_id": "NPRM-001", "source_kind": SOURCE_KIND_NPRM,
                "document_stage": PROPOSED, "label": "f", "role": "COMPLIANCE",
                "heading": "Compliance", "text": "t", "char_start": 0,
                "char_end": 1, "ordinal": 0,
            },
        )
        writer.node(
            "Paragraph",
            {
                "paragraph_id": "2026-21387#f", "revision_id": "2026-21387",
                "nprm_id": None, "source_kind": SOURCE_KIND_REVISION,
                "document_stage": EFFECTIVE, "label": "f", "role": "COMPLIANCE",
                "heading": "Compliance", "text": "t", "char_start": 0,
                "char_end": 1, "ordinal": 0,
            },
        )
        assert writer.paragraph_counts == {SOURCE_KIND_NPRM: 1, SOURCE_KIND_REVISION: 1}
    assert "2026-21387#f" in paths_[2].read_text()
    assert "NPRM-001#f" not in paths_[2].read_text()
    assert "NPRM-001#f" in paths_[3].read_text()


@pytest.mark.parametrize(
    "broken,message",
    [
        ({"revision_id": "r1", "nprm_id": "NPRM-001"}, "exactly one"),
        ({"revision_id": None, "nprm_id": None}, "exactly one"),
        ({"revision_id": None, "nprm_id": "NPRM-001",
          "source_kind": SOURCE_KIND_REVISION}, "source_kind"),
        ({"revision_id": None, "nprm_id": "NPRM-001",
          "document_stage": EFFECTIVE}, "must be PROPOSED"),
        ({"revision_id": "r1", "nprm_id": None, "source_kind": SOURCE_KIND_REVISION,
          "document_stage": PROPOSED}, "cannot be staged"),
    ],
)
def test_the_writer_refuses_an_incoherent_parentage(tmp_path, broken, message):
    record = {
        "paragraph_id": "NPRM-001#f",
        "revision_id": None,
        "nprm_id": "NPRM-001",
        "source_kind": SOURCE_KIND_NPRM,
        "document_stage": PROPOSED,
        "label": "f",
        "role": "COMPLIANCE",
        "heading": "Compliance",
        "text": "t",
        "char_start": 0,
        "char_end": 1,
        "ordinal": 0,
    }
    record.update(broken)
    record["paragraph_id"] = f"{record['revision_id'] or record['nprm_id']}#f"
    with GraphWriter(
        tmp_path / "n.jsonl", tmp_path / "e.jsonl", tmp_path / "p.jsonl",
        tmp_path / "np.jsonl",
    ) as writer:
        with pytest.raises(ContractViolation, match=message):
            writer.node("Paragraph", record)


def test_no_rule_or_action_traces_to_a_proposal():
    """The extractor's output, checked against the proposal ids. An Action
    carries a compliance_time, so one built from a proposal would be a deadline
    that does not exist."""
    nodes = _jsonl(BUILD / "nodes.jsonl")
    nprm_ids = {n["nprm_id"] for n in nodes if n.get("_type") == "NPRM"}
    if not nprm_ids:
        pytest.skip("no built proposals yet")
    proposal_paragraphs = {
        p["paragraph_id"] for p in _jsonl(paths.NPRM_PARAGRAPHS_JSONL)
    }
    for name in ("rules.jsonl", "actions.jsonl"):
        for record in _jsonl(BUILD / name):
            assert record.get("revision_id") not in nprm_ids, (
                f"{name}: {record.get('rule_id') or record.get('action_id')} "
                f"names a proposal as its document"
            )
            assert record.get("paragraph_id") not in proposal_paragraphs, (
                f"{name}: {record.get('rule_id') or record.get('action_id')} "
                f"cites a proposal paragraph"
            )


def test_every_built_proposal_paragraph_is_staged_proposed():
    records = _jsonl(paths.NPRM_PARAGRAPHS_JSONL)
    if not records:
        pytest.skip("no harvested proposal text yet")
    assert all(r["document_stage"] == PROPOSED for r in records)
    assert all(r["source_kind"] == SOURCE_KIND_NPRM for r in records)
    assert all(r["revision_id"] is None and r["nprm_id"] for r in records)
    assert all(
        r["paragraph_id"] == f"{r['nprm_id']}#{r['label']}" for r in records
    )


def test_a_proposal_paragraph_id_survives_citation_id_splitting():
    """A citation id is split on its first ``@``. An nprm_id carrying one would
    resolve to a prefix of itself and cite nothing."""
    records = _jsonl(paths.NPRM_PARAGRAPHS_JSONL)
    if not records:
        pytest.skip("no harvested proposal text yet")
    for record in records:
        citation_id = f"{record['paragraph_id']}@{record['char_start']}-{record['char_end']}"
        assert citation_id.split("@", 1)[0] == record["paragraph_id"]


# =====================================================================
# Layer 2: default retrieval scope
# =====================================================================

@pytest.fixture(scope="module")
def corpus():
    loaded = load_corpus()
    if SOURCE_KIND_NPRM not in loaded.counts_by_source_kind():
        pytest.skip("corpus holds no proposals yet")
    return loaded


def test_the_default_scope_is_adopted_rules_only():
    assert DEFAULT_SOURCE_KINDS == (SOURCE_KIND_REVISION,)


def test_the_default_candidate_set_holds_no_proposal(corpus):
    """The regression guard. A question about an obligation must not start
    competing against 3,000 paragraphs that impose nothing."""
    result = filter_candidates(corpus, Entities())
    assert result.nprm_ids == []
    assert result.source_kinds == (SOURCE_KIND_REVISION,)
    candidates = set(result.paragraph_ids)
    proposals = {p.paragraph_id for p in corpus.paragraphs if p.is_proposal}
    assert proposals, "corpus should hold proposals for this test to mean anything"
    assert not (candidates & proposals)


def test_the_all_revisions_scope_still_holds_no_proposal(corpus):
    """``revision_scope='all'`` widens revisions, not document kinds. Proposals
    have ``is_current_revision`` False, so without the source_kind filter this
    is exactly where they would leak in."""
    result = filter_candidates(corpus, Entities(), revision_scope="all")
    assert result.nprm_ids == []
    proposals = {p.paragraph_id for p in corpus.paragraphs if p.is_proposal}
    assert not (set(result.paragraph_ids) & proposals)


def test_an_ad_number_never_pulls_in_a_proposal(corpus):
    ad = next(iter(corpus.ad_numbers))
    result = filter_candidates(
        corpus, Entities(ad_numbers=[ad]), source_kinds=ALL_SOURCE_KINDS
    )
    assert result.nprm_ids == []
    assert result.narrowed


def test_proposals_are_retrievable_when_a_caller_asks(corpus):
    """The other half of the invariant: proposals MAY be indexed and retrieved.
    A fence that made them unreachable would fail the rubric instead."""
    result = filter_candidates(corpus, Entities(), source_kinds=PROPOSALS_ONLY)
    assert result.paragraph_ids
    assert len(result.nprm_ids) > 1
    assert result.revision_ids == []
    for paragraph_id in result.paragraph_ids:
        assert corpus.by_id[paragraph_id].document_stage == PROPOSED


def test_a_named_proposal_narrows_to_that_proposal(corpus):
    nprm_id = next(
        p.nprm_id for p in corpus.paragraphs if p.is_proposal
    )
    result = filter_candidates(
        corpus, Entities(), source_kinds=PROPOSALS_ONLY, nprm_ids=[nprm_id]
    )
    assert result.narrowed
    assert result.nprm_ids == [nprm_id]
    assert all(
        corpus.by_id[p].nprm_id == nprm_id for p in result.paragraph_ids
    )


def test_asking_for_a_proposal_without_widening_the_scope_is_reported(corpus):
    nprm_id = next(p.nprm_id for p in corpus.paragraphs if p.is_proposal)
    result = filter_candidates(corpus, Entities(), nprm_ids=[nprm_id])
    assert not result.narrowed
    assert any("source_kinds excludes proposals" in u for u in result.unavailable)
    assert result.nprm_ids == []


def test_a_dockets_proposals_come_with_its_rules_when_asked(corpus):
    """The docket is the join between a proposal and the rule it became."""
    docket = next(
        meta.docket_id for meta in corpus.nprms.values() if meta.docket_id
    )
    narrow = filter_candidates(
        corpus, Entities(docket_ids=[docket]), source_kinds=ALL_SOURCE_KINDS
    )
    assert narrow.nprm_ids
    default = filter_candidates(corpus, Entities(docket_ids=[docket]))
    assert default.nprm_ids == []


def test_every_paragraph_knows_its_stage_and_its_document(corpus):
    for paragraph in corpus.paragraphs:
        assert paragraph.source_kind in enum("source_kind")
        assert paragraph.document_stage in enum("document_stage")
        assert bool(paragraph.revision_id) != bool(paragraph.nprm_id)
        assert paragraph.document_id
        if paragraph.is_proposal:
            assert paragraph.document_stage == PROPOSED
        else:
            assert paragraph.document_stage != PROPOSED


def test_a_proposal_hit_carries_what_the_rubric_asks_a_citation_to_name(corpus):
    """record_id plus the Federal Register citation and page range."""
    proposals = [p for p in corpus.paragraphs if p.is_proposal]
    assert proposals
    missing = [
        p.paragraph_id
        for p in proposals
        if not (p.record_id and p.fr_citation and p.page_range)
    ]
    assert not missing, f"proposal paragraphs with no human reference: {missing[:5]}"


def test_no_paragraph_claims_its_pages_are_unrecorded_when_they_are(corpus):
    """A null page range beside a populated citation is a FALSE ABSENCE.

    Found by the citation layer cross-checking its own ``ReferenceBook``
    against every hit: all 25,687 adopted paragraphs carried
    ``fr_citation="91 FR 67442"`` next to ``page_range=None``, because the
    Revision branch formatted the citation and left the range to the dataclass
    default. A consumer reading the flat field -- which looks authoritative,
    sitting right beside the citation -- rendered "page range not recorded" for
    every adopted AD in the corpus, while the Register had stated the pages all
    along. Inventing a page is the obvious failure; denying one the source gave
    is the quiet one, and it is the one the rubric's citation rule punishes.

    So this is checked corpus-wide and against the document node, not sampled.
    """
    expected: dict[str, str | None] = {}
    for line in paths.NODES_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        kind = record.get("_type")
        if kind == "Revision":
            expected[record["revision_id"]] = fr_page_range(
                record.get("start_page"), record.get("end_page")
            )
        elif kind == "NPRM":
            expected[record["nprm_id"]] = record.get("page_range")

    unrecorded = [p.paragraph_id for p in corpus.paragraphs if not p.page_range]
    assert not unrecorded, (
        f"{len(unrecorded)} paragraphs report no page range while their document "
        f"node states one: {unrecorded[:5]}"
    )
    disagreeing = [
        (p.paragraph_id, p.page_range, expected.get(p.document_id))
        for p in corpus.paragraphs
        if p.page_range != expected.get(p.document_id)
    ]
    assert not disagreeing, (
        f"{len(disagreeing)} paragraphs disagree with their own document node: "
        f"{disagreeing[:5]}"
    )


def test_every_layer_that_prints_a_page_range_calls_the_same_function():
    """Not "they agree" -- *the same object*. Agreement is what we had before.

    There were four implementations of this arithmetic (ingest harvest, ingest
    collect, retrieval corpus, api citations), and they did agree on real data,
    which is exactly why nothing caught the one that emitted a reversed
    ``"66022-66019"`` for an inverted pair. Two functions that agree today are
    a convention; one function is an invariant.

    Comparing outputs can no longer detect a regression here -- a freshly
    re-introduced local copy would pass on every case anyone thought to list --
    so this asserts identity of the binding in each module instead, under
    whatever name that module imported it as.
    """
    import engine.api.citations as citations
    import engine.ingest.collect as collect
    import engine.ingest.nprm_text as nprm_text
    import engine.retrieval.corpus as corpus
    from engine.graph import pages

    bindings = {
        "engine.api.citations.page_range": citations.page_range,
        "engine.ingest.collect.fr_page_range": collect.fr_page_range,
        "engine.retrieval.corpus.fr_page_range": corpus.fr_page_range,
        "engine.ingest.nprm_text (module alias)": nprm_text.fr_pages.page_range,
    }
    local = [
        where for where, func in bindings.items() if func is not pages.page_range
    ]
    assert not local, f"these no longer call engine.graph.pages.page_range: {local}"


def test_the_shape_a_page_range_is_printed_in_is_the_shape_consumers_parse():
    """The formatter's output and the regex that reads it back are declared in
    two different modules, so the shape itself still needs pinning -- including
    the edge cases a real document can produce: a one-page notice, a missing
    end page, and an unusable or inverted pair, none of which may become a
    reversed or zero-width range."""
    from engine.api.citations import PAGE_RANGE

    expected = {
        (66019, 66022): "66019-66022",
        (10504, 10504): "10504",
        (14293, None): "14293",
        (100, 50): "100",      # inverted: the start alone, never "100-50"
        (1, 0): "1",           # 0 is "not recorded", not page zero
        (None, None): None,
        (0, 5): None,          # no usable start page
        (True, 4): None,       # a bool is not a page number
    }
    for (start, end), shape in expected.items():
        printed = fr_page_range(start, end)
        assert printed == shape, f"({start}, {end}) printed {printed!r}"
        assert printed is None or PAGE_RANGE.match(printed)


def test_a_hit_carries_the_paragraph_s_own_reference_unchanged(corpus):
    """The wire payload is built from the Paragraph, so it must not re-derive
    the reference. If a Hit recomputed it, the guarantee above would stop at
    the corpus boundary and the false absence would come back on the wire."""
    from engine.retrieval.index import load_index
    from engine.retrieval.search import search

    from engine.retrieval.layout import INDEX_DB

    if not INDEX_DB.exists():
        pytest.skip("no built retrieval index")
    index = load_index()
    by_id = {p.paragraph_id: p for p in corpus.paragraphs}
    for kinds in (DEFAULT_SOURCE_KINDS, PROPOSALS_ONLY):
        result = search(
            index, "fuel pump inspection compliance time",
            Entities(), k=8, source_kinds=kinds,
        )
        assert result.hits
        for hit in result.hits:
            paragraph = by_id[hit.paragraph_id]
            assert hit.page_range == paragraph.page_range
            assert hit.fr_citation == paragraph.fr_citation
            assert hit.document_stage == paragraph.document_stage
            assert hit.source_kind == paragraph.source_kind
            assert hit.page_range, f"{hit.paragraph_id} went on the wire pageless"
