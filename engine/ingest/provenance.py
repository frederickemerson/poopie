"""Source provenance for fetched Federal Register documents.

A citation is only reproducible if the exact bytes it came from can be proven.
Three facts are recorded per document:

* ``content_sha256`` - SHA-256 of the raw response body, hashed before any
  decoding or parsing (decoding then hashing is not reproducible: the same text
  can come from different bytes). The body is what ``requests`` exposes as
  ``response.content``, i.e. after HTTP transfer decompression, which is exactly
  what is written to the cache.
* ``retrieved_at`` - timezone-aware UTC ISO-8601 time of the download, or
  ``None`` when unknown. A document cached by an earlier run has no recorded
  download time; it is hashed from the cache and ``retrieved_at`` stays ``None``
  rather than being invented from file mtimes or "now".
* ``source_bytes`` - byte length of the same body.

The manifest (``data/build/provenance.jsonl``) is the audit artifact;
``verify`` re-hashes the cache against it without touching the network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine import paths

MANIFEST_PATH = paths.BUILD / "provenance.jsonl"

BASIS_FETCHED = "fetched"
BASIS_CACHE_ONLY = "cache_hash_only"
_CHUNK = 1 << 20


class ProvenanceError(RuntimeError):
    """A manifest or cache entry cannot be trusted or read."""


@dataclass(frozen=True)
class Provenance:
    revision_id: str
    url: str | None
    content_sha256: str
    retrieved_at: str | None
    source_bytes: int
    cache_path: str
    basis: str
    #: Set only when the cached bytes changed since the manifest recorded them.
    previous_content_sha256: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        if record["previous_content_sha256"] is None:
            del record["previous_content_sha256"]
        return record


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_of_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def hash_file(path: Path) -> tuple[str, int]:
    """(sha256 hex, byte length) of a file's raw bytes, streamed."""
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise ProvenanceError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest(), size


def parse_retrieved_at(value: str) -> dt.datetime:
    """Parse a recorded timestamp; reject naive or non-UTC values."""
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ProvenanceError(f"retrieved_at {value!r} is not timezone-aware UTC")
    return parsed


