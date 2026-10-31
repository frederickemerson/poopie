# Ingest

Turns three public sources into the JSONL graph the rest of the engine reads: AD
nodes, the paragraphs of each AD with exact character offsets, and references to
documents we do not hold. Nothing downstream re-parses prose for facts the
sources already state in structured form.

Code: `engine/ingest/*.py`. Entry point: `python3 -m engine.ingest.build`.
Numbers below were measured on **2026-10-31 around 12:15** from `data/build/` and
`data/raw/`, while a harvest and an extraction were running, so totals will drift.
Where a count matters I say what it was measured over.

---

## Sources, and why each is authoritative

| Source | Used for | Why it is the authority |
|---|---|---|
| **Federal Register API** (`federalregister.gov/api/v1`) | Every FAA final rule: document number, `docket_ids`, publication and effective dates, the full-text XML | It is the legal publication of the rule. The XML is the document of record; the index fields are the Register's own metadata. |
| **NPRM spreadsheet** (`data/raw/AD Notice of Proposed Rulemaking (AD NPRM).xlsx`) | Proposed rules: docket, citation, comments-due date, make, model, summary | The only source of proposals in this project. 431 data rows, 22 columns, one sheet. Three columns (AC Reference, AIR Policy Reference, Additional Reference) are empty in every row and are not read. |
| **OpenSky aircraft database** (`data/raw/fleet/aircraftDatabase.csv`) | The demo fleet: registration, serial, model, typecode, operator | Real registrations and serial numbers. It has no equipment, modification, part-number or category column, which is why those rule fields can never be evaluated (see `docs/fleet.md`). |

The fleet loader and selection rules are documented in `docs/fleet.md` and are not
repeated here.

---

## Pipeline

```
FR index (per year, split by month on overflow) --> AD filter --> XML (cached)
      |                                                              |
      |   docket lookups for spreadsheet dockets                     v
      +--------------------------------------------------->  paragraphs + offsets
NPRM xlsx --> rows, normalized dockets                               |
                                                                     v
                                          refs (ForeignAD, ServiceBulletin), supersession
                                                                     |
                                                                     v
                         nodes.jsonl / edges.jsonl / paragraphs.jsonl / sidecars
```

Two passes build the final-rule set (`collect.py`):

1. every FAA final rule published in `[--since, --until]`;
2. unless `--skip-nprm-dockets`, every document filed under each spreadsheet docket
   not already covered, whatever its publication date. The spreadsheet spans 2001
   to 2026, so this pass reaches final rules decades older than the window.

Downloads are cached and never repeated: index responses in `data/raw/fr_index/`,
XML in `data/raw/fr_ad/<document_number>.xml`. A rebuild after the first run is
local. `--offline` reads only the caches and raises if one is missing.

### The index API has a 1000-row cap

`per_page` caps at 1000 while `count` can exceed it. The cached response
`rules_2021-01-01_2026-10-31.json` reports `count=2166` and returns 1000
results. So `fr_client.py` fetches a window, and if `count > len(results)` splits
it by month. A month that still overflows raises `FederalRegisterError`; nothing is
silently truncated.

### What counts as an AD

A rule is an AD **exactly when its structured `docket_ids` names an AD number**.
Rules that match the search term but are not ADs (BasicMed updates, airworthiness
criteria, miscellaneous amendments) go to `skipped_non_ad` with their title. The
title and body are never consulted. In the current build `skipped_non_ad_rules` is 0.

---

## `docket_ids`: docket, amendment and AD number as structured values

The Register returns `docket_ids` as a list of strings. `docket_ids.py` extracts
three facts from it and nothing else:

| Fact | Pattern | Example |
|---|---|---|
| docket | `FAA-YYYY-NNNN` (or legacy `2002-NM-352-AD`) in an entry starting "Docket" | `FAA-2026-3487` |
| amendment | `39-NNNNN` in an entry mentioning "Amendment"/"Amdt" | `39-23476` |
| AD number | `AD YYYY-WW-NN` with optional `R1`-style suffix, or a bare number occupying a whole entry | `2026-20-03` |

The module docstring lists the shapes observed across all 2,166 FAA final rules
published 2021-01-01 to 2026-10-31. The common case (2,137 documents) is four
entries: docket, project identifier, amendment, AD. The rest are variations the
parser handles by searching inside entries instead of full-matching them, because
entries are not positional and sometimes carry two facts
(`"Amendment 39-21656 AD 2021-15-09"`). Non-AD rules, such as
`"Amdt. Nos. 11-64, 21-105, 43-51, 107-8"`, yield no AD number and are skipped.

