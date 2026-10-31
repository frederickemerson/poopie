"""A document the user loaded is retrievable, citable, and never law.

The engine ships with 2,117 FAA airworthiness directives. A user may add their
own material -- another regulation, a CFR part, a service bulletin, an EASA AD,
their own notes -- and the engine must be able to find it and cite it. What it
must never do is let that material answer "what must I do, by when" as though
the FAA had published it.

Four layers, in the order they would have to be broken.

1. **The contract.** ``USER_DOCUMENT`` is a declared ``source_kind``,
   ``UserDocument`` is a declared node type, and a Paragraph can name a user
   document as its parent. Nothing invents vocabulary.
2. **The boundary.** Size, media type, encoding and XML shape are refused
   structurally. An upload is data: never executed, never over a build
   artifact, never a path the client chose.
3. **The fence.** ``may_establish_obligation`` admits ``REVISION`` only, at
   every stage, whatever the uploader declared. This is the layer the rest is
   decoration without.
4. **Retrieval and citation.** The document is really in the index and really
   comes back, its citation carries the uploader's title and no Federal
   Register citation, and the answer writer never sees it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import contract, enum, node_types  # noqa: E402
from engine.api.citations import (  # noqa: E402
    NOT_RECORDED,
    HumanReference,
    ReferenceBook,
    reference_dicts,
)
from engine.api.library import Library, VectorCache  # noqa: E402
from engine.graph.stage import (  # noqa: E402
    EFFECTIVE,
    OBLIGATION_BEARING_SOURCE_KINDS,
    PROPOSED,
    SOURCE_KIND_NPRM,
    SOURCE_KIND_REVISION,
    SOURCE_KIND_USER_DOCUMENT,
    may_establish_obligation,
    obligation_refusal,
    split_obligation_evidence,
)
from engine.ingest import user_documents as user_docs  # noqa: E402
from engine.ingest.user_parse import (  # noqa: E402
    MAX_PARAGRAPHS,
    MAX_UPLOAD_BYTES,
    UploadRejected,
    decode,
    parse,
    resolve_media_type,
    safe_filename,
)
from engine.retrieval.corpus import Paragraph, load_corpus  # noqa: E402
from engine.retrieval.graph_filter import (  # noqa: E402
    ALL_SOURCE_KINDS,
    DEFAULT_SOURCE_KINDS,
    EVERY_SOURCE_KIND,
    USER_DOCUMENTS_ONLY,
    filter_candidates,
)
from engine.retrieval.index import (  # noqa: E402
    IndexNotExtendable,
    build_index,
    load_index,
)

BUILD = ROOT / "data" / "build"

#: A service bulletin that reads exactly like an AD: a section called
#: Applicability, a section called Required actions, and a compliance time in
#: flight hours. The point of using this shape is that no amount of reading the
#: text can tell it from a rule, which is why the fence turns on source_kind.
SERVICE_BULLETIN = """# Applicability

This service bulletin applies to Model 737-800 airplanes, line numbers 1
through 400 inclusive.

# Required actions

Within 500 flight hours after the effective date of this bulletin, inspect the
forward engine mount attach fitting for zorblatt cracking using the procedure
in Section 3 of this bulletin.

# Credit for previous actions

