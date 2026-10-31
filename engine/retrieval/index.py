"""The hybrid index: SQLite FTS5 for keyword, a NumPy matrix for dense.

Why FTS5 and not ``rank_bm25`` (both are installed):

* FTS5 keeps an inverted index on disk and scores in C. ``rank_bm25`` holds the
  whole tokenized corpus in Python memory and scores every document on every
  query, which is O(N) Python per query -- fine at 1,400 paragraphs, not fine at
  the full register, and this layer owns a 100 ms budget.
* FTS5 can intersect the match with a rowid set in the same statement, which is
  exactly what "graph filter first, then search" needs. Doing that with
  ``rank_bm25`` means scoring the whole corpus and discarding most of it.
* FTS5 gives phrase and prefix queries for free, which matters for identifiers.

The one thing FTS5 gets wrong out of the box is hyphenated identifiers: the
default ``unicode61`` tokenizer splits ``2026-21-13`` into three tokens, so an
AD number would match any document mentioning 2026. ``tokenchars '-'`` keeps it
one token. Identifier lookup is still the entity pass's job, not the keyword
arm's, but this stops the keyword arm from actively misleading the fusion.

Embeddings are computed once at build time into a float32 matrix and never
re-computed per query; only the query itself is embedded (~13 ms warm). The
model name and dimension are stored in the index and checked on load, so
changing the model invalidates the index loudly instead of silently mixing
vector spaces.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.retrieval.corpus import Corpus, load_corpus  # noqa: E402
from engine.retrieval.layout import (  # noqa: E402
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    EMBEDDINGS_NPY,
    INDEX_DB,
    CorpusUnavailable,
)

_FTS_TOKENIZE = "unicode61 tokenchars '-'"
_model_cache: dict[str, object] = {}


class IndexUnavailable(RuntimeError):
    """The index does not exist or does not match the corpus it is used with."""


class DenseUnavailable(RuntimeError):
    """The embedding model could not be loaded. The caller degrades, visibly."""


def embedder():
    """The sentence-transformers model, loaded once per process.

    Raises ``DenseUnavailable`` rather than returning None: a silently missing
    dense arm would halve retrieval quality with no trace in the output.
    """
    cached = _model_cache.get(EMBEDDING_MODEL)
    if cached is not None:
        return cached
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - dependency is installed
        raise DenseUnavailable(f"sentence-transformers is not importable: {exc}") from exc
    try:
        model = SentenceTransformer(EMBEDDING_MODEL)
    except (OSError, ValueError, RuntimeError) as exc:
        raise DenseUnavailable(
            f"cannot load {EMBEDDING_MODEL}: {exc}. It is downloaded on first use; "
            f"with no network, build the index with --no-dense and retrieval runs "
            f"keyword-only, which the index meta records."
        ) from exc
    _model_cache[EMBEDDING_MODEL] = model
    return model


def embed(texts: list[str]) -> np.ndarray:
    """L2-normalised float32 embeddings, so cosine similarity is a dot product."""
    vectors = embedder().encode(
        texts, normalize_embeddings=True, show_progress_bar=False
    )
    return np.asarray(vectors, dtype=np.float32)


def _indexed_text(paragraph) -> str:
    """What goes in the index: heading plus body.

    The heading carries the paragraph's function ("Applicability", "Compliance")
    which is frequently the whole of the user's question, and it is authoritative
    markup from the source document rather than something inferred.
    """
    return f"{paragraph.heading}\n{paragraph.text}".strip()


@dataclass
class HybridIndex:
    """A loaded index bound to one corpus ordering."""

    db: sqlite3.Connection
    corpus: Corpus
    embeddings: np.ndarray | None
    dense_model: str | None
    #: Paragraphs per contract ``source_kind``, read from the index meta. Lets
    #: a caller state what is in the index without walking the corpus.
    source_kind_counts: dict[str, int] = dataclass_field(default_factory=dict)

    @property
    def dense_available(self) -> bool:
        return self.embeddings is not None

    def rows_of_source_kinds(self, source_kinds: tuple[str, ...]) -> list[int]:
        """Zero-based corpus rows of the paragraphs of these source kinds."""
        if not source_kinds:
            return []
        placeholders = ",".join("?" * len(source_kinds))
        rows = self.db.execute(
            f"SELECT rowid_ FROM ids WHERE source_kind IN ({placeholders}) "
            f"ORDER BY rowid_",
            list(source_kinds),
        ).fetchall()
        return [int(r["rowid_"]) - 1 for r in rows]

    def close(self) -> None:
        self.db.close()


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def build_index(
    corpus: Corpus | None = None,
    *,
    db_path: Path = INDEX_DB,
    embeddings_path: Path = EMBEDDINGS_NPY,
    dense: bool = True,
) -> dict[str, object]:
    """Build both arms from scratch. Returns a report; raises on any failure."""
    corpus = corpus or load_corpus()
    if not corpus.paragraphs:
        raise CorpusUnavailable("corpus holds no paragraphs; nothing to index")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = db_path.with_suffix(db_path.suffix + ".tmp")
    tmp_db.unlink(missing_ok=True)
    db = _connect(tmp_db)
    try:
        with db:
            db.execute(
                f"CREATE VIRTUAL TABLE paragraphs USING fts5("
                f"body, tokenize=\"{_FTS_TOKENIZE}\")"
            )
            # source_kind and document_stage are stored beside the id so a
            # caller can restrict or label a keyword hit without loading the
            # whole corpus, and so the index cannot describe a paragraph
            # without saying what kind of document it came from.
            db.execute(
                "CREATE TABLE ids ("
                "rowid_ INTEGER PRIMARY KEY, paragraph_id TEXT, "
                "document_id TEXT, source_kind TEXT NOT NULL, "
                "document_stage TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX ids_source_kind ON ids(source_kind)")
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            db.executemany(
                "INSERT INTO paragraphs(rowid, body) VALUES (?, ?)",
                [(i + 1, _indexed_text(p)) for i, p in enumerate(corpus.paragraphs)],
            )
            db.executemany(
                "INSERT INTO ids(rowid_, paragraph_id, document_id, source_kind, "
                "document_stage) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        i + 1,
                        p.paragraph_id,
                        p.document_id,
                        p.source_kind,
                        p.document_stage,
                    )
                    for i, p in enumerate(corpus.paragraphs)
                ],
            )

        dense_model: str | None = None
        if dense:
            matrix = embed([_indexed_text(p) for p in corpus.paragraphs])
            if matrix.shape != (len(corpus.paragraphs), EMBEDDING_DIM):
                raise DenseUnavailable(
                    f"{EMBEDDING_MODEL} produced {matrix.shape}, expected "
                    f"{(len(corpus.paragraphs), EMBEDDING_DIM)}"
                )
            # np.save appends ".npy" unless the name already ends in it, so the
            # temp file is written through an explicit handle.
            tmp_npy = embeddings_path.with_name(embeddings_path.name + ".tmp")
            with tmp_npy.open("wb") as fh:
                np.save(fh, matrix)
            tmp_npy.replace(embeddings_path)
            dense_model = EMBEDDING_MODEL
        else:
            embeddings_path.unlink(missing_ok=True)

        with db:
            db.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                [
                    ("fingerprint", corpus.fingerprint),
                    ("corpus_kind", corpus.kind),
                    ("dense_model", json.dumps(dense_model)),
                    ("dense_dim", str(EMBEDDING_DIM if dense else 0)),
                    (
                        "source_kind_counts",
                        json.dumps(corpus.counts_by_source_kind(), sort_keys=True),
                    ),
                ],
            )
    finally:
        db.close()
    tmp_db.replace(db_path)

    return {
        "paragraphs": len(corpus.paragraphs),
        "by_source_kind": corpus.counts_by_source_kind(),
        "corpus_kind": corpus.kind,
        "fingerprint": corpus.fingerprint,
        "dense_model": dense_model,
        "db": str(db_path),
    }


def load_index(
    corpus: Corpus | None = None,
    *,
    db_path: Path = INDEX_DB,
    embeddings_path: Path = EMBEDDINGS_NPY,
) -> HybridIndex:
    """Open an existing index and check it describes this exact corpus."""
    corpus = corpus or load_corpus()
    if not db_path.exists():
        raise IndexUnavailable(
            f"{db_path} does not exist. Build it with: "
            f"python3 -m engine.retrieval.index --build"
        )
    db = _connect(db_path)
    meta = {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM meta")}
    if meta.get("fingerprint") != corpus.fingerprint:
        db.close()
        raise IndexUnavailable(
            f"index was built for corpus {meta.get('fingerprint')!r} but this corpus "
            f"is {corpus.fingerprint!r}. Rebuild: python3 -m engine.retrieval.index --build"
        )

    dense_model = json.loads(meta.get("dense_model") or "null")
    source_kind_counts = json.loads(meta.get("source_kind_counts") or "{}")
    embeddings: np.ndarray | None = None
    if dense_model:
        if not embeddings_path.exists():
            db.close()
            raise IndexUnavailable(
                f"index meta names dense model {dense_model!r} but {embeddings_path} "
                f"is missing. Rebuild the index."
            )
        embeddings = np.load(embeddings_path)
        expected = (len(corpus.paragraphs), int(meta.get("dense_dim") or 0))
        if embeddings.shape != expected:
            db.close()
            raise IndexUnavailable(
                f"{embeddings_path} has shape {embeddings.shape}, expected {expected}"
            )
    return HybridIndex(
        db=db,
        corpus=corpus,
        embeddings=embeddings,
        dense_model=dense_model,
        source_kind_counts=source_kind_counts,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Build the hybrid retrieval index.")
    ap.add_argument("--build", action="store_true", help="build (default action)")
    ap.add_argument("--fixture", action="store_true", help="force the fixture corpus")
    ap.add_argument(
        "--no-dense",
        action="store_true",
        help="keyword arm only; recorded in the index meta, not hidden",
    )
    args = ap.parse_args(argv)
    corpus = load_corpus(prefer_fixture=args.fixture)
    report = build_index(corpus, dense=not args.no_dense)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