The distinction that matters: the `docket_ids` module docstring states that the
prose body restates these facts "inconsistently", so the structured list is the
authority and the body is read only for paragraphs. I did not independently
measure that inconsistency. For revision `2026-20103` the structured list and the
body header agree: AD `2026-20-03`, amendment `39-23476`, docket `FAA-2026-3487`.
Note the Register *document number* (`2026-20103`) and the *AD number*
(`2026-20-03`) are different identifiers; `Revision` is keyed on the former, `AD`
on the latter.

The same module normalizes the spreadsheet's hand-maintained `Docket Number` column.
Of its distinct values, 60 were not in the plain `FAA-YYYY-NNNN` form (re-notice
suffixes `R1`/`_S`/`-W`, spaces, legacy directorate dockets, one cell naming two
dockets); `normalize_sheet_docket` returns the docket ids plus the raw cell.

---

## Headings to `paragraph_role`

`ad_xml.py` walks the XML tree with lxml; markup is never regex-matched. Two real
structures exist and are chosen by what the document contains, not by its date:

| Structure | Where the label lives | Example |
|---|---|---|
| `labelled_headings` (about 2010 onward) | In the heading: `<HD SOURCE="HD1">(c) Applicability</HD>` then `<P>` blocks | all 29 documents in the current build |
| `inline_labels` (legacy) | The heading carries the topic only; the label opens the paragraph: `<P>(g) This amendment becomes effective...</P>` | 2004-era ADs such as `04-6499` |

A document that fits neither gets structure `none` and no paragraphs; the parser
never raises on it.

`roles.py` classifies the **heading text**, not the paragraph letter, because
letters shift between ADs: "Required Actions" is (g) in one fixture and
"Requirements" is (g) in another, and a 2004 AD puts "Effective Date" at (g).
First match wins, so specific patterns precede general ones:

| Heading pattern | `paragraph_role` |
|---|---|
| "alternative method...", "AMOC" | `AMOC` |
| "(Retained) exceptions to...", "differences from" | `EXCEPTIONS` |
| "credit for previous..." | `CREDIT` |
| "material incorporated by reference" | `IBR` |
| "effective date" | `EFFECTIVE_DATE` |
| "affected ADs" | `AFFECTED_ADS` |
| "applicability..." | `APPLICABILITY` |
| "subject" | `SUBJECT` |
| "unsafe condition", "reason" | `UNSAFE_CONDITION` |
| "compliance", "compliance time(s)" | `COMPLIANCE` |
| "(new/retained) required/requirements...", "actions and compliance" | `REQUIRED_ACTIONS` |
| "additional information", "related information" | `ADDITIONAL_INFO` |
| anything else | `OTHER` (a real role, not a dropped paragraph) |

The rule set was built from 176 distinct heading texts in a 120-document sample
(stated in `roles.py`; I did not re-derive that figure). Every emitted role is
checked against the contract enum at import.

Role counts in the current build (353 paragraphs, 29 revisions):

| Role | Count | | Role | Count |
|---|---|---|---|---|
| OTHER | 35 | | AMOC | 24 |
| REQUIRED_ACTIONS | 32 | | EXCEPTIONS | 23 |
| EFFECTIVE_DATE | 29 | | CREDIT | 7 |
| AFFECTED_ADS | 29 | | SUBJECT | 29 |
| APPLICABILITY | 29 | | UNSAFE_CONDITION | 29 |
| COMPLIANCE | 29 | | ADDITIONAL_INFO | 29 |
| IBR | 29 | | | |

Duplicate labels inside one document are kept as `c~2` and noted in
`parse_notes`; the current build recorded none.

---

## The character-offset scheme

Every revision has one `plain_text`, assembled from its pieces:

```
plain_text = header_line + "\n\n" + para_1 + "\n\n" + para_2 + ...
para_n     = heading + "\n" + body paragraphs joined by "\n"
```

`char_start`/`char_end` of each paragraph index into that string, so a paragraph's
`text` is exactly `plain_text[char_start:char_end]`. Because the string is built
from the same pieces the offsets are computed from, they are exact by construction,
and `assert_offsets_round_trip` proves it for every paragraph **before anything is
written**. It is an assertion, not a warning: a silent offset error would corrupt
every citation built on that revision.

A citation id is `{revision_id}#{label}@{char_start}-{char_end}`. Example from the
current build: revision `2026-20103`, applicability paragraph, `char 217-644`. I
re-checked that all 12 paragraphs of `2026-20103` satisfy
`plain_text[start:end] == text` against `revision_text.jsonl`.

`revision_text.jsonl` is a sidecar holding each revision's full `plain_text`,
because the contract's `Revision` node has no field for the text (the sidecar is described alongside the other contract gaps in `docs/contract_change_requests.md`; I did not check that file for this specific entry).

---

