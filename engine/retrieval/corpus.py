"""Load the built JSONL into paragraph records and a NetworkX graph.

The graph is what makes "filter first, then search" possible: an AD number, a
docket or a manufacturer narrows the candidate paragraph set by graph traversal
before any scoring runs, so the search arms only ever see paragraphs that could
be a legitimate answer.

A missing corpus file raises ``CorpusUnavailable`` naming the file and the
command that produces it. It is never treated as an empty corpus, because an
empty corpus turns every query into a refusal and would look like a tuning
problem instead of a missing build step.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.graph.normalize import normalize_manufacturer  # noqa: E402
from engine.graph.pages import page_range as fr_page_range  # noqa: E402
from engine.graph.stage import (  # noqa: E402
    PROPOSED,
    SOURCE_KIND_NPRM,
    SOURCE_KIND_REVISION,
    revision_stage,
)
from engine.retrieval.layout import (  # noqa: E402
    CorpusPaths,
    CorpusUnavailable,
    default_corpus_paths,
)

#: Edge endpoint ids are not named in contracts/contract.json (see
#: docs/contract_change_requests.md). Accept the spellings a producer could
#: reasonably use and fail loudly on anything else, rather than skipping edges.
_SRC_KEYS = ("_src", "src", "_src_id", "from")
_DST_KEYS = ("_dst", "dst", "_dst_id", "to")

_PRODUCE = {
    "paragraphs": "python3 -m engine.ingest... (real) or "
    "python3 -m engine.retrieval.fixture_corpus --raw (fixture)",
    "nodes": "the ingest, or engine.retrieval.fixture_corpus",
    "edges": "the ingest, or engine.retrieval.fixture_corpus",
}


@dataclass(frozen=True)
class Paragraph:
    """A contract ``Paragraph`` node plus the document-level facts a hit carries.

    ``revision_id`` is ``None`` for a paragraph of a proposal and ``nprm_id``
    is ``None`` for one of an adopted rule; ``source_kind`` says which, and
    ``document_stage`` travels with every paragraph so no retrieval hit can
    reach a reader without its legal stage attached.

    The first nine fields keep their positions: they are constructed
    positionally elsewhere, and reordering them would silently shuffle a
    paragraph's text into its heading.
    """

    paragraph_id: str
    revision_id: str | None
    label: str
    role: str
    heading: str
    text: str
    char_start: int
    char_end: int
    ordinal: int
    ad_number: str | None = None
    is_current_revision: bool = True
    nprm_id: str | None = None
    source_kind: str = SOURCE_KIND_REVISION
    document_stage: str = "UNKNOWN"
    #: For a proposal: the organizers' record_id and the printed citation, which
    #: is what the rubric asks a citation to name.
    record_id: str | None = None
    fr_citation: str | None = None
    page_range: str | None = None

    @property
    def document_id(self) -> str:
        """The parent document's id -- revision_id, or nprm_id for a proposal."""
        return str(self.revision_id or self.nprm_id)

    @property
    def is_proposal(self) -> bool:
        return self.source_kind == SOURCE_KIND_NPRM

    @property
    def citation_id(self) -> str:
        """The contract's citation id for this paragraph's full span."""
        return f"{self.paragraph_id}@{self.char_start}-{self.char_end}"


@dataclass(frozen=True)
class RevisionMeta:
    revision_id: str
    ad_number: str | None
    docket_id: str | None
    is_current: bool
    superseded_by: str | None
    effective_on: str | None
    #: The Federal Register's own page integers, copied off the node. A hit has
    #: to be able to state where a reader will find the text in print, and the
    #: contract declares no ``page_range`` on a Revision -- only the two
    #: numbers -- so the range is formatted here from them.
    start_page: int | None = None
    end_page: int | None = None


@dataclass(frozen=True)
class NPRMMeta:
    """The proposal-level facts a hit on a proposal needs to be citable."""

    nprm_id: str
    record_id: str | None
    docket_id: str | None
    citation: str | None
    page_range: str | None
    publish_date: str | None
    comments_due_date: str | None
    make: str | None
    product_type: str | None
    fr_document_number: str | None
    federal_register_link: str | None
    ad_number: str | None
    supersedes_ad: str | None


