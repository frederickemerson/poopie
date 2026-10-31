# Rules: extraction and the applicability engine

Applicability prose in an AD is read once by a model into small, checkable `Rule`
records, each pinned to a verbatim quote; after that, every "does this AD apply to
this airplane?" answer comes from deterministic code with no model in it. The model
proposes, code verifies, and when verification fails the result is an honest
`CANNOT_DETERMINE`, never a guess.

Code: `engine/rules/*.py` (extraction and engine) and `engine/api/applicability.py`
(the join to the API). Contract vocabulary is in `contracts/contract.json`; refusal
semantics are in `docs/refusals.md`.

Measured 2026-10-31 around 12:15 from `data/build/rules.jsonl`, `cost_ledger.jsonl`
and the test suite (`python3 -m pytest tests/ -q`: 203 passed). An extraction was
running at the time, so `actions.jsonl` was empty (0 bytes) and counts will drift.

---

## Two-pass extraction

`extract.partition` splits a revision's paragraphs by the `paragraph_role` that
ingest assigned (`docs/ingest.md`):

| Pass | Reads paragraphs with role | Produces | Edge |
|---|---|---|---|
| Rules | `APPLICABILITY` | `Rule` nodes: `field`, `operator`, `value`, `source_quote`, `confidence`, `unparsed_reason` | `APPLIES_IF` from the Revision |
| Actions | `COMPLIANCE`, `REQUIRED_ACTIONS` | `Action` nodes: `description`, `compliance_time`, `compliance_basis`, `source_quote`, `external_ref` | `REQUIRES` from the Revision |

Role comes from the heading, not the letter, so the same code handles an AD whose
applicability is paragraph (c) and one whose is (b).

Either pass may also return an `external_applicability` / `external_document`
entry when applicability or a deadline is defined in a document this AD only
points at. These become `ForeignAD` or `ServiceBulletin` nodes with `held: false`
and a row in the delegations sidecar saying whether the delegation blocks
**applicability** or **compliance**.

Model: `claude-haiku-5-5` (`MODEL_EXTRACT`). Above 50 paragraphs
(`BATCH_THRESHOLD`) the Batch API is used. Every call goes through
`engine/llm/client.py`, which caches by content hash (so re-running over unchanged
paragraphs is free) and through `engine/llm/ledger.py`, which refuses a pass that
would breach the spend cap (`--cap`, default $5).

Current output (12 revisions): 27 rules.

| Operator | Count | | Field | Count |
|---|---|---|---|---|
| `eq` | 12 | | `manufacturer` | 12 |
| `model_matches` | 12 | | `model` | 12 |
| `exists` | 2 | | `modification` | 1 |
| `unparsed` | 1 | | `serial_number` | 1 |
| | | | `equipment` | 1 |

Real examples:

- `2026-20120#(c)`: "The Boeing Company Model 757-300 series airplanes" becomes
  `manufacturer eq "The Boeing Company"` and `model model_matches ["757-300"]`. Two
  rules, ANDed.
- `2026-21332#(c)`: "equipped with passenger service unit (PSU)-mounted video
  monitors" becomes `equipment exists`. The fleet data has no equipment column, so
  this evaluates to unknown and the engine asks the engineer (`NEED_CONFIG`).
- `2026-20666#(c)`: "having a high-pressure turbine (HPT) interstage seal serial
  number (S/N) specified in Appendix-A" becomes `serial_number unparsed`, with the
  reason that the appendix is not in the paragraph text.

---

## The schema pins the vocabulary to the contract

`schema.py` builds the JSON schema for each pass and puts the contract's enums into
it as `"enum": [...]`: `field` from `enums.rule_field`, `operator` from
`enums.rule_operator`, `compliance_basis` from `enums.compliance_basis`, `authority`
from `enums.authority`. They are read from `contracts/contract.json` **at runtime**,
not copied.

This is not decoration. A live call during design returned `operator: "equipped
with"`, a word the rules engine has no evaluator for. A schema that only says
`"type": "string"` lets that through silently and produces vocabulary nobody
downstream can act on. With the enum pinned, constrained decoding cannot emit it.
`vocab.py` re-checks the same thing from the other side at import: it fails loudly
if `FIELD_TO_AIRCRAFT` and the contract's `rule_field` disagree, or if the engine
does not name every contract operator.

The system prompts (`RULE_SYSTEM`, `ACTION_SYSTEM`) are byte-stable across all
paragraphs so the prompt cache hits; nothing per-paragraph or time-varying may
enter them. The per-paragraph payload goes in the user message.