## NPRM to final rule: the join on docket number

An NPRM row and a final rule belong together when they share a docket id. Both
sides are reduced to the same form (`FAA-YYYY-NNNN`, or the legacy directorate
form) and joined through a `Docket` node: NPRM and AD both get an `IN_DOCKET` edge,
and an AD gets a `PROPOSED_BY` edge to each NPRM on its docket.

One node per spreadsheet **row**, not per docket. 99 of the distinct dockets appear
on more than one row (re-notices and supplemental NPRMs, not duplicates), and the
identity is docket plus Federal Register citation, which is unique across all 431
rows (per `nprm_xlsx.py`, which I did not re-derive).

**Only a minority of dockets join.** Measured on the current build, which covers the
window `2026-10-01..2026-10-31`:

| | Count |
|---|---|
| NPRM rows | 431 |
| Unique dockets in the spreadsheet | 322 |
| Dockets that also have a final rule in the build | 22 |
| Dockets with no final rule in the build | 300 |
| `PROPOSED_BY` edges | 22 |

That 22 is for a one-month window only: the report shows
`dockets_queried_outside_window: 0`, so the second pass (look up each spreadsheet
docket) did not run for that build. The cached docket lookups tell a more useful
story. At 12:15, `data/raw/fr_index/` held 288 `docket_*.json` responses, and **12
of them contain a final rule naming an AD number** (3 more files had no `results`
key and were not counted). So about 4% of looked-up dockets had a final rule in
the Register. This is a harvest in progress; the denominator will grow to the full
322.

Why so few: the spreadsheet is a list of proposals, and most proposals have not
become final rules yet. I have confirmed the low rate; I have **not** confirmed the
explanation by dating the unjoined NPRMs, so treat "not yet final" as the likely
cause rather than a measured one. A docket with no final rule is not an error and
carries `has_final_rule: false`.

---

## Cross-regulator references: `ForeignAD` and `ServiceBulletin`

