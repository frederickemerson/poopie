"""The library: documents the user loaded, and what they are allowed to do.

Three jobs, in one place because they share one invariant.

**Attach.** At startup the shipped corpus and the shipped index are loaded and
checked against each other exactly as before. Only then is the library attached:
paragraphs are appended to the live corpus, rows are inserted into a *private
copy* of the index, and the report says what happened. Nothing under
``data/build`` is opened for writing at any point.

**Add.** One upload: validated, parsed, embedded, persisted, appended. The order
matters and is deliberate -- everything that can refuse the upload happens
before anything is written, and everything that writes happens after the last
thing that can fail on input. See :meth:`Library.add`.

**Cite.** A citation to a user document is resolved by
:class:`LibraryReferenceBook`, which hands back a
:class:`UserDocumentReference`: the uploader's own title as the handle, the
authority they named, ``fr_citation`` and ``page_range`` reported *not recorded*
through the existing mechanism, and the reason it cannot establish an obligation
carried in the citation itself. There is no code path here that can produce a
Federal Register citation for a document that has none -- the fields are not
merely left blank, they are listed as absent, and ``build_envelope`` turns that
listing into a stated limitation of the answer.

The one thing the library deliberately does **not** do is let a user document
reach the answer writer. The writer's prompt describes its inputs as
"paragraphs retrieved from adopted FAA ADs", and the verifier checks only that a
quote is verbatim in a retrieved paragraph. So the fence is kept upstream of
both: user documents are outside the default retrieval scope, and
``engine.graph.stage.split_obligation_evidence`` removes them from the writer's
evidence even when a caller has explicitly asked to retrieve them.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api.citations import (  # noqa: E402
    NOT_RECORDED,
    HumanReference,
    ReferenceBook,
    parse_citation_id,
)
from engine.graph.stage import (  # noqa: E402
    SOURCE_KIND_USER_DOCUMENT,
    describe,
    describe_source_kind,
    obligation_refusal,
)
from engine.ingest import user_documents as user_docs  # noqa: E402
from engine.ingest.user_parse import UploadRejected  # noqa: E402
from engine.retrieval.corpus import (  # noqa: E402
    Corpus,
    UserDocumentMeta,
    extend_corpus,
    user_paragraph,
)
from engine.retrieval.entities import Entities  # noqa: E402
from engine.retrieval.graph_filter import USER_DOCUMENTS_ONLY  # noqa: E402
from engine.retrieval.index import (  # noqa: E402
    DenseUnavailable,
    HybridIndex,
    _indexed_text,
    embed,
    extend_index,
)
from engine.retrieval.search import search  # noqa: E402

#: The human-reference fields a user document does not have. Named rather than
#: left blank: see engine/api/citations.py, "An absent field says so".
UNHELD_REFERENCE_FIELDS = ("ad_number", "record_id", "fr_citation", "page_range")


class VectorCache:
    """Dense vectors for user paragraphs, keyed by ``paragraph_id``.

    Keyed, not ordered. An ordered cache (row *n* is the *n*th stored
    paragraph) has to be re-derived from file order on every read, and any
    disagreement between the two silently hands a paragraph another paragraph's
    meaning -- a wrong answer with no symptom. A dict of id to vector either has
    the row or does not, and a missing row is recomputed.

    The cache exists so startup does not have to load the embedding model: the
    upload pays for its own embeddings, which is the request that should.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.vectors: dict[str, np.ndarray] = {}
        self.note: str | None = None
        if path.exists():
            self._read()

    def _read(self) -> None:
        try:
            with np.load(self.path, allow_pickle=False) as data:
                ids = [str(v) for v in data["paragraph_ids"]]
                matrix = np.asarray(data["vectors"], dtype=np.float32)
        except (OSError, ValueError, KeyError) as exc:
            self.note = f"{self.path.name} could not be read ({exc}); recomputing"
            return
        if matrix.ndim != 2 or matrix.shape[0] != len(ids):
            self.note = (
                f"{self.path.name} holds {matrix.shape} vectors for {len(ids)} ids; "
                f"recomputing rather than trusting it"
            )
            return
        self.vectors = {pid: matrix[i] for i, pid in enumerate(ids)}

    def get(self, paragraph_ids: list[str]) -> np.ndarray | None:
        """Vectors in the given order, or None if any is missing."""
        if not all(pid in self.vectors for pid in paragraph_ids):
            return None
        return np.vstack([self.vectors[pid] for pid in paragraph_ids])

    def put(self, paragraph_ids: list[str], vectors: np.ndarray) -> None:
        for pid, row in zip(paragraph_ids, np.asarray(vectors, dtype=np.float32)):
            self.vectors[pid] = row
        self.save()

    def save(self) -> None:
        """Write atomically, so a crash cannot leave a truncated cache."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ids = sorted(self.vectors)
        matrix = (
            np.vstack([self.vectors[pid] for pid in ids])
            if ids
            else np.zeros((0, 0), dtype=np.float32)
        )
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("wb") as handle:
            # A fixed-width unicode array, NOT dtype=object: an object array can
            # only be read back with allow_pickle=True, and loading pickles from
            # a file written beside user uploads is not something this engine
            # does. np.array infers '<U..' from a list of str.
            np.savez(
                handle,
                paragraph_ids=np.array(ids, dtype=np.str_),
                vectors=matrix,
            )
        tmp.replace(self.path)


# ------------------------------------------------------------- the reference


@dataclass(frozen=True)
class UserDocumentReference(HumanReference):
    """A citation to a document the user loaded.

    A ``HumanReference`` subclass rather than a parallel type, so it passes
    ``reference_dicts``' check and inherits the guarantee that a citation
    without a contract ``document_stage`` cannot be constructed at all.
    """

    #: The uploader's own title and the authority they named. Their words, kept
    #: verbatim; nothing in the engine branches on either.
    title: str = ""
    authority: str = ""
    uploaded_at: str | None = None
    source_filename: str | None = None
    content_sha256: str | None = None
    #: Why this citation cannot support a statement that something is required.
    #: Carried on the citation because that is where a reader meets it.
    obligation_refusal: str = ""

    @property
    def handle(self) -> str:
        """The uploader's title. There is no AD number or record_id to use."""
        return self.title or self.document_id

    @property
    def display(self) -> str:
        """One line that cannot be mistaken for a Federal Register citation."""
        section = f"paragraph ({self.paragraph_label.strip('()')})"
        if self.paragraph_role:
            section += f" {self.paragraph_role}"
        return " · ".join(
            [
                self.handle,
                f"loaded by you from {self.source_filename or 'an upload'}",
                f"issued by {self.authority or 'an authority you did not name'}",
                f"FR citation {NOT_RECORDED}",
                section,
                f"{self.document_stage} as declared by you, not verified",
            ]
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **super().as_dict(),
            "is_user_document": True,
            "title": self.title,
            "authority": self.authority,
            "uploaded_at": self.uploaded_at,
            "source_filename": self.source_filename,
            "content_sha256": self.content_sha256,
            "establishes_obligation": False,
            "obligation_refusal": self.obligation_refusal,
        }


