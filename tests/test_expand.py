"""Reference expansion: the paragraph a ranker drops is still a dependency.

The test that matters is ``test_expansion_recovers_the_paragraph_the_ranker_
dropped``. It runs the project's own hybrid search over a hand-built corpus and
shows a paragraph that *is* the answer losing on both arms -- because the
referenced document describes a different component in different words, which is
precisely why resemblance cannot find it -- then shows expansion adding it
because the retrieved AD names the document it came from. The dense arm is
stubbed with a deterministic hashed bag-of-words embedder, the same function for
the corpus matrix and the query through the real ``build_index``/``search``
path, so no model and no network is needed; the keyword arm is the real FTS5.
"""

from __future__ import annotations

import json
import re
import sys
import zlib
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.graph.loader import EDGE_SUPERSEDES  # noqa: E402
from engine.graph.normalize import normalize_manufacturer  # noqa: E402
from engine.graph.traverse import (  # noqa: E402
    COMPLETE, EDGE_ADOPTS_MCAI, EDGE_HAS_PARAGRAPH, EDGE_REFERENCES_SB,
    KIND_SUPERSESSION, MISSING_DOCUMENT,
)
from engine.retrieval.corpus import Corpus, Paragraph, RevisionMeta  # noqa: E402
from engine.retrieval.entities import extract_entities  # noqa: E402
from engine.retrieval.expand import (  # noqa: E402
    CAP_DOCUMENTS, CAP_PER_DOCUMENT, CAP_TOTAL, ORIGIN_REFERENCE, ORIGIN_SEMANTIC,
    REFUSAL_CODE, expand,
)
from engine.retrieval.index import build_index, load_index  # noqa: E402
from engine.retrieval.layout import EMBEDDING_DIM  # noqa: E402
from engine.retrieval.search import Hit, SearchResult, search  # noqa: E402

NEW_757, OLD_757 = "2026-21113", "2019-21760"
OTHER_737, AIRBUS = "2026-20998", "2026-20777"
#: Holds the work the new AD requires; reachable only through its (g) reference.
NEEDED = f"{OLD_757}#(g)"
BULLETIN, FOREIGN = "BOEING-757-25-0320-RB-R1", "EASA-2025-0208"

#: ``revision_id -> (ad_number, is_current, superseded_by, [(label, role,
#: heading + body)])``, worded like the real corpus.
_DOCUMENTS: dict[str, tuple[str, bool, str | None, list[tuple[str, str, str]]]] = {
    "2026-21113": ("2026-21-13", True, None, [
        ("(a)", "EFFECTIVE_DATE", "Effective Date\nThis AD is effective December 1, 2026."),
        ("(b)", "AFFECTED_ADS", "Affected ADs\nThis AD replaces AD 2019-20-07, Amendment 39-19760 (84 FR 54765, October 11, 2019) (AD 2019-20-07)."),
        ("(c)", "APPLICABILITY", "Applicability\nThis AD applies to The Boeing Company Model 757-200 and -300 series airplanes, certificated in any category,"
         " equipped with a fuel quantity indication system wire bundle routed through the center fuel tank."),
        ("(e)", "UNSAFE_CONDITION", "Unsafe Condition\nThis AD was prompted by reports of chafing of the fuel quantity indication system wiring. The FAA is issuing"
         " this AD to prevent an ignition source inside the center fuel tank of the Boeing 757."),
        ("(g)", "REQUIRED_ACTIONS", "Required Actions\nExcept as specified in paragraph (h) of this AD, do all the actions required by paragraphs (g) through (k) of"
         " AD 2019-20-07, including all subparagraphs, at the times specified in Boeing Special Attention Requirements"
         " Bulletin 757-25-0320 RB, Revision 1, dated August 6, 2025."),
    ]),
    "2019-21760": ("2019-20-07", False, "2026-21113", [
        ("(c)", "APPLICABILITY", "Applicability\nThis AD applies to The Boeing Company Model 757-200 series airplanes, certificated in any category."),
        ("(g)", "REQUIRED_ACTIONS", "Required Actions\nInstall a wire bundle support bracket at station 180 and reroute the P5-2 overhead panel bundle clear of the"
         " hydraulic return line, in accordance with the Accomplishment Instructions of the applicable service"
         " information."),
        ("(h)", "COMPLIANCE", "Compliance\nComply with this AD within 120 days after the effective date of this AD."),
    ]),
    "2026-20998": ("2026-20-98", True, None, [
        ("(c)", "APPLICABILITY", "Applicability\nThis AD applies to The Boeing Company Model 737-800 series airplanes, certificated in any category, equipped"
         " with a fuel quantity indication system of a certain part number."),
        ("(e)", "UNSAFE_CONDITION", "Unsafe Condition\nThis AD was prompted by chafing of the fuel quantity indication system wiring in the center fuel tank, which"
         " could create an ignition source."),
        ("(g)", "REQUIRED_ACTIONS", "Required Actions\nDo a detailed inspection of the fuel quantity indication system wiring for chafing and do all applicable"
         " corrective actions on the Boeing airplane."),
    ]),
    "2026-20777": ("2026-20-77", True, None, [
        ("(c)", "APPLICABILITY", "Applicability\nThis AD applies to Airbus SAS Model A330-941 airplanes, certificated in any category, as identified in"
         " European Union Aviation Safety Agency (EASA) AD 2025-0208, dated September 24, 2025."),
    ]),
}

