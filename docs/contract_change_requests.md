
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

## Proposal text (NPRM full-text ingest) - two requests, both non-blocking

Found while indexing the 431 challenge-index proposals as PROPOSED documents.
Nothing here blocks the work; each is a place where the ingest has to carry a
relationship or a number in a field the contract did not shape for it.

- **`HAS_PARAGRAPH` is pinned to `from: ["Revision"]`, so a proposal's
  paragraphs have no parent edge.** The `Paragraph` node type already models
  both kinds -- "exactly one of revision_id / nprm_id is set, and source_kind
  says which" -- and 3,048 of the 28,735 paragraphs now carry `nprm_id`. But
  `HAS_PARAGRAPH` cannot be emitted from an `NPRM`, so the only link from a
  proposal to its own text is the `nprm_id` *field* on the paragraph, not an
  edge. A graph consumer walking `HAS_PARAGRAPH` therefore sees proposals as
  textless. `engine/retrieval/corpus.py` compensates by registering every
  paragraph as a node keyed by `paragraph_id` with `source_kind` and
  `document_id` attrs, which is a field join standing in for an edge.
  Adding `"NPRM"` to `HAS_PARAGRAPH.from` would make the parentage structural
  and symmetric with adopted ADs. It is deliberately not emitted today:
  `engine/ingest/emit.py` validates every edge against the contract and would
  refuse it, and the contract is not mine to edit.
- **`NPRM` has no `start_page` / `end_page` / `fr_citation`; only `Revision`
  does.** The Federal Register index supplies all three for a proposal exactly
  as it does for a final rule, and the corpus page count has to join on them.
  The ingest works around this by writing the *normalised* strings into the two
  fields the NPRM node does have -- `citation` gets the short `91 FR 66019`
  form and `page_range` gets `66019-66022`, both built from the index
  response's integers (see `engine/ingest/nprm_text.federal_register_page_range`
  and `engine/ingest/build._nprm_reference_fields`). The integers themselves,
  plus `fr_citation`, `fr_publication_date` and `resolved_via`, are in the
  `data/build/nprm_text.jsonl` sidecar. Declaring `fr_citation`, `start_page`
  and `end_page` on `NPRM` would let `engine/api/citations.py` read one shape
  for both document kinds instead of re-parsing a string.
  Note that the spreadsheet's own `citation` and `pages` cells are NOT what the
  node carries: the sheet's citation column is free prose and its page cell
  wraps the numbers four different ways, so 207 of 431 would not parse. Both
  sheet values are preserved verbatim in the sidecar as `sheet_citation` and
  `sheet_pages`, and the sheet's `publish_date` as `sheet_publish_date` -- it is
  one day early for 257 of 431 rows and is never used as the publication date.