def reference_for(
    meta: UserDocumentMeta,
    citation_id: str,
    label: str,
    role: str | None,
) -> UserDocumentReference:
    """Build the reference for one citation into a user document."""
    stage = meta.document_stage
    return UserDocumentReference(
        citation_id=citation_id,
        document_id=meta.user_document_id,
        source_kind=SOURCE_KIND_USER_DOCUMENT,
        document_stage=stage,
        stage_note=(
            f"{describe_source_kind(SOURCE_KIND_USER_DOCUMENT)} You declared it "
            f"{stage}. {describe(stage, None)}"
        ),
        ad_number=None,
        record_id=None,
        fr_citation=None,
        page_range=None,
        source_citation_text=None,
        paragraph_label=label,
        paragraph_role=role,
        federal_register_link=None,
        not_recorded=UNHELD_REFERENCE_FIELDS,
        title=meta.title,
        authority=meta.authority,
        uploaded_at=meta.uploaded_at,
        source_filename=meta.source_filename,
        content_sha256=meta.content_sha256,
        obligation_refusal=obligation_refusal(SOURCE_KIND_USER_DOCUMENT, stage) or "",
    )


class LibraryReferenceBook(ReferenceBook):
    """The shipped reference book, plus the user's own documents.

    Wraps rather than replaces: a citation into a Revision or an NPRM resolves
    through exactly the same code as before, and only an id this book recognises
    as a user document takes the new path. The registry is read live from the
    corpus, so a document uploaded after startup is citable without rebuilding
    the book.
    """

    def __init__(
        self,
        book: ReferenceBook,
        documents: dict[str, UserDocumentMeta],
    ) -> None:
        super().__init__(book.revisions, book.nprms, today=book.today)
        self._documents = documents

    def reference(
        self,
        citation_id: str,
        *,
        role: str | None = None,
        paragraph_stage: str | None = None,
    ) -> HumanReference:
        parsed = parse_citation_id(citation_id)
        document_id, label = parsed if parsed else (citation_id, "")
        meta = self._documents.get(document_id)
        if meta is not None:
            return reference_for(meta, citation_id, label, role)
        return super().reference(
            citation_id, role=role, paragraph_stage=paragraph_stage
        )


