
## Fleet data layer (OpenSky) - no schema change requested, notes only

- `category` (rule_field): the contract `Aircraft` node has no `category` field, and OpenSky's only related column (`categoryDescription`, a weight class) is not the certification category an AD means. Left unmapped; every `category` rule resolves to CANNOT_DETERMINE for this fleet. If a real source for certification category is added later, the Aircraft node would need the field.
- `equipment`, `modification`, `part_number` have no Aircraft field and no OpenSky column; same outcome.
- `Aircraft.manufacturer` is raw OpenSky text and may be null even when `typecode` implies a manufacturer; it is deliberately not back-filled (derived, not source data). Join via `engine/graph/normalize.py`.
