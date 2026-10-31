"""Where the retrieval layer reads and writes.

Two sets of paths, deliberately separate:

* The *real* corpus, produced by the ingest agent (``data/build/nodes.jsonl``
  and friends). This layer only ever reads those.
* A *dev fixture* corpus produced by ``engine.retrieval.fixture_corpus`` from
  committed Federal Register XML. It exists so retrieval can be built and
  measured before the ingest lands, and so the tests never depend on a file
  another agent is still writing.

Every generated filename here matches a pattern already in ``.gitignore``
(``data/build/*.jsonl``, ``*.db``, ``*.npy``) so build artifacts stay out of git
without this layer editing a file it does not own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "data" / "build"
FIXTURES = ROOT / "data" / "fixtures"
RAW_FR_XML = ROOT / "data" / "raw" / "fr_ad"

# --- the real corpus (read-only here; the ingest agent owns these) ----------
NODES_JSONL = BUILD / "nodes.jsonl"
EDGES_JSONL = BUILD / "edges.jsonl"
PARAGRAPHS_JSONL = BUILD / "paragraphs.jsonl"
REVISION_TEXT_JSONL = BUILD / "revision_text.jsonl"

# --- the dev fixture corpus (this layer owns these) ------------------------
FIXTURE_NODES_JSONL = BUILD / "retrieval_fixture_nodes.jsonl"
FIXTURE_EDGES_JSONL = BUILD / "retrieval_fixture_edges.jsonl"
FIXTURE_PARAGRAPHS_JSONL = BUILD / "retrieval_fixture_paragraphs.jsonl"
FIXTURE_REVISION_TEXT_JSONL = BUILD / "retrieval_fixture_revision_text.jsonl"

# --- the index ------------------------------------------------------------
INDEX_DB = BUILD / "retrieval.db"
EMBEDDINGS_NPY = BUILD / "retrieval_embeddings.npy"

#: Small, local, CPU-friendly. Pinned by name so an index built on one machine
#: is reproducible on another; the dimension is recorded in the index meta and
#: checked on load, so swapping this invalidates the index loudly.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


class CorpusUnavailable(RuntimeError):
    """A corpus file this layer needs does not exist yet.

    Raised with the path and the command that produces it. Never swallowed: a
    missing corpus must not look like an empty one, because an empty corpus
    silently turns every query into a refusal.
    """


def require(path: Path, produced_by: str) -> Path:
    if not path.exists():
        raise CorpusUnavailable(
            f"{path} does not exist. It is produced by: {produced_by}"
        )
    return path


@dataclass(frozen=True)
class CorpusPaths:
    """One coherent set of corpus files, with the name of the set it came from."""

    kind: str
    paragraphs: Path
    nodes: Path
    edges: Path
    revision_text: Path


FIXTURE_PATHS = CorpusPaths(
    kind="fixture",
    paragraphs=FIXTURE_PARAGRAPHS_JSONL,
    nodes=FIXTURE_NODES_JSONL,
    edges=FIXTURE_EDGES_JSONL,
    revision_text=FIXTURE_REVISION_TEXT_JSONL,
)

BUILD_PATHS = CorpusPaths(
    kind="build",
    paragraphs=PARAGRAPHS_JSONL,
    nodes=NODES_JSONL,
    edges=EDGES_JSONL,
    revision_text=REVISION_TEXT_JSONL,
)


#: Pins the corpus choice. "fixture" or "build" force one set; anything else
#: (or unset) picks the real corpus when it exists. Measurements are taken with
#: this pinned, so a concurrent re-ingest cannot move the numbers mid-run.
CORPUS_ENV = "AD_RETRIEVAL_CORPUS"


def default_corpus_paths(*, prefer_fixture: bool = False) -> CorpusPaths:
    """Real corpus when the ingest has produced paragraphs, else the fixture.

    The choice turns on ``paragraphs.jsonl`` alone -- it is the one file this
    layer cannot work without -- and the result names which set was chosen so a
    caller can report it rather than guess.
    """
    pinned = os.environ.get(CORPUS_ENV, "").strip().lower()
    if pinned == "fixture":
        return FIXTURE_PATHS
    if pinned == "build":
        return BUILD_PATHS
    if pinned:
        raise ValueError(
            f"{CORPUS_ENV}={pinned!r} is not understood; use 'fixture', 'build' or unset"
        )
    if prefer_fixture or not PARAGRAPHS_JSONL.exists():
        return FIXTURE_PATHS
    return BUILD_PATHS