Inspections accomplished before the effective date of this bulletin are
acceptable.
"""

#: A token that appears in the bulletin above and nowhere in the FAA corpus, so
#: a query containing it retrieves the user document and nothing else.
ONLY_IN_THE_UPLOAD = "zorblatt"


def _upload(library: Library, *, stage: str = EFFECTIVE, **over) -> dict:
    payload = dict(
        title="Boeing SB 737-54A1111 Revision 2",
        authority="Boeing Commercial Airplanes",
        document_stage=stage,
        filename="sb-737-54A1111.md",
    )
    payload.update(over)
    return library.add(SERVICE_BULLETIN.encode("utf-8"), **payload)


def _user_paragraph(stage: str = EFFECTIVE, **over) -> Paragraph:
    base = dict(
        paragraph_id="USERDOC-abc123def456#p2",
        revision_id=None,
        label="p2",
        role="OTHER",
        heading="Required actions",
        text="Within 500 flight hours, inspect the forward engine mount fitting.",
        char_start=0,
        char_end=10,
        ordinal=1,
        user_document_id="USERDOC-abc123def456",
        source_kind=SOURCE_KIND_USER_DOCUMENT,
        document_stage=stage,
    )
    base.update(over)
    return Paragraph(**base)


# =====================================================================
# Layer 1: the contract declares the vocabulary
# =====================================================================


def test_user_document_is_a_contract_source_kind():
    assert SOURCE_KIND_USER_DOCUMENT in enum("source_kind")


def test_the_user_document_node_type_carries_its_provenance():
    """The bytes a citation came from must be pinned, as they are for a Revision."""
    fields = set(node_types()["UserDocument"]["fields"])
    for required in (
        "user_document_id",
        "title",
        "authority",
        "document_stage",
        "content_sha256",
        "source_bytes",
        "uploaded_at",
        "rules_extracted",
        "unparsed_reason",
    ):
        assert required in fields, f"UserDocument must carry {required}"


def test_the_user_document_invariant_permits_citation_but_forbids_obligation():
    """The contract has to do both at once, like the NPRM invariant above it.

    Deleting the invariant is the easy way to make uploads useful, and refusing
    uploads is the easy way to keep it. Neither is acceptable.
    """
    invariant = next(
        i for i in contract()["invariants"] if i.startswith("A USER_DOCUMENT")
    )
    lowered = invariant.lower()
    assert "may be indexed" in lowered, "user documents must be indexable"
    assert "cited" in lowered, "user documents must be citable"
    assert "not recorded" in lowered, "their absent FR fields must be stated"
    assert "obligation" in lowered and "no user_document" in lowered
    assert "deadline" in lowered, "the invariant must forbid supplying a deadline"
    assert "default retrieval scope" in lowered


# =====================================================================
# Layer 2: the upload boundary
# =====================================================================


def test_an_oversized_upload_is_refused_on_the_bytes_read():
    with pytest.raises(UploadRejected, match="limit"):
        decode(b"x" * (MAX_UPLOAD_BYTES + 1))


def test_binary_content_in_a_text_file_is_refused():
    with pytest.raises(UploadRejected, match="NUL"):
        decode(b"plain text\x00\x01binary")


def test_undecodable_bytes_are_refused_not_repaired():
    """A replacement character would put text in a citation that is not in the
    user's document, so the upload is refused instead."""
    with pytest.raises(UploadRejected, match="UTF-8"):
        decode(b"valid then \xff\xfe invalid")


def test_pdf_is_refused_by_name_with_the_reason():
    """And by extension alone: a browser does not reliably declare a type, and
    the upload form deliberately does not send one, so the generic "cannot tell
    what this is" message would be what a user who picked a PDF actually saw."""
    with pytest.raises(UploadRejected, match="PDF is not supported"):
        resolve_media_type("part25.pdf", "application/pdf")
    with pytest.raises(UploadRejected, match="PDF is not supported"):
        resolve_media_type("part25.pdf", None)
    with pytest.raises(UploadRejected, match="Word documents"):
        resolve_media_type("bulletin.docx", None)


def test_an_unknown_type_is_refused_rather_than_sniffed():
    with pytest.raises(UploadRejected, match="not supported|cannot tell"):
        resolve_media_type("payload.sh", None)


def test_a_filename_cannot_carry_a_path():
    """The stored copy is named from the content hash, so this is about what gets
    rendered -- but a filename that still looks like a path would be rendered."""
    assert "/" not in safe_filename("../../etc/passwd")
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\\\windows\\\\system32\\\\x.txt") == "x.txt"