# ----------------------------------------------------------------- the library


class Library:
    """The loaded user documents, bound to one corpus and one index.

    Mutating a live corpus and a live index is serialised on a lock. FastAPI
    runs a synchronous endpoint in a worker thread, so two uploads arriving
    together would otherwise interleave an append to the corpus with an insert
    into the index and leave row *i* of the matrix pointing at paragraph *j*.
    """

    def __init__(
        self,
        corpus: Corpus,
        index: HybridIndex | None,
        book: ReferenceBook,
        *,
        directory: Path | None = None,
    ) -> None:
        self.corpus = corpus
        self.index = index
        # Resolved here rather than defaulted in the signature: a default
        # argument is bound once at import, which would make the store location
        # impossible to redirect -- including in a test, which would then have
        # to write into the real library to exercise anything.
        self.directory = directory or user_docs.DIRECTORY
        self.cache = VectorCache(self.directory / user_docs.EMBEDDINGS_NPZ.name)
        self.work_db = self.directory / user_docs.INDEX_DB.name
        self.references = LibraryReferenceBook(book, corpus.user_documents)
        self.notes: list[str] = []
        self.error: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- startup

    def attach(self) -> dict[str, Any]:
        """Union the stored documents into the live corpus and index.

        Returns a report even when nothing was loaded, because "no user
        documents" and "user documents that failed to attach" are different
        facts and a single empty list would conflate them.
        """
        with self._lock:
            store = user_docs.load(self.directory)
            if not store.documents:
                return {**store.as_report(), "attached": 0, "dense": None}
            corpus_report = extend_corpus(self.corpus, store)
            added = [
                self.corpus.by_id[pid]
                for pid in corpus_report["paragraphs_added"]
                if pid in self.corpus.by_id
            ]
            attached = self._index(added)
            return {
                **store.as_report(),
                **corpus_report,
                "attached": len(added) if attached else 0,
                "dense": self.index.dense_available if self.index else None,
                "error": self.error,
            }

    # -------------------------------------------------------------- reading

    def documents(self) -> list[dict[str, Any]]:
        """Every loaded document, newest first, with its paragraph count."""
        store = user_docs.load(self.directory)
        return [document.as_summary() for document in reversed(store.documents)]

    def as_report(self) -> dict[str, Any]:
        """What /health says about the library."""
        return {
            "directory": str(self.directory),
            "documents": len(self.corpus.user_documents),
            "paragraphs": sum(
                1 for p in self.corpus.paragraphs if p.is_user_document
            ),
            "retrievable": self.error is None,
            "in_default_retrieval_scope": False,
            "can_establish_obligation": False,
            "notes": list(self.notes),
            "error": self.error,
        }

    def search(self, query: str, *, k: int = 8) -> dict[str, Any]:
        """Search the user's own documents, and nothing else.

        Scoped to ``USER_DOCUMENTS_ONLY`` rather than run over everything and
        filtered afterwards: the point of the endpoint is "what do my documents
        say about X", and mixing in adopted ADs would answer a different
        question using the same words.
        """
        if self.index is None:
            return {"error": "no retrieval index is loaded", "hits": []}
        if not self.corpus.user_documents:
            return {
                "hits": [],
                "documents": 0,
                "note": "no user documents are loaded, so there is nothing to search",
            }
        result = search(
            self.index,
            query,
            Entities(),
            k=max(1, min(int(k or 8), 25)),
            source_kinds=USER_DOCUMENTS_ONLY,
        )
        resolve = self.references.reference
        hits: list[dict[str, Any]] = []
        for hit in result.hits:
            row = dict(hit.as_payload())
            row["text"] = hit.text
            row["human_reference"] = resolve(
                hit.citation_id, role=hit.role, paragraph_stage=hit.document_stage
            ).as_dict()
            row["establishes_obligation"] = False
            row["obligation_refusal"] = obligation_refusal(
                hit.source_kind, hit.document_stage
            )
            hits.append(row)
        return {
            "hits": hits,
            "documents": len(self.corpus.user_documents),
            "filter": result.filter_report,
            "arms": result.arms,
            # Stated on every response, not left for the caller to remember.
            "limitation": (
                "These are documents you loaded. They are not FAA airworthiness "
                "directives, this engine has not verified them, and nothing in them "
                "can establish a compliance obligation or an applicability verdict "
                "here."
            ),
        }

    # --------------------------------------------------------------- adding

    def add(
        self,
        raw: bytes,
        *,
        title: str,
        authority: str,
        document_stage: str,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> dict[str, Any]:
        """Load one document. Returns a report; raises ``UploadRejected``.

        The order is the safety property:

        1. ``build`` validates size, type, encoding, XML shape and the declared
           stage, and parses the text. Nothing has been written.
        2. A document whose bytes are already loaded returns early. Same bytes,
           same id, so this is a fact and not a heuristic.
        3. The paragraphs are embedded. This is the last step that can fail for
           a reason outside this process's control (the model has to load).
        4. Only now is anything persisted, and only then are the live corpus and
           the index extended.
        """
        document, parsed = user_docs.build(
            raw,
            title=title,
            authority=authority,
            document_stage=document_stage,
            filename=filename,
            media_type=media_type,
        )
        with self._lock:
            if document.user_document_id in self.corpus.user_documents:
                return {
                    "status": "already_loaded",
                    "user_document_id": document.user_document_id,
                    "detail": (
                        "these exact bytes are already loaded, under id "
                        f"{document.user_document_id}; nothing was changed"
                    ),
                    "document": document.as_summary(),
                }

            # Embedded over exactly the string the keyword arm indexes --
            # heading plus body -- so the two arms score the same text.
            paragraphs = [user_paragraph(record) for record in document.paragraphs]
            vectors = self._vectors(paragraphs)
            stored = user_docs.append(document, raw, directory=self.directory)
            store = user_docs.UserDocumentStore(documents=[document])
            corpus_report = extend_corpus(self.corpus, store)
            added = [
                self.corpus.by_id[pid]
                for pid in corpus_report["paragraphs_added"]
                if pid in self.corpus.by_id
            ]
            self._index(added, vectors=vectors)
            return {
                "status": "loaded",
                "user_document_id": document.user_document_id,
                **stored,
                "document": document.as_summary(),
                "parse_notes": list(parsed.notes),
                "retrievable": self.error is None,
                "establishes_obligation": False,
                "obligation_refusal": obligation_refusal(
                    SOURCE_KIND_USER_DOCUMENT, str(document.node["document_stage"])
                ),
                "in_default_retrieval_scope": False,
            }

    # -------------------------------------------------------------- internals

    def _vectors(self, paragraphs: list[Any]) -> np.ndarray | None:
        """Embeddings for new paragraphs, or None when the index has no dense arm.

        A dense arm that exists but cannot embed these paragraphs is an error,
        not a degradation: a matrix shorter than the corpus breaks every dense
        query, and padding it with zeros would retire the dense arm for exactly
        the documents the user just added, invisibly. So the upload is refused
        with the reason and nothing is stored.
        """
        if self.index is None or not self.index.dense_available:
            return None
        ids = [p.paragraph_id for p in paragraphs]
        cached = self.cache.get(ids)
        if cached is not None:
            return cached
        try:
            vectors = embed([_indexed_text(p) for p in paragraphs])
        except DenseUnavailable as exc:
            raise UploadRejected(
                f"the embedding model is not available, so this document cannot be "
                f"indexed for semantic search ({exc}). Nothing was stored."
            ) from exc
        self.cache.put(ids, vectors)
        return vectors

    def _index(
        self,
        paragraphs: list[Any],
        *,
        vectors: np.ndarray | None = None,
    ) -> bool:
        """Insert paragraphs into the private index copy. Records any failure."""
        if self.index is None:
            self.error = (
                "no retrieval index is loaded, so user documents are not searchable"
            )
            return False
        if not paragraphs:
            return True
        if vectors is None:
            try:
                vectors = self._vectors(paragraphs)
            except UploadRejected as exc:
                self.error = str(exc)
                return False
        if self.cache.note and self.cache.note not in self.notes:
            self.notes.append(self.cache.note)
        try:
            extend_index(
                self.index, paragraphs, vectors=vectors, work_db=self.work_db
            )
        except (RuntimeError, ValueError) as exc:
            # Reported, not swallowed, and recoverable: the working copy is
            # rebuilt from the shipped index on the next startup, so a restart
            # repairs this rather than leaving a wrong index behind.
            self.error = (
                f"{type(exc).__name__}: {exc}. Restart the engine to rebuild the "
                f"index working copy from the shipped one."
            )
            return False
        self.error = None
        return True
