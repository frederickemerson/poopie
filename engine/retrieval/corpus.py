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
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.graph.normalize import normalize_manufacturer  # noqa: E402
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
    """A contract ``Paragraph`` node plus the AD-level facts a hit must carry."""

    paragraph_id: str
    revision_id: str
    label: str
    role: str
    heading: str
    text: str
    char_start: int
    char_end: int
    ordinal: int
    ad_number: str | None = None
    is_current_revision: bool = True

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

    def __post_init__(self) -> None:
        self.by_id = {p.paragraph_id: p for p in self.paragraphs}
        self.row_of = {p.paragraph_id: i for i, p in enumerate(self.paragraphs)}

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

    revisions: dict[str, RevisionMeta] = {}
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
            )
            graph.add_node(rid, ntype="Revision", amendment=rec.get("amendment"))
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
            )
        )

    plain_text: dict[str, str] = {}
    if paths.revision_text.exists():
        for rec in _read_jsonl(paths.revision_text, what="revision_text"):
            plain_text[rec["revision_id"]] = rec.get("plain_text") or ""

    return Corpus(
        kind=paths.kind,
        paragraphs=paragraphs,
        graph=graph,
        revisions=revisions,
        ad_numbers={ad: (make or "") for ad, make in ad_make.items()},
        plain_text=plain_text,
    )