def test_xml_with_a_dtd_is_refused_so_xxe_and_entity_expansion_cannot_run():
    """An external entity reads a local file; a nested one expands to gigabytes.

    Both arrive through a DTD, so the DTD itself is refused rather than the
    damage being bounded after the fact.
    """
    xxe = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE doc [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
        "<doc>&secret;</doc>"
    )
    with pytest.raises(UploadRejected, match="DTD"):
        parse(decode(xxe.encode("utf-8")), "application/xml")

    billion_laughs = (
        '<?xml version="1.0"?>'
        "<!DOCTYPE lolz [<!ENTITY lol 'lol'>"
        "<!ENTITY lol2 '&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;'>]>"
        "<lolz>&lol2;</lolz>"
    )
    with pytest.raises(UploadRejected, match="DTD"):
        parse(decode(billion_laughs.encode("utf-8")), "application/xml")


def test_xml_without_a_dtd_parses_into_paragraphs():
    parsed = parse(
        decode(b"<sb><title>SB 1</title><p>Inspect the cable.</p></sb>"),
        "application/xml",
    )
    assert [p.text for p in parsed.paragraphs] == ["SB 1", "Inspect the cable."]


def test_paragraph_offsets_round_trip_into_the_plain_text():
    """A one-character offset error corrupts every citation on the document."""
    for media_type, body in (
        ("text/markdown", SERVICE_BULLETIN),
        ("text/plain", "First block.\n\nSecond block.\n\nThird."),
        ("application/xml", "<d><p>One.</p><p>Two.</p></d>"),
    ):
        parsed = parse(decode(body.encode("utf-8")), media_type)
        assert parsed.paragraphs
        for paragraph in parsed.paragraphs:
            span = parsed.plain_text[paragraph.char_start : paragraph.char_end]
            assert span == paragraph.text, f"{media_type} {paragraph.label}"


def test_too_many_paragraphs_is_refused():
    body = "\n\n".join(f"Paragraph {n}." for n in range(MAX_PARAGRAPHS + 1))
    with pytest.raises(UploadRejected, match="the limit is"):
        parse(body, "text/plain")


def test_an_unknown_document_stage_is_refused():
    with pytest.raises(UploadRejected, match="document_stage"):
        user_docs.build(
            b"text",
            title="t",
            authority="a",
            document_stage="IN_FORCE_PROBABLY",
            filename="t.txt",
        )


def test_the_same_bytes_always_get_the_same_id_and_the_id_pins_them():
    first, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="one name",
        authority="Boeing",
        document_stage=EFFECTIVE,
        filename="a.md",
    )
    second, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="a different name",
        authority="Airbus",
        document_stage=PROPOSED,
        filename="b.md",
    )
    assert first.user_document_id == second.user_document_id
    assert first.user_document_id.startswith(user_docs.ID_PREFIX)
    assert first.node["content_sha256"] == second.node["content_sha256"]
    assert first.user_document_id.endswith(first.node["content_sha256"][:12])


def test_no_applicability_rule_is_extracted_and_the_node_says_so():
    """Marked unparsed rather than guessed at. An extractor pointed at an
    arbitrary upload would manufacture conditions from a document that cannot
    establish any."""
    document, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="SB",
        authority="Boeing",
        document_stage=EFFECTIVE,
        filename="a.md",
    )
    assert document.node["rules_extracted"] is False
    assert document.node["unparsed_reason"]


def test_every_paragraph_of_a_user_document_is_role_other():
    """A bulletin's "Applicability" heading is not an AD's "(c) Applicability".

    Giving it that role would make the user's own heading look like the
    structure the rules extractor reads.
    """
    document, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="SB",
        authority="Boeing",
        document_stage=EFFECTIVE,
        filename="a.md",
    )
    headings = [p["heading"] for p in document.paragraphs]
    assert "Applicability" in headings, "the heading itself is kept verbatim"
    assert {p["role"] for p in document.paragraphs} == {"OTHER"}


def test_a_paragraph_names_exactly_one_parent():
    document, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="SB",
        authority="Boeing",
        document_stage=EFFECTIVE,
        filename="a.md",
    )
    for record in document.paragraphs:
        assert record["revision_id"] is None
        assert record["nprm_id"] is None
        assert record["user_document_id"] == document.user_document_id
        assert record["source_kind"] == SOURCE_KIND_USER_DOCUMENT