@dataclass
class Corpus:
    """Paragraphs in a fixed order plus the graph that filters them.

    The order is the index order: row *i* of the embedding matrix and rowid
    *i+1* of the FTS5 table are both ``paragraphs[i]``. Nothing may reorder
    this list after an index is built; ``fingerprint`` is checked on load.
    """

    kind: str
    paragraphs: list[Paragraph]
    graph: nx.DiGraph
    revisions: dict[str, RevisionMeta]
    ad_numbers: dict[str, str]
    plain_text: dict[str, str]
    nprms: dict[str, NPRMMeta] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_id = {p.paragraph_id: p for p in self.paragraphs}
        self.row_of = {p.paragraph_id: i for i, p in enumerate(self.paragraphs)}

    def counts_by_source_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for paragraph in self.paragraphs:
            counts[paragraph.source_kind] = counts.get(paragraph.source_kind, 0) + 1
        return counts

    @property
    def fingerprint(self) -> str:
        """Cheap identity of this exact paragraph list, in this exact order."""
        import hashlib

        h = hashlib.sha256()
        for p in self.paragraphs:
            h.update(p.paragraph_id.encode("utf-8"))
            h.update(b"\x00")
        return f"{len(self.paragraphs)}:{h.hexdigest()[:16]}"

    def ids(self) -> list[str]:
        return [p.paragraph_id for p in self.paragraphs]


def _read_jsonl(path: Path, *, what: str) -> list[dict]:
    if not path.exists():
        raise CorpusUnavailable(
            f"{path} does not exist. Produced by: {_PRODUCE.get(what, 'the ingest')}"
        )
    out: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not JSON: {exc}") from exc
    if not out:
        raise CorpusUnavailable(f"{path} exists but holds no records")
    return out


def _endpoint(record: dict, keys: tuple[str, ...], path: Path) -> str:
    for key in keys:
        value = record.get(key)
        if value:
            return str(value)
    raise ValueError(
        f"{path}: edge record {record.get('_type')!r} has no endpoint id under any of "
        f"{list(keys)}; it has {sorted(record)}. Pin the key in contracts/contract.json."
    )