Prompt rules that shape the output: one clause is one rule; alternatives inside a
clause are one rule whose value is a list; "certificated in any category" yields no
rule; models are expanded from shorthand but kept in the manufacturer's own
designation (never converted to an ICAO code); serial constraints are one
`serial_in_range` rule whose value is a list of `{low, high}` entries; a clause that
cannot be expressed is `unparsed` with a reason.

---

## The verbatim source-quote invariant

Every `Rule` and `Action` carries a `source_quote`, and it must appear in the
paragraph it came from. That is the provenance: a reader can click a rule and see
the exact words that produced it.

**Enforcement.** `records.build_rule` calls `contracts.contract.validate_rule`,
which raises `ContractViolation` if the quote is empty or is not a substring of the
paragraph text. `build_action` makes the equivalent check. Node shape and enum
membership are validated in the same call, and `check_value_shape` confirms the
`value` fits its operator (a range operator needs `{low, high}` entries; `eq` takes
exactly one value; `in` needs at least one).

**Retry.** In the rules pass, a paragraph with any failing rule gets exactly one
second attempt (`schema.retry_message`). The retry message repeats the paragraph
and lists the exact failures ("rule 2 (model/model_matches): ... source_quote is
not a verbatim substring"), and tells the model to emit `unparsed` rather than
adjust a quote it cannot find. A repaired quote is never substituted by searching
for something similar in the text: that would manufacture provenance.

**When it still fails.** The paragraph gets an `operator: "unparsed"` rule whose
`source_quote` is the whole paragraph (a verbatim substring of itself, and the text
a human then has to read) and `confidence: 0.0`. The reason lists the first three
failures. Any good rules from the same paragraph are kept alongside it. In the
engine, an unparsed rule evaluates to *unknown* and ends in `CANNOT_DETERMINE`
(below).

**Offline mode** (`--offline`, or no `ANTHROPIC_API_KEY`): every applicability
paragraph becomes one unparsed rule and every action paragraph one unparsed action.
There is deliberately no regex fallback: a pattern that works on the examples seen
would silently answer wrongly on the ones not seen.

**The action pass has no retry.** An action whose quote does not verify is
rejected and recorded in `paragraphs_with_rejected_action`; it is not retried and
no unparsed placeholder action is written. See Known issues.

---

## The rules engine

`engine.rules.engine.decide(aircraft, rules, *, revision_id, external_applicability)`
is the only producer of a contract decision value. It is a pure function: no
network, no LLM, no randomness, no I/O, no mutation of its inputs. A decision is a
few microseconds of Python; `matrix.py` decides the whole fleet-by-AD grid in one
pass and persists it, so the UI never recomputes.

### One rule: three outcomes, never two

`evaluate.evaluate(rule, aircraft)` returns a `Condition` whose outcome is `pass`,
`fail` or `unknown`, plus a plain-English `reason`. `fail` means the rule is
violated. `unknown` means the fleet record cannot answer, or the clause was never
parsed. A rule is **never** guessed into pass or fail.

Alternatives inside one rule value are ORed (any pass makes it pass; otherwise any
unknown makes it unknown; otherwise fail). Separate rules are ANDed by `decide`.

### Every operator

| Operator | Meaning | How it is evaluated |
|---|---|---|
| `eq` | field equals one value | Per-field comparison below. More than one value is a `RuleValueError`, reported as `unknown`. |
| `neq` | not equal | Evaluates `eq`, then negates a definite answer. An unknown stays unknown. |
| `in` | field is any of a list | ORs the per-field comparison over the list. |
| `not_in` | field is none of a list | Negation of `in`, same rule. |
| `model_matches` | aircraft is one of the AD's model designations | `match.model_matches`, table-driven (below). |
| `serial_in_range` | serial within any `{low, high}` entry, inclusive | `serials.in_range`, below. |
| `serial_not_in_range` | negation of the above | Negated definite answers only. |
| `exists` | the aircraft has the named item | Unknown whenever the Aircraft node has no such field (equipment, modification, part number, category), or the field is free text. |
| `not_exists` | negation of `exists` | Unknown in the same cases. |
| `unparsed` | clause could not be reduced | Always `unknown`; the `reason` is the extractor's `unparsed_reason`. |

Negation is applied only to a definite true/false. `neq` of an unknown is still
unknown, so a missing value can never flip into a pass.

**Per-field comparison.** `rule_field` maps to an Aircraft field through
`vocab.FIELD_TO_AIRCRAFT`. Four rule fields map to `None` (`category`, `equipment`,
`modification`, `part_number`) because the OpenSky data has no such column
(`docs/fleet.md`); every rule on them is unknown for every aircraft, by design. For
the rest:

- `model` and `manufacturer` go through the normalization table
  (`data/reference/aircraft_normalization.json`, via `engine/graph/normalize.py`),
  never byte equality: an AD's "757-200" and OpenSky's "757-232" are not the same
  string. The outcome is true (the table proves a match), false (the table proves a
  mismatch) or unknown (the table does not cover the string). If the table does not
  list the AD's variant but the aircraft is in the same family, the answer is
  unknown rather than a guess.
- `typecode` is a case-insensitive equality.
- `built_year` compares as integers.
- Free-text columns (`operator`, `engines`): equality proves a match; **inequality
  proves nothing**, because those strings are verbatim and unmerged in the source
  (`Alaska Airlines` and `Alaska Airlines, Inc.` are different strings). A
  difference is therefore unknown, not fail.

**Serial numbers** (`serials.py`). Real serials are not numbers: `24729`, `E-3121`,
`31-7852015`. A serial is split into a literal shape (separators and their
positions) and its ordered digit groups. Two serials are comparable only when the
shape and the number of digit groups match; `-` and ` ` are not interchangeable. An
unorderable pair returns unknown, never a guess, because guessing here grounds the
wrong airplane. Bounds are inclusive ("20003 through 20407 inclusive"), and an
inverted range (`low > high`) is unknown.

### How rules combine into a decision

Resolution order, with the reason for it (`engine.py`):

| # | Condition | Decision | Refusal | Resolvable by |
|---|---|---|---|---|
| 1 | any rule `fail` | `DOES_NOT_APPLY` | none | n/a |
| 2 | applicability delegated to a document we do not hold | `CANNOT_DETERMINE` | `EXTERNAL_SOURCE_REQUIRED` | load the referenced document |
| 3 | a rule is `unparsed` | `CANNOT_DETERMINE` | `CANNOT_DETERMINE` | a human reads the highlighted clause |
| 4 | any rule `unknown` otherwise | `CANNOT_DETERMINE` | `NEED_CONFIG` | the engineer supplies the value |
| 5 | no rules at all | `CANNOT_DETERMINE` | `CANNOT_DETERMINE` | a human reads the clause |
| 6 | every rule `pass` | `APPLIES` | none | n/a |

Step 1 comes first because a conjunction with a false term is false whatever else is
unknown. That stays safe even when applicability is delegated: a foreign document
can narrow the FAA-stated set, never widen it. Steps 2 to 4 are ordered by who can
fix the problem, and the blocker that only a document can resolve is named first.

Example, the 757 PSU case from `docs/refusals.md`: manufacturer and model pass,
`equipment exists` is unknown, so the result is `CANNOT_DETERMINE` with
`NEED_CONFIG`, `unknown_fields: ["equipment"]`, and every other condition shown
green.

### The proof tree

`Decision.proof_tree()` is self-contained JSON for the UI. It carries the decision,
the revision, the aircraft's identifying fields, the unheld external documents, the
`fired_rule_ids` (the rules that failed for `DOES_NOT_APPLY`, the rules that passed
otherwise), `unknown_fields`, the refusal, and one entry per rule in `conditions`:

```
rule_id, field, operator, value,
aircraft_field, aircraft_value,      # what the fleet record held
outcome, reason,                     # pass | fail | unknown, in plain English
paragraph_id, source_quote           # where in the AD this came from
```

So any node of the tree can be traced to the aircraft's recorded value on one side
and a quoted AD span on the other. `sse_payload()` and `refusal_payload()` emit
exactly the keys the contract's `decision` and `refusal` events declare;
`edge_attrs()` gives the `AFFECTED_BY` edge attributes.

Every refusal carries `code`, `detail`, `resolvable_by` and
`evidence_paragraph_ids`. The engine's "no rule extracted" refusal has no paragraph
to point at; the retrieval gate fills that gap (`docs/retrieval.md`).

---

## `engine/api/applicability.py`: the join to a query

This module contains no applicability logic. It answers a lookup question (which
aircraft and which revision is this query about?) and hands both to `decide`.

- **Revision:** the revision of the top retrieved hit.
- **Aircraft**, most specific first: an explicit `tail_number` argument, a tail
  number in the query text or plan, then a serial number. **A bare model name never
  selects an aircraft**: several hundred share a model, and picking one would
  invent the answer.
- If any of these is missing, the result is "no decision" with the reason in words
  (no rules loaded, no revision retrieved, no rules for that revision, no aircraft
  identified). It is reported, never defaulted.
- `fleet_matrix(store, revision_id)` runs `decide` over every aircraft for the
  BlastRadius grid.

The store reads `data/build/rules.jsonl`, `delegations.jsonl` and
`nodes.aircraft.jsonl` once at startup.

---

## CLIs

```
python3 -m engine.rules extract [--paragraphs P] [--out-dir D] [--cap USD]
                                [--offline] [--revision ID ...] [--limit N]
python3 -m engine.rules matrix  [--aircraft F] [--rules F] [--externals F]
                                [--out-dir D] [--limit N]
python3 -m engine.rules.extract_cli [--offline] [--limit N] [--budget USD]
```

`--cap` is a hard spend ceiling: the ledger refuses the pass up front. `--limit`
counts revisions in `engine.rules extract` and paragraphs in `extract_cli`.

---

## Known issues

**Fixed: `MAX_TOKENS` raised from 2048 to 8192.** An applicability paragraph that
enumerates many variants (one GE CF34 AD listed enough engine variants) overflowed
2048 output tokens and the JSON was cut off mid-array, losing rules. Evidence in
`data/build/cost_ledger.jsonl`: three `extract_rules` calls ended at exactly 2046
output tokens, which is the signature of a truncated response; later calls of 2,497
and 2,623 tokens completed once the ceiling was raised. I could not tie those three
rows to a named CF34 AD, so the CF34 attribution is the code comment's claim, not
mine.

**Fixed: truncation now raises a named error.** `engine/llm/client.py` used to
report truncated output as "model returned non-JSON", which sent the investigation
the wrong way. When `json.loads` fails and `stop_reason == "max_tokens"` it now
raises: `"<label>: output hit max_tokens=N and the JSON was cut off mid-structure.
Raise max_tokens; do not parse the fragment."` The "non-JSON" error remains for
other failures. I read this in the code; I did not find a test that forces it.

**Open: the quote check is looser than the prompt says.** The prompt tells the model
to copy "character for character" and says the check is a substring test.
`contract._norm` (used by `validate_rule`) and `records._norm` (for actions) collapse
whitespace **and lowercase** both sides before comparing. A quote that differs from
the paragraph only in case or spacing passes. This is still real provenance for a
reader, but it is not byte-exact, and any claim of "character-exact quotes" should
not be made on this evidence. The citation offsets in ingest are exact; rule quotes
are not tied to offsets.

**Open: the two extraction CLIs write different files.** `engine.rules.extract_cli`
writes `rules.jsonl`, `actions.jsonl`, `delegations.jsonl` and
`external_nodes.jsonl`, without `_type` keys or edges. `python3 -m engine.rules
extract` writes `rules.jsonl`, `actions.jsonl`, `nodes.rules.jsonl`,
`edges.rules.jsonl` and `externals.jsonl`, with `_type`. The API reads
`delegations.jsonl`; `engine/verify/rules_adapter.py` and `matrix` read
`externals.jsonl`. Whichever CLI was last run determines which readers work. The
files in `data/build/` today are from `extract_cli`.

**Open: the two paths mint different ids for the same document.** The extractor
builds `ForeignAD` ids as `f"{authority}:{number}"` and bulletin ids joined with
`":"`; ingest builds bulletin ids dash-joined (`docs/ingest.md`). If both outputs
are merged the same bulletin can become two nodes.

**Open: `rules_unparsed` in the report counts any rule with an `unparsed_reason`,**
not only `operator: "unparsed"`. Rule `2026-20680#(c)/r03` has operator `exists`
and a non-null reason ("only the bulletin reference is captured"), so it is counted
as unparsed in the report while the engine evaluates it as an unknown `exists`.

**Open: unattributable unparsed clauses are filed under `model`.** `rule_field` has
no neutral value, so `UNPARSED_FIELD = "model"` is used. An unparsed rule therefore
appears in `unknown_fields` as `model`, which can mislead the UI about what is
unknown.

**Open: no retry or placeholder in the action pass** (above). A rejected action
leaves a silent gap in the extracted actions rather than an `UNPARSED` one.
`actions.jsonl` was empty at measurement, so action extraction has not been
checked against real output here.

**Unverified docstring claim:** `extract.py` states a measured cost of
`$0.000076` per paragraph on Haiku 5.5. The ledger shows 56 uncached `extract_rules`
calls totalling $0.0163, about `$0.00029` each. The code's budgeting ceiling
(`PER_ITEM_USD = 0.0005`) is consistent with the ledger; the `$0.000076` figure is
not.