def test_the_store_writes_only_inside_its_own_directory(tmp_path):
    document, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="SB",
        authority="Boeing",
        document_stage=EFFECTIVE,
        filename="a.md",
    )
    user_docs.append(document, SERVICE_BULLETIN.encode("utf-8"), directory=tmp_path)
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert written == {
        "paragraphs.jsonl",
        "text.jsonl",
        "nodes.jsonl",
        f"uploads/{document.user_document_id}.md",
    }
    # The bytes are kept byte for byte, which is what content_sha256 claims.
    stored = (tmp_path / "uploads" / f"{document.user_document_id}.md").read_bytes()
    assert stored == SERVICE_BULLETIN.encode("utf-8")


def test_a_torn_append_is_not_served(tmp_path):
    """Paragraphs are written before the node, so a crash between them leaves an
    upload that did not happen -- never one that half did."""
    document, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="SB",
        authority="Boeing",
        document_stage=EFFECTIVE,
        filename="a.md",
    )
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "paragraphs.jsonl").write_text(
        "\n".join(json.dumps({"_type": "Paragraph", **r}) for r in document.paragraphs),
        encoding="utf-8",
    )
    store = user_docs.load(tmp_path)
    assert store.documents == []
    assert len(store.orphan_paragraphs) == len(document.paragraphs)


# =====================================================================
# Layer 3: the obligation fence
# =====================================================================


def test_a_user_document_paragraph_can_never_establish_an_obligation():
    """THE test.

    Every contract ``document_stage``, including the one an uploader is most
    likely to declare. If this ever returns True, a service bulletin someone
    dropped into a form can answer "what must I do by when" as though the FAA
    had published it, and every other guarantee in this file is decoration.
    """
    for stage in enum("document_stage"):
        assert may_establish_obligation(SOURCE_KIND_USER_DOCUMENT, stage) is False, (
            f"a USER_DOCUMENT paragraph staged {stage} was admitted as the basis "
            f"of an obligation"
        )
        reason = obligation_refusal(SOURCE_KIND_USER_DOCUMENT, stage)
        assert reason and "user" in reason.lower()


def test_the_uploader_declaring_effective_changes_nothing():
    """The stage is the uploader's claim, and the fence does not consult it.

    An operator's EASA AD may genuinely be in force in its own jurisdiction.
    This engine has verified nothing about it, so a form field must not be the
    thing that turns a sentence into a requirement.
    """
    assert may_establish_obligation(SOURCE_KIND_USER_DOCUMENT, EFFECTIVE) is False
    assert may_establish_obligation(SOURCE_KIND_REVISION, EFFECTIVE) is True


def test_only_an_adopted_revision_bears_an_obligation():
    assert OBLIGATION_BEARING_SOURCE_KINDS == frozenset({SOURCE_KIND_REVISION})


def test_every_contract_source_kind_is_ruled_on():
    """A fourth kind added to the contract must fail rather than default in.

    ``engine.graph.stage`` raises at import if it has not classified every
    ``source_kind``; this asserts the classification is actually exhaustive, so
    the next person to widen the enum has to decide what it may ground.
    """
    ruled_on = {SOURCE_KIND_REVISION, SOURCE_KIND_NPRM, SOURCE_KIND_USER_DOCUMENT}
    assert set(enum("source_kind")) == ruled_on
    for kind in enum("source_kind"):
        bearing = may_establish_obligation(kind, EFFECTIVE)
        assert bearing is (kind in OBLIGATION_BEARING_SOURCE_KINDS)


def test_split_obligation_evidence_sets_aside_the_user_document_with_a_reason():
    adopted = Paragraph(
        "2026-21-13#g", "2026-21902", "g", "REQUIRED_ACTIONS", "Required actions",
        "Inspect within 500 flight hours.", 0, 10, 5,
        source_kind=SOURCE_KIND_REVISION, document_stage=EFFECTIVE,
    )
    user = _user_paragraph()
    eligible, excluded = split_obligation_evidence([user, adopted])
    assert [p.paragraph_id for p in eligible] == ["2026-21-13#g"]
    assert len(excluded) == 1
    assert excluded[0]["paragraph_id"] == user.paragraph_id
    assert excluded[0]["source_kind"] == SOURCE_KIND_USER_DOCUMENT
    assert "user" in excluded[0]["reason"].lower()