def load_corpus(
    paths: CorpusPaths | None = None, *, prefer_fixture: bool = False
) -> Corpus:
    """Read paragraphs, nodes and edges into a Corpus. Raises if any is absent."""
    paths = paths or default_corpus_paths(prefer_fixture=prefer_fixture)

    para_records = _read_jsonl(paths.paragraphs, what="paragraphs")
    node_records = _read_jsonl(paths.nodes, what="nodes")
    edge_records = _read_jsonl(paths.edges, what="edges")
    # Rule nodes are written by a different producer (engine.rules) into their
    # own file, so they have to be read explicitly. They carry "_type": "Rule"
    # already and go through the same node loop. Without this the graph holds
    # no Rule nodes at all and _revisions_for_models can never narrow by model,
    # which it reports as "no Rule nodes in graph" -- true, and avoidable.
    if paths.rules is not None and paths.rules.exists():
        node_records = node_records + _read_jsonl(paths.rules, what="rules")

    revisions: dict[str, RevisionMeta] = {}
    nprms: dict[str, NPRMMeta] = {}
    ad_make: dict[str, str | None] = {}
    graph = nx.DiGraph()

    for rec in node_records:
        ntype = rec.get("_type")
        if ntype == "Revision":
            rid = rec["revision_id"]
            revisions[rid] = RevisionMeta(
                revision_id=rid,
                ad_number=rec.get("ad_number"),
                docket_id=rec.get("docket_id"),
                is_current=bool(rec.get("is_current")),
                superseded_by=rec.get("superseded_by"),
                effective_on=rec.get("effective_on"),
                start_page=rec.get("start_page"),
                end_page=rec.get("end_page"),
            )
            graph.add_node(
                rid,
                ntype="Revision",
                amendment=rec.get("amendment"),
                fr_citation=rec.get("fr_citation"),
            )
        elif ntype == "NPRM":
            nprm_id = rec["nprm_id"]
            nprms[nprm_id] = NPRMMeta(
                nprm_id=nprm_id,
                record_id=rec.get("record_id"),
                docket_id=rec.get("docket_id"),
                citation=rec.get("citation"),
                page_range=rec.get("page_range"),
                publish_date=rec.get("publish_date"),
                comments_due_date=rec.get("comments_due_date"),
                make=rec.get("make"),
                product_type=rec.get("product_type"),
                fr_document_number=rec.get("fr_document_number"),
                federal_register_link=rec.get("federal_register_link"),
                ad_number=rec.get("ad_number"),
                supersedes_ad=rec.get("supersedes_ad"),
            )
            graph.add_node(
                nprm_id,
                ntype="NPRM",
                make=rec.get("make"),
                make_canonical=normalize_manufacturer(rec.get("make")),
                product_type=rec.get("product_type"),
                record_id=rec.get("record_id"),
            )
        elif ntype == "AD":
            ad = rec["ad_number"]
            ad_make[ad] = rec.get("make")
            graph.add_node(
                ad,
                ntype="AD",
                make=rec.get("make"),
                make_canonical=normalize_manufacturer(rec.get("make")),
                product_type=rec.get("product_type"),
            )
        elif ntype == "Docket":
            graph.add_node(rec["docket_id"], ntype="Docket")
        elif ntype == "Paragraph":
            graph.add_node(rec["paragraph_id"], ntype="Paragraph")
        elif ntype == "Rule":
            graph.add_node(
                rec["rule_id"],
                ntype="Rule",
                field=rec.get("field"),
                operator=rec.get("operator"),
                value=rec.get("value"),
                revision_id=rec.get("revision_id"),
                paragraph_id=rec.get("paragraph_id"),
            )
        elif ntype in {"ForeignAD", "ServiceBulletin"}:
            key = "foreign_ad_id" if ntype == "ForeignAD" else "sb_id"
            graph.add_node(
                rec[key],
                ntype=ntype,
                held=bool(rec.get("held")),
                authority=rec.get("authority"),
                ad_number=rec.get("ad_number"),
                number=rec.get("number"),
                revision=rec.get("revision"),
                dated=rec.get("dated"),
            )

    for rec in edge_records:
        etype = rec.get("_type")
        if not etype:
            raise ValueError(f"{paths.edges}: edge record has no _type: {sorted(rec)}")
        src = _endpoint(rec, _SRC_KEYS, paths.edges)
        dst = _endpoint(rec, _DST_KEYS, paths.edges)
        graph.add_edge(src, dst, etype=etype)

    paragraphs: list[Paragraph] = []
    for rec in para_records:
        rid = rec["revision_id"]
        if not rid:
            raise ValueError(
                f"{paths.paragraphs}: paragraph {rec.get('paragraph_id')!r} has no "
                f"revision_id. This file holds adopted-rule paragraphs only; a "
                f"proposal belongs in {paths.nprm_paragraphs}."
            )
        meta = revisions.get(rid)
        paragraphs.append(
            Paragraph(
                paragraph_id=rec["paragraph_id"],
                revision_id=rid,
                label=rec["label"],
                role=rec["role"],
                heading=rec.get("heading") or "",
                text=rec["text"],
                char_start=int(rec["char_start"]),
                char_end=int(rec["char_end"]),
                ordinal=int(rec.get("ordinal") or 0),
                ad_number=meta.ad_number if meta else None,
                is_current_revision=meta.is_current if meta else True,
                source_kind=SOURCE_KIND_REVISION,
                document_stage=_revision_paragraph_stage(rec, meta),
                fr_citation=_revision_citation(graph, rid),
                # Formatted, not left to the dataclass default. A null here
                # beside a populated fr_citation reads as "the Register did not
                # state the pages", which is a false absence: the numbers are
                # on the Revision node. engine.graph.pages is the same
                # formatter the ingest and the citation layer use.
                page_range=(
                    fr_page_range(meta.start_page, meta.end_page) if meta else None
                ),
            )
        )

    paragraphs.extend(_load_nprm_paragraphs(paths, nprms))

    # Paragraphs live in their own files, not in nodes.jsonl, so NetworkX only
    # ever saw them as auto-created edge endpoints with no attributes. Declare
    # them here -- add_node on an existing node updates it rather than
    # duplicating it -- so a traversal can tell a Paragraph from a Revision and
    # can read a hit's stage straight off the graph.
    for paragraph in paragraphs:
        graph.add_node(
            paragraph.paragraph_id,
            ntype="Paragraph",
            source_kind=paragraph.source_kind,
            document_stage=paragraph.document_stage,
            document_id=paragraph.document_id,
            role=paragraph.role,
        )

    plain_text: dict[str, str] = {}
    if paths.revision_text.exists():
        for rec in _read_jsonl(paths.revision_text, what="revision_text"):
            plain_text[rec["revision_id"]] = rec.get("plain_text") or ""
    if paths.nprm_text is not None and paths.nprm_text.exists():
        for rec in _read_jsonl(paths.nprm_text, what="nprm_text"):
            plain_text[rec["nprm_id"]] = rec.get("plain_text") or ""

    return Corpus(
        kind=paths.kind,
        paragraphs=paragraphs,
        graph=graph,
        revisions=revisions,
        ad_numbers={ad: (make or "") for ad, make in ad_make.items()},
        plain_text=plain_text,
        nprms=nprms,
    )