The Federal Register exposes no field naming the foreign AD or bulletin an FAA AD
adopts. The only structured hint is a `Project Identifier MCAI-*` entry in
`docket_ids`, which says the AD came from a foreign authority's mandatory
continuing airworthiness information, not which document. So the identity has to
come from the text, and `refs.py` takes it from the most authoritative place in the
document: first the `IBR` paragraph (the AD's own list of incorporated material),
then the remaining operative paragraphs.

This is regex over prose, and I say so plainly: it is the one place in ingest where
the source gives no structured alternative.

Every reference is emitted with **`held: false`**, because we hold the FAA text and
never the referenced document. That flag is what lets the rules engine refuse
instead of inferring applicability it cannot see.

Counts in the current build:

| Node | Count | `held` |
|---|---|---|
| `ForeignAD` | 16 (15 EASA, 1 TCCA) | all `false` |
| `ServiceBulletin` | 55 | all `false` |
| `ADOPTS_MCAI` edges | 16 | |
| `REFERENCES_SB` edges | 63 | |

Authority tokens seen in the text: "European Union Aviation Safety Agency" 11,
"EASA" 4, "Transport Canada" 1. Spelled-out names and abbreviations are mapped to
the contract's `authority` enum, so "EASA AD 2025-0208" and "European Union
Aviation Safety Agency (EASA) AD 2025-0208" are one node, `EASA:2025-0208`. A
regulator the enum does not model goes to the enum's catch-all, with the raw token
preserved in the id.

Real example (`delegations.jsonl`): revision `2026-20103` applies to Airbus
Helicopters AS350/AS355/EC120/EC130 models "as identified in European Union
Aviation Safety Agency AD 2025-0159, dated July 24, 2025"; this yields
`ForeignAD EASA:2025-0159`.

`ingest_report.json` also records how often an AD delegates: of 28 ADs, 10 (35.7%)
delegate **applicability** to a document we do not hold, and 25 (89.3%) delegate
applicability **or compliance**. That is the share of the corpus where a plain
retrieval answer would be unsafe.

### Supersession

`supersession.py` reads paragraph (b) "Affected ADs". The verb carries the meaning:
"replaces", "supersedes", "removes", "cancels", "revises" produce a supersession
edge; "affects" and "is related to" do not, because conflating them would retire an
AD still in force. A referenced AD outside the corpus is recorded as dangling and
no node is invented. Current build: 0 supersession edges, 1 same-amendment
correction, 5 dangling references.

---

## Outputs

| File | Contents (current build) |
|---|---|
| `data/build/nodes.jsonl` | 887 nodes: NPRM 431, Docket 328, ServiceBulletin 55, Revision 29, AD 28, ForeignAD 16. Paragraph nodes are written to `paragraphs.jsonl` instead. Aircraft nodes are merged in by `engine.graph.aircraft_nodes --merge`; none were present at measurement. |
| `data/build/edges.jsonl` | 944 edges: IN_DOCKET 461, HAS_PARAGRAPH 353, REFERENCES_SB 63, PROPOSED_BY 22, HAS_REVISION 29, ADOPTS_MCAI 16 |
| `data/build/paragraphs.jsonl` | 353 paragraphs |
| `data/build/revision_text.jsonl` | sidecar: `plain_text` per revision (29) |
| `data/build/make_normalization.json` | sidecar: raw manufacturer strings behind each normalized make |
| `data/build/ingest_report.json` | the report this document quotes |

Lines are built from the contract's field list, so a node carries exactly the
declared fields (absent values are explicit nulls) and a typo becomes an error at
write time (`emit.py`).

---

## CLI

```
python3 -m engine.ingest.build [-h] [--since SINCE] [--until UNTIL]
                               [--term TERM] [--offline]
                               [--skip-nprm-dockets] [--limit LIMIT]
```

| Flag | Default | Meaning |
|---|---|---|
| `--since` | `2021-01-01` | earliest `publication_date` |
| `--until` | today | latest `publication_date` |
| `--term` | `airworthiness directives` | Register search term |
| `--offline` | off | use the caches only; raise if a needed index response is absent |
| `--skip-nprm-dockets` | off | do not look up final rules for spreadsheet dockets outside the window |
| `--limit` | none | cap documents, for smoke runs |

Other ingest modules: `python3 -m engine.ingest.fleet --demo-fleet` builds the fleet
(see `docs/fleet.md`).

---

## Known issues

**Fixed: the month windower hardcoded February as 29 days.** `_split_by_month`
used a hand-written day table, so a non-leap year produced the window
`2021-02-01..2021-02-29`. The Register API answered HTTP 400, and the harvest
**silently stopped after January**. Fixed by using `calendar.monthrange(year,
month)`, which is correct for every year. Regression tests are in
`tests/test_fr_windows.py` (non-leap February never exceeds the real month, window
ends match the calendar, leap February is 29, windows cover every day of the year).
The cache now holds `rules_2021-02-01_2021-02-28.json` with 45 documents.

**Open: the built data predates a label-format change.** `ad_xml.py` currently
emits paragraph labels without parentheses (`a`, `c`), and `tests/test_ad_xml.py`
asserts `list("abcdefghijkl")`. The files in `data/build/` (written 11:14, with
`ad_xml.py` modified 11:17) carry `(a)`, `(c)`, so paragraph ids look like
`2026-20103#(c)`. Offsets are unaffected (verified above) but a rebuild will rename
every paragraph id, and `rules.jsonl`, `delegations.jsonl` and the retrieval index
all key on the old ids. Rebuild and re-extract together. I did not rebuild.

**Open: the current build is a one-month smoke window.** It holds 28 ADs from
2026-10-01..2026-10-31, not the 2021-onward corpus the CLI default describes. The
2,166-document index is cached; the XML for the full window is not yet
downloaded (`data/raw/fr_ad/` held 803 files at measurement).

**Open: `ServiceBulletin` nodes are over-split.** The 55 nodes include variants of
the same bulletin, for example `BOEING-757-53A0122-RB`, `BOEING-757-53A0122` and
`757-53A0122-RB`, and some with a junk manufacturer prefix
(`WHERE-BOEING-757-53A0122-RB`, `AD-WHERE-BOEING-B787-81205-SB270051-00-RB-R001`).
`_merge_bulletins` folds mentions that share a number key, but the `RB` suffix and
the manufacturer-from-preceding-words heuristic defeat it. 55 therefore overstates
the number of distinct bulletins. Not fixed.

**Open: the `ForeignAD` and `ServiceBulletin` id schemes differ between ingest and
the rules extractor.** Ingest ids are `EASA:2025-0159` (ForeignAD) and
dash-joined (`BOEING-757-53A0122`); the rules extractor builds
`f"{authority}:{number}"` and `":"`-joined bulletin ids. Same document, potentially
two nodes if both outputs are merged. See `docs/rules.md`.

**Limit: `refs.py` is regex over prose.** Its coverage is the authority and
bulletin phrasings it was written against. A phrasing it does not match is a
reference we do not record, which makes a revision look less delegating than it is.
Not measured against a labelled set.

**Not verified:** the `roles.py` docstring figures (176 headings, 120-document
sample), the `nprm_xlsx.py` docstring figures (323 distinct dockets, 99 repeated,
60 non-standard), and the "2,137 of 2,166" docket-shape count. The build report
shows 322 unique dockets, one fewer than the docstring's 323; I did not trace the
difference.
