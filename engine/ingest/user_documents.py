"""Where documents the user loaded are kept, and how they are read back.

The shipped build is read-only to this module. Nothing here opens, truncates or
rewrites anything under ``data/build``: user documents live in
``data/user_documents`` and the corpus loader unions the two. That is not
tidiness, it is the recovery story -- ``make ingest`` and ``make index`` stay
exactly reproducible, and deleting every user document is ``rm -rf`` on one
directory that contains nothing the FAA published.

The layout::

    data/user_documents/
      uploads/USERDOC-<hash>.<ext>   the bytes as uploaded, byte for byte
      nodes.jsonl                    one contract UserDocument node per load
      paragraphs.jsonl               one contract Paragraph node per paragraph
      text.jsonl                     the plain text each paragraph indexes into
      embeddings.npz                 dense vectors, keyed by paragraph_id
      retrieval.db                   a writable copy of the shipped index (see engine.retrieval.index)

Three properties worth stating.

**The id is the content hash.** ``user_document_id`` is ``USERDOC-`` plus the
first twelve hex of the SHA-256 of the uploaded bytes. So loading the same file
twice is idempotent rather than duplicating it, a ``paragraph_id`` is stable
across loads, and the id itself is the proof of which bytes a citation came
from -- the same job ``content_sha256`` does for a Revision.

**The node file is the authority.** Appends go paragraphs, then text, then the
node, so a process killed mid-write leaves a document that simply did not
happen: :func:`load` keys off the nodes and reports paragraphs whose document
node is missing instead of serving them. A half-written upload cannot become a
half-cited answer.

**No rules are extracted.** A user document gets no ``Rule`` and no ``Action``
node, and its node records that in ``unparsed_reason`` rather than leaving the
absence to be read as "this document requires nothing". Extraction is an LLM
pass over FAA AD prose, and running it over an arbitrary upload would
manufacture applicability conditions out of a document that cannot establish
any.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import (  # noqa: E402
    ContractViolation,
    node_types,
    validate_enum,
    validate_node,
)
from engine.graph.stage import SOURCE_KIND_USER_DOCUMENT  # noqa: E402
from engine.ingest.user_parse import (  # noqa: E402
    MAX_AUTHORITY_CHARS,
    MAX_TITLE_CHARS,
    MEDIA_TYPES,
    ParsedUserDocument,
    ParsedUserParagraph,
    UploadRejected,
    clean_line,
    decode,
    parse,
    resolve_media_type,
    safe_filename,
)

NODE_TYPE = "UserDocument"
ID_PREFIX = "USERDOC-"
#: Twelve hex characters of SHA-256. Enough that a collision is not a practical
#: concern at this scale, short enough that a paragraph_id stays readable.
ID_HASH_CHARS = 12

#: Why there are no Rule nodes. Written onto every UserDocument node.
UNPARSED_REASON = (
    "no applicability rule was extracted: a user-supplied document cannot establish "
    "an obligation or an applicability verdict in this engine, so there is nothing "
    "for the rules engine to evaluate and nothing was guessed at"
)

DIRECTORY = ROOT / "data" / "user_documents"
UPLOADS = DIRECTORY / "uploads"
NODES_JSONL = DIRECTORY / "nodes.jsonl"
PARAGRAPHS_JSONL = DIRECTORY / "paragraphs.jsonl"
TEXT_JSONL = DIRECTORY / "text.jsonl"
#: Dense vectors for the paragraphs above, keyed by paragraph_id rather than by
#: row, so file order and matrix order cannot drift apart. Written at upload
#: time so that startup never has to load the embedding model.
EMBEDDINGS_NPZ = DIRECTORY / "embeddings.npz"
#: The writable copy of the retrieval index. The shipped ``retrieval.db`` is
#: never written to; see :func:`engine.retrieval.index.extend_index`.
INDEX_DB = DIRECTORY / "retrieval.db"


class UserDocumentStoreError(RuntimeError):
    """The store on disk cannot be trusted or read."""


@dataclass(frozen=True)
class UserDocument:
    """One loaded document: the contract node, plus its parsed parts."""

    node: dict[str, Any]
    paragraphs: list[dict[str, Any]]
    plain_text: str

    @property
    def user_document_id(self) -> str:
        return str(self.node["user_document_id"])

    @property
    def title(self) -> str:
        return str(self.node.get("title") or self.user_document_id)

    def as_summary(self) -> dict[str, Any]:
        """What a library listing shows, including what this document cannot do.

        ``establishes_obligation`` is in the payload rather than left implicit:
        a listing that shows a title, an authority and a stage and says nothing
        else invites exactly the reading the fence exists to prevent.
        """
        return {
            **self.node,
            "source_kind": SOURCE_KIND_USER_DOCUMENT,
            "stage_declared_by_uploader": self.node.get("document_stage"),
            "establishes_obligation": False,
            "in_default_retrieval_scope": False,
            "characters": len(self.plain_text),
        }


@dataclass
class UserDocumentStore:
    """Every loaded document, in load order, plus what could not be read."""

    documents: list[UserDocument] = field(default_factory=list)
    #: Paragraph records whose document node is absent from nodes.jsonl: a torn
    #: append. Reported, never served.
    orphan_paragraphs: list[str] = field(default_factory=list)
    directory: Path = DIRECTORY

    def __post_init__(self) -> None:
        self.by_id = {d.user_document_id: d for d in self.documents}

    @property
    def paragraphs(self) -> list[dict[str, Any]]:
        return [p for d in self.documents for p in d.paragraphs]

    def as_report(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "documents": len(self.documents),
            "paragraphs": len(self.paragraphs),
            "orphan_paragraphs": len(self.orphan_paragraphs),
            "titles": [d.title for d in self.documents],
        }


def document_id_for(content_sha256: str) -> str:
    if len(content_sha256) != 64:
        raise ValueError("content_sha256 must be a sha256 hex digest")
    return f"{ID_PREFIX}{content_sha256[:ID_HASH_CHARS]}"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ----------------------------------------------------------------- the build


def build(
    raw: bytes,
    *,
    title: str,
    authority: str,
    document_stage: str,
    filename: str | None = None,
    media_type: str | None = None,
    uploaded_at: str | None = None,
) -> tuple[UserDocument, ParsedUserDocument]:
    """Validate, parse and assemble one document. Touches no files.

    Raises :class:`engine.ingest.user_parse.UploadRejected` with a reason the
    uploader can act on. Separated from :func:`append` so the whole upload can
    be refused before anything has been written anywhere.
    """
    resolved_type = resolve_media_type(filename, media_type)
    text = decode(raw)
    clean_title = clean_line(title, limit=MAX_TITLE_CHARS, what="title")
    clean_authority = clean_line(authority, limit=MAX_AUTHORITY_CHARS, what="authority")
    stage = str(document_stage or "").strip().upper()
    try:
        validate_enum("document_stage", stage)
    except ContractViolation as exc:
        raise UploadRejected(f"document_stage: {exc}") from exc

    parsed = parse(text, resolved_type)
    digest = hashlib.sha256(raw).hexdigest()
    document_id = document_id_for(digest)

    node = _node(
        {
            "user_document_id": document_id,
            "title": clean_title,
            "authority": clean_authority,
            "document_stage": stage,
            "source_filename": safe_filename(filename),
            "media_type": resolved_type,
            "content_sha256": digest,
            "source_bytes": len(raw),
            "uploaded_at": uploaded_at or utc_now_iso(),
            "paragraph_count": len(parsed.paragraphs),
            # Always false, and the reason beside it. See the module docstring.
            "rules_extracted": False,
            "unparsed_reason": UNPARSED_REASON,
        }
    )
    paragraphs = [
        _paragraph_record(document_id, stage, paragraph)
        for paragraph in parsed.paragraphs
    ]
    return UserDocument(node=node, paragraphs=paragraphs, plain_text=parsed.plain_text), parsed


def _node(values: dict[str, Any]) -> dict[str, Any]:
    """A contract-validated UserDocument node: exactly the declared fields."""
    fields = node_types()[NODE_TYPE]["fields"]
    unknown = set(values) - set(fields)
    if unknown:
        raise UserDocumentStoreError(
            f"{NODE_TYPE} was given fields the contract does not declare: {sorted(unknown)}"
        )
    record = {name: values.get(name) for name in fields}
    validate_node(NODE_TYPE, record)
    return record


def _paragraph_record(
    document_id: str, stage: str, paragraph: ParsedUserParagraph
) -> dict[str, Any]:
    """A contract-validated Paragraph node parented on a user document."""
    record = {
        "paragraph_id": f"{document_id}#{paragraph.label}",
        "revision_id": None,
        "nprm_id": None,
        "user_document_id": document_id,
        "label": paragraph.label,
        "role": paragraph.role,
        "heading": paragraph.heading,
        "text": paragraph.text,
        "char_start": paragraph.char_start,
        "char_end": paragraph.char_end,
        "ordinal": paragraph.ordinal,
        "source_kind": SOURCE_KIND_USER_DOCUMENT,
        "document_stage": stage,
    }
    validate_node("Paragraph", record)
    validate_enum("paragraph_role", record["role"])
    check_paragraph_parentage(record)
    return record


def check_paragraph_parentage(record: dict[str, Any]) -> None:
    """Exactly one parent id, and a source_kind that names the same parent.

    The three-way form of the check ``engine.ingest.emit`` makes for the FAA's
    own two kinds, kept here because a user document paragraph never goes
    through ``GraphWriter``: that writer truncates the build files, and the
    whole point of this module is that it does not.
    """
    key = record.get("paragraph_id")
    parents = {
        "REVISION": record.get("revision_id"),
        "NPRM": record.get("nprm_id"),
        "USER_DOCUMENT": record.get("user_document_id"),
    }
    present = [kind for kind, value in parents.items() if value]
    if len(present) != 1:
        raise UserDocumentStoreError(
            f"Paragraph {key}: exactly one of revision_id/nprm_id/user_document_id "
            f"must be set, got {present or 'none'}"
        )
    kind = record.get("source_kind")
    if kind != present[0]:
        raise UserDocumentStoreError(
            f"Paragraph {key}: source_kind is {kind!r} but its parent is a "
            f"{present[0]}"
        )
    expected_id = f"{parents[present[0]]}#{record.get('label')}"
    if key != expected_id:
        raise UserDocumentStoreError(
            f"Paragraph id {key!r} does not match the contract format "
            f"'{{document_id}}#{{label}}', which would be {expected_id!r}"
        )


# ----------------------------------------------------------- read and append


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # A torn final line is the one corruption an append-only file
                # can produce, so it is skipped with the position named rather
                # than failing the whole startup.
                raise UserDocumentStoreError(f"{path}:{line_no} is not JSON: {exc}") from exc
    return out


def load(directory: Path = DIRECTORY) -> UserDocumentStore:
    """Every document in the store, in the order they were loaded."""
    nodes = _read_jsonl(directory / NODES_JSONL.name)
    paragraph_records = _read_jsonl(directory / PARAGRAPHS_JSONL.name)
    text_records = _read_jsonl(directory / TEXT_JSONL.name)

    plain_text = {
        str(r.get("user_document_id")): str(r.get("plain_text") or "")
        for r in text_records
    }
    by_document: dict[str, dict[str, dict[str, Any]]] = {}
    known = {str(n.get("user_document_id")) for n in nodes if n.get("user_document_id")}
    orphans: list[str] = []
    for record in paragraph_records:
        parent = str(record.get("user_document_id") or "")
        if parent not in known:
            orphans.append(str(record.get("paragraph_id") or "?"))
            continue
        # Keyed by paragraph_id, so re-appending a document the store already
        # holds cannot double its paragraphs. The id is derived from the content
        # hash, so the later copy is the same text by construction.
        by_document.setdefault(parent, {})[str(record.get("paragraph_id"))] = record

    documents: list[UserDocument] = []
    seen: set[str] = set()
    for node in nodes:
        node = {key: value for key, value in node.items() if key != "_type"}
        document_id = str(node.get("user_document_id") or "")
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        paragraphs = sorted(
            by_document.get(document_id, {}).values(),
            key=lambda r: int(r.get("ordinal") or 0),
        )
        documents.append(
            UserDocument(
                node=node,
                paragraphs=paragraphs,
                plain_text=plain_text.get(document_id, ""),
            )
        )
    return UserDocumentStore(
        documents=documents, orphan_paragraphs=orphans, directory=directory
    )


def _append(path: Path, records: list[dict[str, Any]]) -> None:
    """Append JSONL and flush to disk before returning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append(
    document: UserDocument, raw: bytes, *, directory: Path = DIRECTORY
) -> dict[str, Any]:
    """Persist one document. Order is paragraphs, text, then the node.

    The node goes last because :func:`load` keys off it, so an interruption
    leaves an upload that did not happen rather than one that half did.
    """
    document_id = document.user_document_id
    extension = MEDIA_TYPES[str(document.node["media_type"])]
    uploads = directory / UPLOADS.name
    uploads.mkdir(parents=True, exist_ok=True)
    # The stored name comes from the content hash and an extension off the
    # allow-list -- never from the uploaded filename, which is kept for display
    # only. There is no path component a client can influence.
    target = uploads / f"{document_id}.{extension}"
    if not target.exists():
        target.write_bytes(raw)

    _append(directory / PARAGRAPHS_JSONL.name, [
        {"_type": "Paragraph", **record} for record in document.paragraphs
    ])
    _append(directory / TEXT_JSONL.name, [
        {"user_document_id": document_id, "plain_text": document.plain_text}
    ])
    _append(directory / NODES_JSONL.name, [
        {"_type": NODE_TYPE, **document.node}
    ])
    return {
        "user_document_id": document_id,
        "paragraphs": len(document.paragraphs),
        "stored_bytes": str(target),
    }
