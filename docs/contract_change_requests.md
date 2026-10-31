
## Fleet data layer (OpenSky) - no schema change requested, notes only

- `category` (rule_field): the contract `Aircraft` node has no `category` field, and OpenSky's only related column (`categoryDescription`, a weight class) is not the certification category an AD means. Left unmapped; every `category` rule resolves to CANNOT_DETERMINE for this fleet. If a real source for certification category is added later, the Aircraft node would need the field.
- `equipment`, `modification`, `part_number` have no Aircraft field and no OpenSky column; same outcome.
- `Aircraft.manufacturer` is raw OpenSky text and may be null even when `typecode` implies a manufacturer; it is deliberately not back-filled (derived, not source data). Join via `engine/graph/normalize.py`.

## Revision provenance (content_sha256 / retrieved_at / source_bytes) - no schema change requested, notes only

- `retrieved_at` is `null` when unknown: XML cached before provenance existed is hashed from the cache, but its download time was never recorded and is not inferred from file mtime. Consumers must treat null as "unknown", not "epoch".
- `content_sha256` and `source_bytes` are both null only for revisions whose XML could not be fetched. The ingest writer rejects a Revision with `retrieved_at`/`source_bytes` but no hash.
- The contract does not say whether these may be null. If you want that pinned in `contract.json` (e.g. nullable flags), that is a change for the contract owner.
- Audit manifest `data/build/provenance.jsonl` is a sidecar (not a node type): `revision_id, url, content_sha256, retrieved_at, source_bytes, cache_path, basis` (+ `previous_content_sha256` when cached bytes changed after being recorded). `python3 -m engine.ingest.build --verify-provenance` re-hashes the cache against it.

## Reference traversal (engine/graph/traverse.py, engine/retrieval/expand.py)

Three gaps found while following references. None blocks the work; each one is a
place where the traversal has to derive something the contract could pin.

- **No edge type for an AD-to-AD reference the corpus cannot resolve.** The
  ingest turns paragraph (b) "Affected ADs" into `SUPERSEDES` edges only when
  the referenced AD number is in the corpus; the rest are counted in
  `ingest_report.supersession.referenced_ads_outside_corpus` and then exist
  nowhere in the graph. Since a referenced AD we do not hold is a first-class
  refusal cause, `traverse.py` has to read paragraph (b) back with the ingest's
  own `parse_affected_ads` to find them. A `REFERENCES_AD` edge type (from
  `Revision`, to `AD`, with a `relation` attr distinguishing "replaces" from
  "affects"/"is related to", plus a node or a `held` flag for an AD outside the
  ingest window) would make this structural and let the walk stay pure graph.
  The same gap hides the non-superseding relations entirely: "This AD affects
  AD 2023-26-01" produces no edge today, so an AD we *do* hold and that the
  document explicitly points at is invisible to any graph consumer.
- **`ADOPTS_MCAI` and `REFERENCES_SB` declare no attrs, so the delegating
  paragraph is not on the edge.** `refusal_semantics.EXTERNAL_SOURCE_REQUIRED`
  must show *why* a document is needed, and the exact clause is the evidence
  (`(c) Applicability ... as identified in EASA AD 2025-0208`). The ingest knows
  it -- it is in the `delegations.jsonl` sidecar -- but a graph consumer does
  not, so `expand.py` falls back to the referencing revision's retrieved
  paragraphs. Adding `"attrs": ["paragraph_id", "scope"]` to both edge types
  would make the citation exact.
- **`answer_envelope.traversal` is described, not shaped.** The traversal emits
  `{outcome, start, max_depth, reached[], references[], missing[], cycles[],
  truncated_at[]}`, where each `missing` entry is `{identifier, label, ntype,
  kind, reason, referenced_by, paragraph_ids, depth}`. `reason` is
  `not_in_corpus` or `text_not_held` and `kind` is `supersession` / `adoption` /
  `reference` -- vocabulary this layer had to name because no enum covers it. If
  the web layer is to mirror these, they belong in `contract.json` as
  `reference_kind` and `missing_reason` enums.