def relative_cache_path(path: Path) -> str:
    """Repo-relative posix path; absolute only if the file lives outside the repo."""
    try:
        return path.resolve().relative_to(paths.ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def from_fetch(
    revision_id: str, url: str, content: bytes, path: Path, *, retrieved_at: str | None = None
) -> Provenance:
    """Provenance of bytes just downloaded. ``content`` must be the raw body."""
    stamp = retrieved_at or utc_now_iso()
    parse_retrieved_at(stamp)
    return Provenance(
        revision_id=revision_id,
        url=url,
        content_sha256=sha256_of_bytes(content),
        retrieved_at=stamp,
        source_bytes=len(content),
        cache_path=relative_cache_path(path),
        basis=BASIS_FETCHED,
    )


def from_cache(revision_id: str, url: str | None, path: Path) -> Provenance:
    """Provenance of a file with no recorded download: hash known, time unknown."""
    sha, size = hash_file(path)
    return Provenance(
        revision_id=revision_id,
        url=url,
        content_sha256=sha,
        retrieved_at=None,
        source_bytes=size,
        cache_path=relative_cache_path(path),
        basis=BASIS_CACHE_ONLY,
    )


def reconcile(
    revision_id: str,
    url: str | None,
    path: Path,
    fetched: Provenance | None,
    prior: Provenance | None,
) -> tuple[Provenance, str | None]:
    """Decide the provenance of the bytes currently in the cache.

    The cache file is re-hashed, so a recorded hash is only reused when it still
    describes the bytes on disk. Returns (provenance, drift note or None).
    """
    current = from_cache(revision_id, url, path)
    if fetched is not None and fetched.content_sha256 == current.content_sha256:
        return fetched, None
    if prior is not None and prior.content_sha256 == current.content_sha256:
        return Provenance(**{**asdict(prior), "url": url or prior.url}), None
    if prior is not None:
        note = (
            f"{revision_id}: cached bytes changed since recorded "
            f"({prior.content_sha256[:12]} -> {current.content_sha256[:12]})"
        )
        return Provenance(
            **{**asdict(current), "previous_content_sha256": prior.content_sha256}
        ), note
    return current, None


# ------------------------------------------------------------------ manifest


def read_manifest(path: Path = MANIFEST_PATH) -> dict[str, Provenance]:
    """Strict reader: a malformed line is an error, never skipped."""
    if not path.exists():
        return {}
    entries: dict[str, Provenance] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entry = Provenance(**json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ProvenanceError(f"{path}:{number}: malformed manifest line: {exc}") from exc
            if entry.revision_id in entries:
                raise ProvenanceError(f"{path}:{number}: duplicate revision_id {entry.revision_id}")
            entries[entry.revision_id] = entry
    return entries


def merge_manifest(
    prior: dict[str, Provenance], current: list[Provenance]
) -> dict[str, Provenance]:
    """Prior entries survive unless this run re-examined the same document."""
    return {**prior, **{p.revision_id: p for p in current}}


def write_manifest(entries: dict[str, Provenance], path: Path = MANIFEST_PATH) -> None:
    """Atomic write (temp file + rename), sorted by revision_id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for key in sorted(entries):
            handle.write(json.dumps(entries[key].to_record(), ensure_ascii=False) + "\n")
    os.replace(temp, path)


# -------------------------------------------------------------------- verify


@dataclass
class VerifyReport:
    checked: int = 0
    matched: int = 0
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unrecorded: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Drift that breaks a citation: a recorded hash that no longer matches
        or whose file is gone. Unrecorded files are reported, not failed."""
        return not self.changed and not self.missing


def _resolve(cache_path: str) -> Path:
    candidate = Path(cache_path)
    resolved = (candidate if candidate.is_absolute() else paths.ROOT / candidate).resolve()
    return resolved


def verify(
    manifest_path: Path = MANIFEST_PATH, cache_dir: Path = paths.FR_XML_CACHE
) -> VerifyReport:
    """Re-hash the cache against the manifest. Reads only; never downloads."""
    manifest = read_manifest(manifest_path)
    report = VerifyReport()
    recorded_paths: set[Path] = set()
    for revision_id in sorted(manifest):
        entry = manifest[revision_id]
        file_path = _resolve(entry.cache_path)
        recorded_paths.add(file_path)
        report.checked += 1
        if not file_path.is_file():
            report.missing.append(revision_id)
            continue
        sha, size = hash_file(file_path)
        if sha == entry.content_sha256 and size == entry.source_bytes:
            report.matched += 1
        else:
            report.changed.append(revision_id)
    if cache_dir.is_dir():
        for file_path in sorted(cache_dir.glob("*.xml")):
            if file_path.resolve() not in recorded_paths:
                report.unrecorded.append(file_path.stem)
    return report


def format_report(report: VerifyReport) -> str:
    lines = [
        f"checked {report.checked} recorded documents: {report.matched} match, "
        f"{len(report.changed)} changed, {len(report.missing)} missing, "
        f"{len(report.unrecorded)} unrecorded",
    ]
    for label, ids in (
        ("CHANGED", report.changed),
        ("MISSING", report.missing),
        ("UNRECORDED", report.unrecorded),
    ):
        for revision_id in ids:
            lines.append(f"  {label} {revision_id}")
    return "\n".join(lines)


def run_verify_cli() -> int:
    """Exit status for ``--verify-provenance``: non-zero on any drift."""
    if not MANIFEST_PATH.exists():
        print(f"no manifest at {MANIFEST_PATH}; run a build first")
        return 2
    try:
        report = verify()
    except ProvenanceError as exc:
        print(f"provenance verification failed: {exc}")
        return 2
    print(format_report(report))
    return 0 if report.ok else 1
