"""Source provenance: hashing, timestamps, manifest, drift detection. No network."""

from __future__ import annotations

import datetime as dt
import hashlib

import pytest

from contracts.contract import ContractViolation
from engine.ingest import provenance as prov
from engine.ingest.emit import GraphWriter

# Non-ASCII bytes that decode differently under different codecs: hashing the
# decoded text would not be reproducible, hashing the bytes is.
RAW = '<RULE><P>Café – AD 2021-01-01</P></RULE>'.encode("utf-8")


@pytest.fixture()
def cache(tmp_path):
    directory = tmp_path / "fr_ad"
    directory.mkdir()
    return directory


def _write(cache, name, content=RAW):
    path = cache / f"{name}.xml"
    path.write_bytes(content)
    return path


def _manifest(tmp_path, entries):
    path = tmp_path / "provenance.jsonl"
    prov.write_manifest({e.revision_id: e for e in entries}, path)
    return path


def test_hash_is_over_raw_bytes_and_stable(cache):
    path = _write(cache, "2021-1")
    expected = hashlib.sha256(RAW).hexdigest()
    assert prov.sha256_of_bytes(RAW) == expected
    assert prov.hash_file(path) == (expected, len(RAW))
    assert prov.hash_file(path) == prov.hash_file(path)
    # decode-then-hash would differ from hashing the bytes
    assert hashlib.sha256(RAW.decode("utf-8").encode("utf-16")).hexdigest() != expected


def test_source_bytes_is_byte_length_not_character_count(cache):
    record = prov.from_fetch("2021-1", "http://x", RAW, _write(cache, "2021-1"))
    assert record.source_bytes == len(RAW) > len(RAW.decode("utf-8"))


def test_retrieved_at_is_timezone_aware_utc(cache):
    record = prov.from_fetch("2021-1", "http://x", RAW, _write(cache, "2021-1"))
    parsed = prov.parse_retrieved_at(record.retrieved_at)
    assert parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0)
    with pytest.raises(prov.ProvenanceError):
        prov.parse_retrieved_at("2024-01-01T00:00:00")
    with pytest.raises(prov.ProvenanceError):
        prov.parse_retrieved_at("2024-01-01T00:00:00+02:00")


def test_cached_unhashed_file_has_unknown_time_never_fabricated(cache):
    path = _write(cache, "2021-1")
    record, drift = prov.reconcile("2021-1", "http://x", path, fetched=None, prior=None)
    assert record.retrieved_at is None
    assert record.basis == prov.BASIS_CACHE_ONLY
    assert record.content_sha256 == hashlib.sha256(RAW).hexdigest()
    assert drift is None


def test_prior_retrieved_at_is_kept_while_bytes_match(cache):
    path = _write(cache, "2021-1")
    prior = prov.from_fetch("2021-1", "http://x", RAW, path, retrieved_at="2025-01-02T03:04:05+00:00")
    record, drift = prov.reconcile("2021-1", "http://x", path, fetched=None, prior=prior)
    assert record.retrieved_at == "2025-01-02T03:04:05+00:00" and drift is None


def test_changed_bytes_drop_old_time_and_flag_drift(cache):
    path = _write(cache, "2021-1")
    prior = prov.from_fetch("2021-1", "http://x", RAW, path, retrieved_at="2025-01-02T03:04:05+00:00")
    path.write_bytes(RAW + b"<!-- corrected -->")
    record, drift = prov.reconcile("2021-1", "http://x", path, fetched=None, prior=prior)
    assert record.retrieved_at is None
    assert record.previous_content_sha256 == prior.content_sha256
    assert drift and "changed" in drift


def test_verify_distinguishes_changed_missing_unrecorded(tmp_path, cache):
    entries = []
    for name in ("same", "edited", "gone"):
        path = _write(cache, name)
        entries.append(prov.from_cache(name, None, path))
    manifest = _manifest(tmp_path, entries)
    (cache / "edited.xml").write_bytes(RAW + b" ")
    (cache / "gone.xml").unlink()
    _write(cache, "new-doc")

    report = prov.verify(manifest, cache)

    assert report.matched == 1
    assert report.changed == ["edited"]
    assert report.missing == ["gone"]
    assert report.unrecorded == ["new-doc"]
    assert not report.ok


def test_verify_ok_when_only_unrecorded(tmp_path, cache):
    entry = prov.from_cache("a", None, _write(cache, "a"))
    manifest = _manifest(tmp_path, [entry])
    _write(cache, "b")
    report = prov.verify(manifest, cache)
    assert report.ok and report.unrecorded == ["b"]


def test_manifest_round_trip_and_strict_reader(tmp_path, cache):
    entry = prov.from_fetch("a", "http://x", RAW, _write(cache, "a"))
    manifest = _manifest(tmp_path, [entry])
    assert prov.read_manifest(manifest) == {"a": entry}
    manifest.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(prov.ProvenanceError):
        prov.read_manifest(manifest)


def test_merge_manifest_does_not_mutate_inputs_and_keeps_unseen(cache):
    old = prov.from_cache("old", None, _write(cache, "old"))
    new = prov.from_cache("new", None, _write(cache, "new"))
    prior = {"old": old}
    merged = prov.merge_manifest(prior, [new])
    assert set(merged) == {"old", "new"} and set(prior) == {"old"}


def test_revision_node_requires_hash_and_size_together(tmp_path):
    base = {"revision_id": "r1", "ad_number": "2021-01-01"}
    nodes = tmp_path / "n", tmp_path / "e", tmp_path / "p"
    with GraphWriter(*nodes) as writer:
        writer.node("Revision", {**base, "content_sha256": None})  # no bytes: allowed
        with pytest.raises(ContractViolation):
            writer.node("Revision", {**base, "revision_id": "r2", "source_bytes": 5})
        with pytest.raises(ContractViolation):
            writer.node(
                "Revision",
                {**base, "revision_id": "r3", "content_sha256": "ab" * 32,
                 "source_bytes": 5, "retrieved_at": "2024-01-01T00:00:00"},
            )
        writer.node(
            "Revision",
            {**base, "revision_id": "r4", "content_sha256": "ab" * 32,
             "source_bytes": 5, "retrieved_at": None},
        )
