
## Fleet data layer (OpenSky) - no schema change requested, notes only

- `category` (rule_field): the contract `Aircraft` node has no `category` field, and OpenSky's only related column (`categoryDescription`, a weight class) is not the certification category an AD means. Left unmapped; every `category` rule resolves to CANNOT_DETERMINE for this fleet. If a real source for certification category is added later, the Aircraft node would need the field.
- `equipment`, `modification`, `part_number` have no Aircraft field and no OpenSky column; same outcome.
- `Aircraft.manufacturer` is raw OpenSky text and may be null even when `typecode` implies a manufacturer; it is deliberately not back-filled (derived, not source data). Join via `engine/graph/normalize.py`.

## Revision provenance (content_sha256 / retrieved_at / source_bytes) - no schema change requested, notes only

- `retrieved_at` is `null` when unknown: XML cached before provenance existed is hashed from the cache, but its download time was never recorded and is not inferred from file mtime. Consumers must treat null as "unknown", not "epoch".
- `content_sha256` and `source_bytes` are both null only for revisions whose XML could not be fetched. The ingest writer rejects a Revision with `retrieved_at`/`source_bytes` but no hash.
- The contract does not say whether these may be null. If you want that pinned in `contract.json` (e.g. nullable flags), that is a change for the contract owner.
- Audit manifest `data/build/provenance.jsonl` is a sidecar (not a node type): `revision_id, url, content_sha256, retrieved_at, source_bytes, cache_path, basis` (+ `previous_content_sha256` when cached bytes changed after being recorded). `python3 -m engine.ingest.build --verify-provenance` re-hashes the cache against it.