# =====================================================================
# Layer 3b: the retrieval scope
# =====================================================================


def test_user_documents_are_not_in_the_default_retrieval_scope():
    """The deliberate decision, pinned.

    A question about what an operator must do is answered from the default
    scope. Admitting a document that cannot ground an obligation into the set a
    compliance answer is drawn from would be a regression on exactly the
    answers that matter.
    """
    assert SOURCE_KIND_USER_DOCUMENT not in DEFAULT_SOURCE_KINDS


def test_every_kind_in_the_default_scope_can_bear_an_obligation():
    """The fence and the scope must agree. This is the test that fails if
    someone adds USER_DOCUMENT to the default scope for convenience."""
    for kind in DEFAULT_SOURCE_KINDS:
        assert may_establish_obligation(kind, EFFECTIVE) is True


def test_widening_to_all_faa_documents_does_not_silently_include_uploads():
    """``ALL_SOURCE_KINDS`` means "the Federal Register, all of it".

    Existing call sites pass it to mean adopted rules plus proposals. Quietly
    widening what it covers would widen every one of them at once.
    """
    assert SOURCE_KIND_USER_DOCUMENT not in ALL_SOURCE_KINDS
    assert SOURCE_KIND_USER_DOCUMENT in EVERY_SOURCE_KIND
    assert USER_DOCUMENTS_ONLY == (SOURCE_KIND_USER_DOCUMENT,)


def test_the_shipped_corpus_holds_no_user_paragraph_by_default():
    """``load_corpus`` must not grow because somebody uploaded something: the
    shipped index is fingerprinted against this exact paragraph list."""
    corpus = load_corpus()
    assert SOURCE_KIND_USER_DOCUMENT not in corpus.counts_by_source_kind()
    assert corpus.user_documents == {}