_EXTERNAL_NODES = {
    FOREIGN: {"ntype": "ForeignAD", "authority": "EASA", "ad_number": "2025-0208",
              "dated": "September 24, 2025", "held": False},
    BULLETIN: {"ntype": "ServiceBulletin", "manufacturer": "Boeing", "held": False,
               "number": "757-25-0320 RB", "revision": "1", "dated": "August 6, 2025"},
}


def _corpus() -> Corpus:
    """Four ADs shaped like the ingest's output. The 757 AD replaces one we hold
    and delegates its compliance times to a bulletin we do not."""
    boeing = normalize_manufacturer("The Boeing Company")
    airbus = normalize_manufacturer("Airbus SAS")
    graph = nx.DiGraph()
    paragraphs: list[Paragraph] = []
    revisions: dict[str, RevisionMeta] = {}
    plain_text: dict[str, str] = {}

    for revision_id, (ad_number, is_current, superseded_by, items) in _DOCUMENTS.items():
        make = airbus if revision_id == AIRBUS else boeing
        revisions[revision_id] = RevisionMeta(
            revision_id, ad_number, f"FAA-{ad_number[:4]}-1000", is_current,
            superseded_by, "2026-12-01")
        graph.add_node(revision_id, ntype="Revision", amendment=None)
        graph.add_node(
            ad_number, ntype="AD", make=make, make_canonical=make,
            current_revision_id=revision_id if is_current else NEW_757)
        graph.add_edge(ad_number, revision_id, etype="HAS_REVISION")
        offset = 0
        for ordinal, (label, role, text) in enumerate(items):
            paragraph_id = f"{revision_id}#{label}"
            paragraphs.append(Paragraph(
                paragraph_id=paragraph_id, revision_id=revision_id, label=label,
                role=role, heading=text.split("\n", 1)[0], text=text,
                char_start=offset, char_end=offset + len(text), ordinal=ordinal,
                ad_number=ad_number, is_current_revision=is_current,
            ))
            offset += len(text) + 2
            graph.add_node(paragraph_id, ntype="Paragraph")
            graph.add_edge(revision_id, paragraph_id, etype=EDGE_HAS_PARAGRAPH)
        plain_text[revision_id] = "\n\n".join(text for _, _, text in items)

    graph.add_nodes_from(_EXTERNAL_NODES.items())
    graph.add_edge(NEW_757, OLD_757, etype=EDGE_SUPERSEDES)
    graph.add_edge(NEW_757, BULLETIN, etype=EDGE_REFERENCES_SB)
    graph.add_edge(AIRBUS, FOREIGN, etype=EDGE_ADOPTS_MCAI)

    return Corpus(
        kind="test", paragraphs=paragraphs, graph=graph, revisions=revisions,
        ad_numbers={m.ad_number: "" for m in revisions.values()}, plain_text=plain_text)


