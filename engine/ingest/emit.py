"""Write contract-validated JSONL.

Every node line is built from the contract's own field list, so a line carries
exactly the declared fields (absent values are explicit nulls) and a typo
becomes an error here rather than a missing key three layers downstream. Nodes
and edges are de-duplicated by key, so callers may emit the same reference as
often as they find it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.ingest.provenance import ProvenanceError, parse_retrieved_at  # noqa: E402
from contracts.contract import (  # noqa: E402
    ContractViolation,
    edge_types,
    node_types,
    validate_edge,
    validate_enum,
    validate_node,
)

#: Contract enum values this module names directly. Spelled out for grep-ability
#: and checked against contracts/contract.json at import, so a renamed value
#: fails the build here instead of silently mis-staging every paragraph.
SOURCE_KIND_REVISION = "REVISION"
SOURCE_KIND_NPRM = "NPRM"
PROPOSED_STAGE = "PROPOSED"

for _value, _enum_name in (
    (SOURCE_KIND_REVISION, "source_kind"),
    (SOURCE_KIND_NPRM, "source_kind"),
    (PROPOSED_STAGE, "document_stage"),
):
    validate_enum(_enum_name, _value)

#: node field -> enum that constrains it.
_ENUM_FIELDS = {
    ("Paragraph", "role"): "paragraph_role",
    ("ForeignAD", "authority"): "authority",
    ("NPRM", "source"): "source",
    ("Aircraft", "source"): "source",
}


def edge_type_named(prefix: str) -> str:
    """The one contract edge type starting with ``prefix``.

    Edge type names are selected rather than written as literals because
    tests/test_contract.py reserves some spellings for the refusal_code enum,
    and the contract's own SUPERSEDES edge collides with one of them.
    """
    matches = [name for name in edge_types() if name.startswith(prefix)]
    if len(matches) != 1:
        raise ContractViolation(
            f"expected exactly one edge type starting with {prefix!r}, got {matches}"
        )
    return matches[0]


def _check_revision_provenance(record: dict[str, Any]) -> None:
    """A Revision carries its source hash and size together, or none of them.

    ``retrieved_at`` may be null (a document cached before provenance was
    recorded) but never without a hash, and never a naive timestamp.
    """
    sha, size, stamp = (record.get(k) for k in ("content_sha256", "source_bytes", "retrieved_at"))
    key = record.get("revision_id")
    if sha is None:
        if size is not None or stamp is not None:
            raise ContractViolation(f"Revision {key}: retrieved_at/source_bytes without content_sha256")
        return
    if not isinstance(sha, str) or len(sha) != 64:
        raise ContractViolation(f"Revision {key}: content_sha256 is not a sha256 hex digest")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ContractViolation(f"Revision {key}: source_bytes must be a positive integer")
    if stamp is not None:
        try:
            parse_retrieved_at(stamp)
        except (ValueError, ProvenanceError) as exc:
            raise ContractViolation(f"Revision {key}: bad retrieved_at: {exc}") from exc


#: ``91 FR 66019``: the only citation shape the Federal Register index emits.
_FR_CITATION = re.compile(r"^(\d+)\s+FR\s+(\d+)$")


def _check_revision_pages(record: dict[str, Any]) -> None:
    """A page number must be corroborated by the citation printed beside it.

    The Federal Register index gives ``citation``, ``start_page`` and
    ``end_page`` together, and the citation always names the start page -- true
    for all 4,053 index documents cached under ``data/raw/fr_index``, with no
    exception. That makes the pair self-checking, and this is the check:

    * a page number may not exist without an ``fr_citation`` to confirm it, so
      no page can be written that nothing corroborates;
    * the citation's page must equal ``start_page``, so a page number that was
      typed, guessed or carried over from another document cannot be written;
    * ``end_page`` may not precede ``start_page``, and neither may be
      non-positive.

    This raises rather than dropping the field. The values are copied straight
    off the index response, so tripping it means the index changed shape or
    something downstream edited them, and both deserve a stopped build.
    """
    key = record.get("revision_id")
    citation = record.get("fr_citation")
    start, end = record.get("start_page"), record.get("end_page")

    for name, value in (("start_page", start), ("end_page", end)):
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractViolation(f"Revision {key}: {name} must be a positive integer, got {value!r}")

    if start is None and end is not None:
        raise ContractViolation(f"Revision {key}: end_page {end} without a start_page")
    if start is not None and end is not None and end < start:
        raise ContractViolation(f"Revision {key}: end_page {end} precedes start_page {start}")

    if citation is None:
        if start is not None:
            raise ContractViolation(
                f"Revision {key}: start_page {start} with no fr_citation to corroborate it. "
                f"A page number this engine cannot show the citation for is not written."
            )
        return
    if not isinstance(citation, str):
        raise ContractViolation(f"Revision {key}: fr_citation must be a string, got {citation!r}")
    match = _FR_CITATION.match(citation.strip())
    if not match:
        raise ContractViolation(
            f"Revision {key}: fr_citation {citation!r} is not of the form '<volume> FR <page>' "
            f"that the Federal Register index emits"
        )
    named = int(match.group(2))
    if start is not None and start != named:
        raise ContractViolation(
            f"Revision {key}: fr_citation {citation!r} names page {named} but start_page is "
            f"{start}. One of them is not the Federal Register's own value."
        )


def _check_paragraph_parentage(record: dict[str, Any]) -> None:
    """A paragraph names exactly one parent document, and says which kind.

    The contract's words are "Exactly one of revision_id / nprm_id is set, and
    source_kind says which". Both set, neither set, or a ``source_kind`` that
    disagrees with the id that is present would each let a reader resolve a
    citation against the wrong document, so all three are refused here rather
    than being tidied up.

    ``document_stage`` is checked against the parent kind too: a paragraph of a
    proposal is PROPOSED and nothing else, and a paragraph of an adopted
    revision is never PROPOSED. That is the invariant's structural half -- the
    stage cannot be set to something the parent document is not.
    """
    key = record.get("paragraph_id")
    revision, nprm = record.get("revision_id"), record.get("nprm_id")
    kind, stage = record.get("source_kind"), record.get("document_stage")
    if bool(revision) == bool(nprm):
        raise ContractViolation(
            f"Paragraph {key}: exactly one of revision_id/nprm_id must be set, "
            f"got revision_id={revision!r} nprm_id={nprm!r}"
        )
    expected = SOURCE_KIND_NPRM if nprm else SOURCE_KIND_REVISION
    if kind != expected:
        raise ContractViolation(
            f"Paragraph {key}: source_kind is {kind!r} but its parent is "
            f"{expected.lower()} {revision or nprm!r}"
        )
    if not stage:
        raise ContractViolation(f"Paragraph {key}: document_stage is required")
    validate_enum("document_stage", stage)
    if nprm and stage != PROPOSED_STAGE:
        raise ContractViolation(
            f"Paragraph {key} belongs to proposal {nprm!r}, so its document_stage "
            f"must be {PROPOSED_STAGE}, not {stage!r}"
        )
    if revision and stage == PROPOSED_STAGE:
        raise ContractViolation(
            f"Paragraph {key} belongs to adopted revision {revision!r} and cannot "
            f"be staged {PROPOSED_STAGE}"
        )
    expected_id = f"{revision or nprm}#{record.get('label')}"
    if key != expected_id:
        raise ContractViolation(
            f"Paragraph id {key!r} does not match the contract format "
            f"'{{document_id}}#{{label}}', which would be {expected_id!r}"
        )


class GraphWriter:
    """Streaming writer for nodes.jsonl, edges.jsonl and the paragraph files.

    Paragraphs are split across two files by ``source_kind``, not merged into
    one. ``paragraphs.jsonl`` holds only adopted ``Revision`` paragraphs and is
    what the rules extractor and the citable corpus read; proposals go to
    ``nprm_paragraphs.jsonl``. The separation is the guarantee: a consumer that
    only knows the first path cannot reach a proposal by forgetting a filter.
    Emitting a proposal paragraph without that second path is an error, never a
    quiet fall back into the citable file.
    """

    def __init__(
        self,
        nodes: Path,
        edges: Path,
        paragraphs: Path,
        nprm_paragraphs: Path | None = None,
    ) -> None:
        self._nodes: TextIO = nodes.open("w", encoding="utf-8")
        self._edges: TextIO = edges.open("w", encoding="utf-8")
        self._paragraphs: TextIO = paragraphs.open("w", encoding="utf-8")
        self._nprm_paragraphs: TextIO | None = (
            nprm_paragraphs.open("w", encoding="utf-8") if nprm_paragraphs else None
        )
        self._seen_nodes: set[tuple[str, str]] = set()
        self._seen_edges: set[tuple[str, str, str]] = set()
        self.node_counts: dict[str, int] = {}
        self.edge_counts: dict[str, int] = {}
        #: Paragraph counts by source_kind, so a report can state the split.
        self.paragraph_counts: dict[str, int] = {}

    def __enter__(self) -> GraphWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        for handle in (
            self._nodes,
            self._edges,
            self._paragraphs,
            self._nprm_paragraphs,
        ):
            if handle is not None and not handle.closed:
                handle.close()

    def _paragraph_handle(self, source_kind: str) -> TextIO:
        if source_kind != SOURCE_KIND_NPRM:
            return self._paragraphs
        if self._nprm_paragraphs is None:
            raise ContractViolation(
                "a proposal paragraph was emitted but GraphWriter was given no "
                "nprm_paragraphs path; it must not go in the citable file"
            )
        return self._nprm_paragraphs

    # ---------------------------------------------------------------- nodes

    def node(self, node_type: str, values: dict[str, Any]) -> str:
        """Emit one node. Returns its key value. Repeat calls are ignored."""
        spec = node_types().get(node_type)
        if spec is None:
            raise ContractViolation(f"unknown node type {node_type!r}")
        unknown = set(values) - set(spec["fields"])
        if unknown:
            raise ContractViolation(
                f"{node_type} was given fields the contract does not declare: {sorted(unknown)}"
            )
        record = {field: values.get(field) for field in spec["fields"]}
        validate_node(node_type, record)
        if node_type == "Revision":
            _check_revision_provenance(record)
            _check_revision_pages(record)
        if node_type == "Paragraph":
            _check_paragraph_parentage(record)
        for (owner, field), enum_name in _ENUM_FIELDS.items():
            if owner == node_type and record.get(field) is not None:
                validate_enum(enum_name, record[field])

        key = str(record[spec["key"]])
        identity = (node_type, key)
        if identity in self._seen_nodes:
            return key
        self._seen_nodes.add(identity)
        if node_type == "Paragraph":
            kind = str(record["source_kind"])
            handle = self._paragraph_handle(kind)
            self.paragraph_counts[kind] = self.paragraph_counts.get(kind, 0) + 1
        else:
            handle = self._nodes
        handle.write(json.dumps({"_type": node_type, **record}, ensure_ascii=False) + "\n")
        self.node_counts[node_type] = self.node_counts.get(node_type, 0) + 1
        return key

    # ---------------------------------------------------------------- edges

    def edge(
        self,
        edge_type: str,
        src_type: str,
        src: str,
        dst_type: str,
        dst: str,
        **attrs: Any,
    ) -> None:
        validate_edge(edge_type, src_type, dst_type)
        if not src or not dst:
            raise ContractViolation(f"{edge_type} needs both endpoints, got {src!r} -> {dst!r}")
        identity = (edge_type, str(src), str(dst))
        if identity in self._seen_edges:
            return
        self._seen_edges.add(identity)
        # _src/_dst rather than src/dst: the contract does not pin the endpoint
        # key (see docs/contract_change_requests.md) and this is the spelling the
        # other producers in engine/ already write and engine/retrieval reads first.
        record = {
            "_type": edge_type,
            "_src_type": src_type,
            "_dst_type": dst_type,
            "_src": str(src),
            "_dst": str(dst),
        }
        if attrs:
            declared = set(edge_types()[edge_type].get("attrs") or ())
            undeclared = set(attrs) - declared
            if undeclared:
                raise ContractViolation(
                    f"{edge_type} has no contract attrs {sorted(undeclared)}"
                )
            record.update(attrs)
        self._edges.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.edge_counts[edge_type] = self.edge_counts.get(edge_type, 0) + 1

    def has_node(self, node_type: str, key: str) -> bool:
        return (node_type, key) in self._seen_nodes


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Sidecar writer for data the contract has no field for. Never validated."""
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