# =====================================================================
# Layer 4: it is really in the index, really comes back, really cited as yours
# =====================================================================


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A real corpus and a real index, in a temp directory, with one upload.

    The index is built keyword-only so the test does not need the embedding
    model; the dense arm is exercised separately against a tiny matrix. The
    store is redirected into ``tmp_path``, so no test writes into the real
    library.
    """
    corpus = load_corpus(prefer_fixture=True)
    db, npy = tmp_path / "ix.db", tmp_path / "ix.npy"
    build_index(corpus, db_path=db, embeddings_path=npy, dense=False)
    index = load_index(corpus, db_path=db, embeddings_path=npy)
    monkeypatch.setattr(user_docs, "DIRECTORY", tmp_path / "library")
    book = ReferenceBook.load(
        load_corpus.__globals__["default_corpus_paths"](prefer_fixture=True).nodes
    )
    loaded = Library(corpus, index, book)
    assert loaded.attach()["documents"] == 0
    report = _upload(loaded)
    assert report["status"] == "loaded"
    return loaded


def test_the_upload_is_retrievable(library):
    found = library.search(f"{ONLY_IN_THE_UPLOAD} cracking inspection")
    assert found["hits"], "the uploaded document did not come back from retrieval"
    assert all(h["source_kind"] == SOURCE_KIND_USER_DOCUMENT for h in found["hits"])
    assert any(ONLY_IN_THE_UPLOAD in h["text"] for h in found["hits"])


def test_every_retrieved_user_paragraph_is_refused_as_a_basis_for_an_obligation(library):
    """Retrievable AND inadmissible, on the same hits, in one test.

    Being findable and being able to impose a requirement are different
    properties, and the whole feature rests on the engine holding both at once.
    """
    found = library.search(f"{ONLY_IN_THE_UPLOAD} cracking inspection")
    assert found["hits"]
    for hit in found["hits"]:
        assert hit["establishes_obligation"] is False
        assert hit["obligation_refusal"]
        assert (
            may_establish_obligation(hit["source_kind"], hit["document_stage"]) is False
        )
    assert "not FAA airworthiness directives" in found["limitation"]


def test_the_default_scope_still_returns_no_upload_after_one_is_loaded(library):
    """The regression guard: an upload must not reach a compliance answer."""
    from engine.retrieval.entities import Entities

    result = filter_candidates(library.corpus, Entities())
    assert result.paragraph_ids
    by_id = library.corpus.by_id
    offenders = [
        pid for pid in result.paragraph_ids if by_id[pid].is_user_document
    ]
    assert not offenders, f"{len(offenders)} user paragraph(s) in the default scope"
    assert result.as_report()["user_documents"] == 0


def test_the_citation_names_the_uploader_and_invents_no_federal_register_cite(library):
    found = library.search(f"{ONLY_IN_THE_UPLOAD} cracking inspection")
    reference = found["hits"][0]["human_reference"]

    assert reference["source_kind"] == SOURCE_KIND_USER_DOCUMENT
    assert reference["is_user_document"] is True
    assert reference["handle"] == "Boeing SB 737-54A1111 Revision 2"
    assert reference["authority"] == "Boeing Commercial Airplanes"
    # No fabricated Federal Register identity, and the absences are NAMED
    # through the existing mechanism rather than left blank.
    assert reference["fr_citation"] is None
    assert reference["page_range"] is None
    assert reference["ad_number"] is None
    assert reference["record_id"] is None
    assert reference["federal_register_link"] is None
    assert set(reference["not_recorded"]) == {
        "ad_number",
        "record_id",
        "fr_citation",
        "page_range",
    }
    assert NOT_RECORDED in reference["display"]
    assert "loaded by you" in reference["display"]
    assert "not verified" in reference["display"]
    assert reference["establishes_obligation"] is False
    assert reference["obligation_refusal"]
    # And it is a real HumanReference, so it could not have been built without
    # a contract document_stage.
    assert reference["document_stage"] in enum("document_stage")


def test_a_user_citation_survives_the_envelope_s_reference_renderer(library):
    """``build_envelope`` renders citations through ``reference_dicts``, which
    refuses anything that is not a ``HumanReference`` -- the only reason the
    engine can promise every rendered citation shows its stage."""
    citation_id = library.search(f"{ONLY_IN_THE_UPLOAD} cracking")["hits"][0][
        "human_reference"
    ]["citation_id"]
    resolve = library.references.reference
    assert isinstance(resolve(citation_id), HumanReference)
    rendered = reference_dicts(resolve, [citation_id])
    assert rendered[0]["is_user_document"] is True
    assert "fr_citation" in rendered[0]["not_recorded"]


def test_an_faa_citation_is_unaffected_by_the_library_book(library):
    """The wrapper must not change how an adopted AD resolves."""
    adopted = next(p for p in library.corpus.paragraphs if p.is_adopted_revision)
    through_library = library.references.reference(adopted.citation_id)
    direct = ReferenceBook(
        library.references.revisions, library.references.nprms
    ).reference(adopted.citation_id)
    assert through_library.as_dict() == direct.as_dict()


def test_reloading_the_same_bytes_changes_nothing(library):
    before = len(library.corpus.paragraphs)
    again = _upload(library)
    assert again["status"] == "already_loaded"
    assert len(library.corpus.paragraphs) == before


def test_the_shipped_build_artifacts_are_never_written(library, tmp_path):
    """Nothing the library does may touch data/build.

    Checked as a fact about the index connection and the store directory rather
    than by diffing mtimes: the index this library writes to is a copy, and the
    store is under tmp_path.
    """
    assert library.index is not None
    assert library.index.writable is True
    assert BUILD not in Path(library.index.db_path).parents
    assert tmp_path in library.directory.parents or library.directory.parent == tmp_path
    for path in tmp_path.rglob("*"):
        assert BUILD not in path.parents


# ----------------------------------------------------- the writer's evidence


def _serve(server, library, monkeypatch, *, permissive_gate: bool = False) -> None:
    """Point the server's process-wide state at this test's corpus and index."""
    from engine.api.applicability import ApplicabilityStore
    from engine.llm.client import LLMClient
    from engine.llm.ledger import CostLedger
    from engine.verify.gate import GateResult

    monkeypatch.setattr(server.STATE, "corpus", library.corpus)
    monkeypatch.setattr(server.STATE, "index", library.index)
    monkeypatch.setattr(server.STATE, "references", library.references)
    monkeypatch.setattr(server.STATE, "library", library)
    monkeypatch.setattr(server.STATE, "applicability", ApplicabilityStore.load())
    monkeypatch.setattr(
        server.STATE, "client", LLMClient(CostLedger(cap_usd=0.0), offline=True)
    )
    monkeypatch.setattr(server.STATE, "error", None)
    if permissive_gate:
        # The refusal gate and the rules engine's own refusals are different
        # guarantees, tested in test_gate.py and test_rules.py. Both are held
        # open here so the stream actually reaches the answer writer --
        # otherwise this test would pass by never getting that far, which is
        # exactly the vacuous green the fence must not be proven with. (With
        # no tail number the rules engine refuses NEED_CONFIG on every query,
        # which has nothing to do with what is being tested.)
        from engine.api.applicability import ApplicabilityOutcome

        monkeypatch.setattr(server, "evaluate_gate", lambda *a, **k: GateResult())
        monkeypatch.setattr(
            server,
            "decide_for_query",
            lambda *a, **k: ApplicabilityOutcome(
                None, "held open by the test; see test_rules.py for this path"
            ),
        )


def test_the_answer_writer_never_sees_a_user_paragraph(library, monkeypatch):
    """End to end through the real stream, with the writer instrumented.

    The writer's prompt calls its inputs "paragraphs retrieved from adopted FAA
    ADs" and the verifier only checks that a quote is verbatim in a retrieved
    paragraph. So nothing downstream of the writer would catch a user document
    being handed to it, and this is where that is proven not to happen -- with
    retrieval explicitly widened to include uploads, the gate held open, and the
    user document provably in the retrieved set.
    """
    import engine.api.server as server
    from engine.api.answer import AnswerOutcome

    seen: list[list] = []

    def capture(client, question, hits, *, stage_note=None):
        seen.append(list(hits))
        return AnswerOutcome(reason="captured by the test; no model was called")

    monkeypatch.setattr(server, "write_answer", capture)
    _serve(server, library, monkeypatch, permissive_gate=True)

    # A query that matches both the upload (via its unique token) and the FAA
    # corpus (via "cracking"), so the retrieved set really is mixed and the
    # writer really does have a user paragraph in front of it to be kept from.
    question = f"{ONLY_IN_THE_UPLOAD} cracking inspection"
    body = "".join(server._stream(question, None, include_user_documents=True))

    retrieved = json.loads(
        next(
            line[len("data: ") :]
            for line in body.splitlines()
            if line.startswith("data: ") and '"source_kind"' in line
        )
    )
    kinds = {p["source_kind"] for p in retrieved["paragraphs"]}
    assert SOURCE_KIND_USER_DOCUMENT in kinds, (
        "the upload was not retrieved, so this test would prove nothing"
    )
    assert SOURCE_KIND_REVISION in kinds, "no adopted AD was retrieved either"

    assert seen, "the answer writer was never reached, so nothing was proven"
    for hits in seen:
        assert hits, "the writer was handed an empty evidence set"
        for hit in hits:
            assert hit.source_kind != SOURCE_KIND_USER_DOCUMENT, (
                f"{hit.paragraph_id} was handed to the answer writer"
            )
            assert may_establish_obligation(hit.source_kind, hit.document_stage)


def test_a_query_only_the_upload_matches_refuses_instead_of_answering(
    library, monkeypatch
):
    """The upload is the only thing retrieved, so there is no admissible
    evidence at all -- and the engine refuses rather than writing from it.

    The gate is held open, so the refusal under test is the evidence fence and
    not one of the gate's own refusals firing first.
    """
    import engine.api.server as server

    def refuse(*args, **kwargs):
        raise AssertionError("the answer writer was called with no admissible evidence")

    monkeypatch.setattr(server, "write_answer", refuse)
    _serve(server, library, monkeypatch, permissive_gate=True)

    body = "".join(
        server._stream(ONLY_IN_THE_UPLOAD, None, include_user_documents=True)
    )
    assert "USERDOC" in body, "the upload should have been retrieved and shown"
    assert '"code": "NO_EVIDENCE"' in body
    assert "may establish an obligation" in body
    assert '"answer_status": "REFUSED"' in body


# ------------------------------------------------------------ index mechanics


def test_a_paragraph_may_only_be_appended_to_the_index_never_inserted(library):
    """Row *i* of the embedding matrix is ``corpus.paragraphs[i]``.

    Inserting into the middle would shift every later row away from its vector,
    which is a wrong answer with no symptom, so it is refused loudly.
    """
    from engine.retrieval.index import extend_index

    first = library.corpus.paragraphs[0]
    with pytest.raises(IndexNotExtendable, match="already holds"):
        extend_index(library.index, [first], work_db=library.work_db)


def test_a_paragraph_not_in_the_corpus_cannot_be_indexed(library):
    from engine.retrieval.index import extend_index

    with pytest.raises(IndexNotExtendable, match="not in the corpus"):
        extend_index(library.index, [_user_paragraph()], work_db=library.work_db)


def test_a_dense_index_refuses_paragraphs_with_no_vectors(tmp_path, monkeypatch):
    """There is no half-dense index: a matrix shorter than the corpus makes
    every dense query an index error, and zero-padding it would retire the dense
    arm for exactly the new documents, invisibly."""
    from engine.retrieval.corpus import extend_corpus
    from engine.retrieval.index import extend_index

    corpus = load_corpus(prefer_fixture=True)
    db, npy = tmp_path / "ix.db", tmp_path / "ix.npy"
    build_index(corpus, db_path=db, embeddings_path=npy, dense=False)
    index = load_index(corpus, db_path=db, embeddings_path=npy)
    # Give the index a dense arm without going near the real model.
    index.embeddings = np.zeros((len(corpus.paragraphs), 4), dtype=np.float32)
    index.dense_model = "test-only"

    monkeypatch.setattr(user_docs, "DIRECTORY", tmp_path / "library")
    document, _ = user_docs.build(
        SERVICE_BULLETIN.encode("utf-8"),
        title="SB",
        authority="Boeing",
        document_stage=EFFECTIVE,
        filename="a.md",
    )
    report = extend_corpus(
        corpus, user_docs.UserDocumentStore(documents=[document])
    )
    added = [corpus.by_id[pid] for pid in report["paragraphs_added"]]
    with pytest.raises(IndexNotExtendable, match="need embeddings"):
        extend_index(index, added, work_db=tmp_path / "work.db")
    with pytest.raises(IndexNotExtendable, match="shape"):
        extend_index(
            index,
            added,
            vectors=np.zeros((len(added), 3), dtype=np.float32),
            work_db=tmp_path / "work.db",
        )


def test_the_vector_cache_is_keyed_by_paragraph_id_and_reads_back(tmp_path):
    """Keyed, not ordered: an ordered cache that drifts out of step hands a
    paragraph another paragraph's meaning, with no symptom."""
    path = tmp_path / "e.npz"
    vectors = np.random.default_rng(0).random((2, 6), dtype=np.float32)
    VectorCache(path).put(["d#p1", "d#p2"], vectors)

    reread = VectorCache(path)
    assert reread.note is None, reread.note
    assert np.allclose(reread.get(["d#p1", "d#p2"]), vectors)
    # Order is the caller's, not the file's.
    assert np.allclose(reread.get(["d#p2", "d#p1"]), vectors[::-1])
    assert reread.get(["d#p1", "missing"]) is None


def test_a_cache_that_does_not_match_is_reported_not_trusted(tmp_path):
    path = tmp_path / "e.npz"
    path.write_bytes(b"not an npz file")
    cache = VectorCache(path)
    assert cache.note and "recomput" in cache.note
    assert cache.vectors == {}