def _stub_embed(texts: list[str]) -> np.ndarray:
    """Deterministic hashed bag of words, L2-normalised. crc32, not hash():
    hash() is salted per process and would move the ranking between runs."""
    matrix = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower()):
            matrix[row, zlib.crc32(token.encode("utf-8")) % EMBEDDING_DIM] += 1.0
        norm = float(np.linalg.norm(matrix[row]))
        if norm:
            matrix[row] /= norm
    return matrix


def _index(corpus: Corpus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The real index over this corpus, embedder stubbed. Both names are patched
    because ``search`` imported ``embed`` into its own namespace; patching one
    would leave query and corpus in different vector spaces."""
    monkeypatch.setattr("engine.retrieval.index.embed", _stub_embed)
    monkeypatch.setattr("engine.retrieval.search.embed", _stub_embed)
    db, npy = tmp_path / "index.db", tmp_path / "embeddings.npy"
    build_index(corpus, db_path=db, embeddings_path=npy, dense=True)
    return load_index(corpus, db_path=db, embeddings_path=npy)


_HIT_FIELDS = ("paragraph_id", "revision_id", "ad_number", "label", "role",
               "heading", "text", "char_start", "char_end")


def _hit(corpus: Corpus, paragraph_id: str, score: float = 0.03) -> Hit:
    record = corpus.by_id[paragraph_id]
    return Hit(
        **{field: getattr(record, field) for field in _HIT_FIELDS},
        score=score, keyword_rank=1, dense_rank=1, dense_cosine=0.5)


def _result(hits: list[Hit]) -> SearchResult:
    return SearchResult(
        hits=hits, filter_report={}, arms=["keyword", "dense"], top_cosine=0.5,
        top_score=hits[0].score if hits else 0.0)


# --- The demonstration: a real search drops it, expansion recovers it. ----

QUERY = "What must be done about the fuel quantity indication system wiring on the Boeing 757?"


def test_expansion_recovers_the_paragraph_the_ranker_dropped(tmp_path, monkeypatch):
    corpus = _corpus()
    index = _index(corpus, tmp_path, monkeypatch)
    entities = extract_entities(QUERY, known_ad_numbers=frozenset(corpus.ad_numbers))

    # revision_scope="all" is retrieval's most generous setting: every paragraph
    # of every revision, superseded ones included, competes.
    ranked = search(index, QUERY, entities, k=5, revision_scope="all", rerank=False)
    scored = search(index, QUERY, entities, k=100, revision_scope="all", rerank=False)
    ranks = {hit.paragraph_id: place for place, hit in enumerate(scored.hits, 1)}

    # The paragraph was in play and was scored...
    assert NEEDED in ranks, "the needed paragraph was never a candidate"
    needed = next(h for h in scored.hits if h.paragraph_id == NEEDED)
    assert needed.keyword_rank or needed.dense_rank
    # ...and lost: the top 5 is full of paragraphs that resemble the question.
    assert len(ranked.hits) == 5
    assert NEEDED not in ranked.paragraph_ids()
    assert ranks[NEEDED] > 5
    assert needed.score < ranked.hits[-1].score

    # Yet it is the only place the work the new AD requires is written down.
    assert [p.paragraph_id for p in corpus.paragraphs if "station 180" in p.text] == [NEEDED]

    expanded = expand(ranked, corpus)

    assert NEEDED in expanded.reference_paragraph_ids()
    recovered = next(p for p in expanded.added if p.paragraph_id == NEEDED)
    assert (recovered.origin, recovered.kind) == (ORIGIN_REFERENCE, KIND_SUPERSESSION)
    assert recovered.referenced_by == OLD_757
    assert "station 180" in recovered.text


def test_the_graph_filter_hides_it_too_when_the_query_names_the_ad(tmp_path, monkeypatch):
    """Asking by AD number makes it worse: the filter narrows to that AD's current
    revision, so the referenced AD's paragraphs are not even candidates."""
    corpus = _corpus()
    query = "What does AD 2026-21-13 require?"
    entities = extract_entities(query, known_ad_numbers=frozenset(corpus.ad_numbers))

    index = _index(corpus, tmp_path, monkeypatch)
    ranked = search(index, query, entities, k=8, rerank=False)

    assert entities.ad_numbers == ["2026-21-13"]
    assert {h.revision_id for h in ranked.hits} == {NEW_757}
    assert NEEDED not in ranked.paragraph_ids()
    assert NEEDED in expand(ranked, corpus).reference_paragraph_ids()


# --- Marking, missing documents, caps. ------------------------------


def test_every_paragraph_says_where_it_came_from():
    corpus = _corpus()
    expanded = expand(_result([_hit(corpus, f"{NEW_757}#(g)")]), corpus)

    assert {p.origin for p in expanded.retrieved} == {ORIGIN_SEMANTIC}
    assert {p.origin for p in expanded.added} == {ORIGIN_REFERENCE}
    # A reference-derived paragraph carries no score: it was never ranked, and
    # must not be comparable with one that was.
    assert all(p.score is None for p in expanded.added)
    assert all(p.score is not None for p in expanded.retrieved)
    assert expanded.reference_paragraph_ids() <= expanded.paragraph_ids()
    payload = json.loads(json.dumps(expanded.as_payload()))
    assert {entry["origin"] for entry in payload["added"]} == {ORIGIN_REFERENCE}

    # And a paragraph the search already returned is not added a second time.
    both = expand(_result([*[_hit(corpus, f"{NEW_757}#(g)")], _hit(corpus, NEEDED)]), corpus)
    assert NEEDED not in both.reference_paragraph_ids()
    ids = [p.paragraph_id for p in both.paragraphs]
    assert len(ids) == len(set(ids))


def test_an_unheld_document_is_named_for_the_refusal():
    """The 757 compliance times live in a bulletin we do not hold; the A330
    applicability is defined inside an EASA AD we do not hold. Both are the
    contract's EXTERNAL_SOURCE_REQUIRED case, and both must be named."""
    corpus = _corpus()

    bulletins = expand(_result([_hit(corpus, f"{NEW_757}#(g)")]), corpus)
    foreign = expand(_result([_hit(corpus, f"{AIRBUS}#(c)")]), corpus)

    assert bulletins.outcome == MISSING_DOCUMENT
    assert bulletins.requires_external_source
    named = {d["identifier"]: d for d in bulletins.external_documents()}
    assert named[BULLETIN]["code"] == REFUSAL_CODE
    assert named[BULLETIN]["label"] == "Boeing 757-25-0320 RB, Revision 1, dated August 6, 2025"
    assert named[BULLETIN]["referenced_by"] == NEW_757
    # A refusal with no evidence is a defect, so one is always supplied.
    assert named[BULLETIN]["evidence_paragraph_ids"]

    easa = {d["identifier"]: d for d in foreign.external_documents()}[FOREIGN]
    assert easa["label"] == "EASA AD 2025-0208, dated September 24, 2025"
    assert easa["evidence_paragraph_ids"] == [f"{AIRBUS}#(c)"]


def test_the_quiet_paths_add_nothing_and_claim_nothing():
    """An AD that references nothing, and a search that returned nothing, are
    both COMPLETE with an empty expansion -- not a silent partial result."""
    corpus = _corpus()

    quiet = expand(_result([_hit(corpus, f"{OTHER_737}#(g)")]), corpus)
    empty = expand(_result([]), corpus)

    assert (quiet.added, quiet.missing) == ((), ())
    assert quiet.outcome == COMPLETE and not quiet.capped
    assert (empty.paragraphs, empty.traversals) == ((), ())
    assert empty.outcome == COMPLETE


def _fan_corpus(fan: int, per_document: int) -> Corpus:
    """One revision superseding ``fan`` others: the flood this layer must cap."""
    roles = ("APPLICABILITY", "COMPLIANCE", "REQUIRED_ACTIONS", "CREDIT", "AMOC")
    graph = nx.DiGraph()
    paragraphs: list[Paragraph] = []
    revisions: dict[str, RevisionMeta] = {}
    for index in range(fan + 1):
        revision_id, ad_number = f"rev-{index:02d}", f"2026-00-{index:02d}"
        revisions[revision_id] = RevisionMeta(
            revision_id, ad_number, None, index == 0, None, None)
        graph.add_node(revision_id, ntype="Revision")
        for ordinal in range(per_document):
            text = f"Paragraph {ordinal} of {revision_id} about inspection work."
            paragraph_id = f"{revision_id}#({ordinal})"
            paragraphs.append(Paragraph(
                paragraph_id=paragraph_id, revision_id=revision_id,
                label=f"({ordinal})", role=roles[ordinal % len(roles)],
                heading="Paragraph", text=text, char_start=0, char_end=len(text),
                ordinal=ordinal, ad_number=ad_number, is_current_revision=index == 0,
            ))
            graph.add_node(paragraph_id, ntype="Paragraph")
            graph.add_edge(revision_id, paragraph_id, etype=EDGE_HAS_PARAGRAPH)
        if index:
            graph.add_edge("rev-00", revision_id, etype=EDGE_SUPERSEDES)
    return Corpus(
        kind="test-fan", paragraphs=paragraphs, graph=graph, revisions=revisions,
        ad_numbers={m.ad_number: "" for m in revisions.values()}, plain_text={})


def test_the_cap_engages_and_reports_what_it_dropped():
    corpus = _fan_corpus(fan=12, per_document=5)

    expanded = expand(
        _result([_hit(corpus, "rev-00#(0)")]), corpus,
        max_documents=6, max_per_document=3, max_added=12)

    assert expanded.capped
    assert set(expanded.cap_reasons) == {CAP_DOCUMENTS, CAP_PER_DOCUMENT, CAP_TOTAL}
    assert len(expanded.documents) == 6
    assert len(expanded.added) == 12
    assert expanded.dropped_documents == 6
    assert expanded.dropped_paragraphs > 0
    assert json.loads(json.dumps(expanded.as_payload()))["capped"] is True

    # Under the caps, nothing is dropped and nothing claims to have been.
    small = _fan_corpus(fan=2, per_document=2)
    roomy = expand(_result([_hit(small, "rev-00#(0)")]), small)
    assert not roomy.capped
    assert roomy.cap_reasons == ()
    assert (roomy.dropped_documents, roomy.dropped_paragraphs) == (0, 0)


def test_the_cap_keeps_the_obligation_bearing_paragraphs_first():
    """When the cap bites, what survives is chosen by the ingest's own role field,
    so applicability and compliance are not dropped for an "Additional
    Information" paragraph."""
    corpus = _fan_corpus(fan=1, per_document=5)

    expanded = expand(_result([_hit(corpus, "rev-00#(0)")]), corpus, max_per_document=2)

    assert [p.role for p in expanded.added] == ["APPLICABILITY", "COMPLIANCE"]


# --- Determinism and error handling. --------------------------------


def test_expansion_is_deterministic():
    corpus = _fan_corpus(fan=8, per_document=4)
    result = _result([_hit(corpus, "rev-00#(0)")])

    first, second = expand(result, corpus), expand(result, corpus)

    assert json.dumps(first.as_payload()) == json.dumps(second.as_payload())


def test_a_result_from_another_build_is_an_error():
    stranger = _hit(_corpus(), f"{NEW_757}#(g)")
    with pytest.raises(ValueError, match="different builds"):
        expand(_result([stranger]), _fan_corpus(fan=1, per_document=1))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"seed_hits": 0}, ">= 1"), ({"max_documents": 0}, ">= 1"),
        ({"max_per_document": 0}, ">= 1"), ({"max_added": 0}, ">= 1"),
        ({"max_depth": -1}, "max_depth"),
    ],
)
def test_a_limit_out_of_range_is_rejected(kwargs, message):
    corpus = _corpus()
    with pytest.raises(ValueError, match=message):
        expand(_result([_hit(corpus, f"{NEW_757}#(g)")]), corpus, **kwargs)


def test_citation_spans_of_added_paragraphs_are_verbatim():
    """The contract's citation invariant holds for a paragraph this layer added,
    exactly as for one the search returned."""
    corpus = _corpus()
    expanded = expand(_result([_hit(corpus, f"{NEW_757}#(g)")]), corpus)

    assert expanded.added
    for added in expanded.added:
        text = corpus.plain_text[added.revision_id]
        assert text[added.char_start : added.char_end] == added.text
        assert added.citation_id.startswith(added.paragraph_id + "@")