def _revision_paragraph_stage(rec: dict, meta: RevisionMeta | None) -> str:
    """The stage of an adopted paragraph, recomputed rather than trusted.

    ``document_stage`` is written into the build artifact because the contract
    declares the field, but for an adopted rule it is a function of today's
    date: a revision effective next week is ADOPTED_NOT_YET_EFFECTIVE until it
    is EFFECTIVE, with no rebuild in between. So it is derived here from the
    Revision node's own ``effective_on`` and ``superseded_by``, and the stored
    value is used only when there is no Revision node to derive it from.
    """
    if meta is not None:
        return revision_stage(
            {
                "revision_id": meta.revision_id,
                "effective_on": meta.effective_on,
                "superseded_by": meta.superseded_by,
            }
        )
    return rec.get("document_stage") or "UNKNOWN"


def _revision_citation(graph: nx.DiGraph, revision_id: str) -> str | None:
    data = graph.nodes.get(revision_id) or {}
    return data.get("fr_citation")


def _load_nprm_paragraphs(paths: CorpusPaths, nprms: dict[str, NPRMMeta]) -> list[Paragraph]:
    """Paragraphs of proposals, every one of them staged PROPOSED.

    A build that did not harvest proposal text has no such file, which is a
    smaller corpus and not a broken one, so the absent file returns an empty
    list. The stage is not read from the record: a proposal is a proposal, and
    :func:`engine.graph.stage.nprm_stage` says so unconditionally.
    """
    if paths.nprm_paragraphs is None or not paths.nprm_paragraphs.exists():
        return []
    out: list[Paragraph] = []
    for rec in _read_jsonl(paths.nprm_paragraphs, what="nprm_paragraphs"):
        nprm_id = rec.get("nprm_id")
        if not nprm_id:
            raise ValueError(
                f"{paths.nprm_paragraphs}: paragraph {rec.get('paragraph_id')!r} "
                f"has no nprm_id"
            )
        meta = nprms.get(str(nprm_id))
        out.append(
            Paragraph(
                paragraph_id=rec["paragraph_id"],
                revision_id=None,
                label=rec["label"],
                role=rec["role"],
                heading=rec.get("heading") or "",
                text=rec["text"],
                char_start=int(rec["char_start"]),
                char_end=int(rec["char_end"]),
                ordinal=int(rec.get("ordinal") or 0),
                ad_number=None,
                is_current_revision=False,
                nprm_id=str(nprm_id),
                source_kind=SOURCE_KIND_NPRM,
                document_stage=PROPOSED,
                record_id=meta.record_id if meta else None,
                fr_citation=meta.citation if meta else None,
                page_range=meta.page_range if meta else None,
            )
        )
    return out
