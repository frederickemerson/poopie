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
| **NPRM spreadsheet** (`data/raw/AD Notice of Proposed Rulemaking (AD NPRM).xlsx`) | The FAA's own export of proposed rules: docket, citation, comments-due date, make, model, summary | 431 data rows, 22 columns, one sheet. Three columns (AC Reference, AIR Policy Reference, Additional Reference) are empty in every row and are not read. Read by `engine/ingest/nprm_xlsx.py`. |
| **Challenge AD index** (`data/reference/challenge-4-ad-index.xlsx`, sheet `nprm_index`) | The same 431 proposals, re-exported by the challenge organizers with a stable `record_id`, a `federal_register_link` and four derived columns | It is the key the organizers publish and ask citations to name, so `record_id` is the `nprm_id` of every proposal node. Read by `engine/ingest/nprm_index_xlsx.py`, whose docstring records which FAA-export quirks still hold and which the organizers changed. Its `publish_date` column is one day early for 257 of the 431 rows and is therefore never used as a publication date. |
| **Federal Register proposal XML** (`conditions[type][]=PRORULE`) | The full text of each proposal, as paragraphs with character offsets | Same authority as a final rule's XML, and the same `<HD SOURCE="HD1">` markup, so `ad_xml.py` parses it unchanged. The spreadsheet's summary column is a paraphrase; this is the document. |
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
challenge index --> rows --> resolve to an FR document --> PRORULE XML (cached)
      |                                                              |
      |                                                              v
      |                              refs (ForeignAD, ServiceBulletin), supersession
      |                                                              |
      v                                                              v
nodes.jsonl / edges.jsonl / paragraphs.jsonl / nprm_paragraphs.jsonl / sidecars
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
and an AD gets a `PROPOSED_BY` edge to each NPRM on its docket **that was published
before the AD's earliest revision**. A shared docket alone is not enough: dockets
are reused, and without the date guard the build emitted
`AD 2009-17-05 (adopted 2009-08-17) PROPOSED_BY NPRM-268 (published 2011-07-28)`,
a rule proposed two years after it was adopted. The guard uses the Federal
Register's publication date, never the spreadsheet's `publish_date`. Edges rejected
this way are listed in the ingest report as `proposed_by_skipped`.

One node per index **row**, not per docket. 99 of the distinct dockets appear on
more than one row (re-notices and supplemental NPRMs, not duplicates), so the
docket cannot be the key. The `nprm_id` is the challenge index's `record_id`
(`NPRM-001`), for two reasons: it is the handle the organizers publish and ask
citations to name, and it contains no `@`. A citation id is
`{paragraph_id}@{char_start}-{char_end}` and is split on its **first** `@`, so an
id built from docket and date — the earlier scheme — would have silently truncated
every citation made to a proposal.

**Only a minority of dockets join.** Measured on the current build
(`--since 2021-01-01`, 2,161 revisions):

| | Count |
|---|---|
| NPRM rows | 431 |
| Unique dockets in the index | 322 |
| Dockets joined to a final rule | 42 |
| Dockets with no final rule yet | 280 |
| `PROPOSED_BY` edges emitted | 41 |
| `PROPOSED_BY` edges rejected by the date guard | 1 |

Why so few: the spreadsheet is a list of proposals, and most proposals have not
become final rules yet. I have confirmed the low rate; I have **not** confirmed the
explanation by dating the unjoined NPRMs, so treat "not yet final" as the likely
cause rather than a measured one. A docket with no final rule is not an error and
carries `has_final_rule: false`.

---

## Proposal full text: resolving 431 rows to Federal Register documents

The spreadsheet's `summary` column is a paraphrase, roughly 150 pages in total. The
documents behind it are the corpus. `engine/ingest/nprm_text.py` resolves each row
of the challenge index to a Federal Register document and fetches its XML into
`data/raw/fr_nprm/`.

**The link column cannot carry this.** Of the 431 rows, 25 have no
`federal_register_link` at all and 169 more hold prose instead of a URL, so only
237 cells yield a document number (15 of those name two). The column is therefore a
hint, not the key, and a missing link is not a fetch failure. Resolution tries three
routes in order, and every row records which one answered in `resolved_via`:

| Route | Rows | What it matches on |
|---|---|---|
| `link` | 234 | a document number parsed out of the cell, confirmed against the index |
| `citation` | 195 | the Federal Register **start page**, within a ±7-day window of the sheet's date |
| `docket_date` | 2 | the docket id plus the date window, when the page does not match |
| `unresolved` | 0 | |

**Why the page and not the date.** The first attempt used the sheet's `publish_date`
as an equality test and resolved 174 of 431. The measured offset distribution is
exactly `{0 days: 174, +1 day: 257}` — the sheet is one day early for every row
before 2022 — so the date became a window and the start page became the identity.
Pages run continuously through an annual volume, which makes `(volume, start page)`
a unique address; where two notices begin on the same page, a tiebreak on docket
agreement and end page picks one. Result: 431 resolved, 0 duplicates.

**The proposals index must not be filtered by term.** `conditions[term]=airworthiness
directives` is a lossy full-text filter: it drops `05-5707`, titled "Airworthiness
Directives; GROB-WERKE Model G120A Airplanes", from the 2005 proposal index. The
harvest asks for every `PRORULE` in a year instead (measured maximum 620, under the
1000-row cap) and filters locally.

### The markup is the same as a final rule's

NPRM XML carries the same `<HD SOURCE="HD1">(c) Applicability</HD>` labelled
headings as an adopted AD, so `parse_ad_xml` reads it unchanged and **no prose regex
was added anywhere**. Of the 431 documents: 200 parse as `labelled_headings`, 97 as
`inline_labels` (the legacy form, also already supported), and 134 contain no
proposed text to section.

Those 134 are not parse failures, and the ingest does not guess why they are empty:
it groups them by the Federal Register's own `action` field, verbatim.

| Federal Register action | Documents |
|---|---|
| Proposed rule; withdrawal. (3 spellings) | 124 |
| Notice of proposed rulemaking (NPRM); withdrawal. | 4 |
| Notice of proposed rulemaking (NPRM); extension of comment period. (2 spellings) | 3 |
| Notice of public meeting; reopening of the comment periods. | 1 |
| Notice of proposed rulemaking (NPRM). | 2 |

A withdrawal has no proposed text by definition. The two genuine NPRMs in the last
row are a known gap, recorded rather than papered over: `E8-18239` is a 14 CFR
Part 61 rulemaking (Robinson training requirements) and not an AD proposal at all —
it appears to be in the challenge index by mistake — and `04-28145` is a real AD
proposal whose legacy inline labels sit outside the `EXTRACT` wrapper that
`ad_xml.py` requires. Relaxing that wrapper would change how all 2,161 adopted
revisions are parsed, which is the wrong blast radius for one document.

### Proposals are a separate file, on purpose

Proposal paragraphs are written to `data/build/nprm_paragraphs.jsonl`, never to
`paragraphs.jsonl`. That is not tidiness: `paragraphs.jsonl` is the file the rules
extractor reads, so the separation is what makes "no NPRM paragraph can supply an
obligation or a deadline" a property of the file layout rather than a filter someone
can forget. `engine/ingest/emit.py` refuses to route a paragraph by call order — it
reads `source_kind` and raises `ContractViolation` on any incoherent parentage
(both ids set, neither set, a proposal staged anything but `PROPOSED`, a revision
staged `PROPOSED`, or a `paragraph_id` that is not `{document_id}#{label}`).

### Pages

| | Documents | Σ (end − start + 1) | Distinct (volume, page) pairs |
|---|---|---|---|
| All resolved proposals | 431 | 1,338 | 1,282 |
| Documents with proposed text | 297 | 1,105 | 1,061 |
| *(for comparison)* the sheet's own `pages` cell | 431 | 1,341 | 1,285 |

The sum double-counts, because short notices share a page with whatever else was
printed that day; the distinct count is the union of `(volume, page)` pairs and is
the honest figure. Both clear the 1,000-page bar.

The quoted numbers come from the index response's `start_page` and `end_page`
integers, bucketed by volume — **not** from the sheet's `pages` cell. Two reasons,
and both change the answer:

* the cell's wrapper varies four ways ("(Pages 1-2)", "Pages 1-2", "(Page 1)", and
  one doubled closing paren), and a page number is only unique inside its volume,
  which the cell does not carry. Taking the volume from the sheet's `publish_date`
  would put every pre-2022 January notice in the wrong volume.
* for two rows the cell is simply about a different document. `NPRM-186` and
  `NPRM-287` are both withdrawal notices, and their page cells ("(Page
  74210-74213)", "Page 29148-29149") name the pages of the *original* NPRM being
  withdrawn, while the Register prints the withdrawal at 86 FR 14289-14290 and
  81 FR 13303. The sheet's own `citation` column agrees with the Register in both
  cases ("Volume 86, Number 48 (Monday, March 15, 2021)" → 2021-03-15), which is
  how the resolution was confirmed; only the page cell disagrees. That is the whole
  3-page gap between the two rows of the table.

`engine/api/citations.corpus_pages` recounts the same thing from the built nodes
instead of from the harvest, and `tests/test_nprm_text.py` fails if the two
disagree — the corpus page count is a published number, so it is not allowed to
depend on which layer you ask.

The arithmetic itself lives in **`engine/graph/pages.py`**, and every layer that
prints a page range to a reader now calls that one function: the proposal harvest
(`nprm_text.py`), the final-rule collector (`collect.py`), the retrieval corpus
and `engine/api/citations.py`. There were four implementations before, and they
did agree on real data — which is precisely why nothing caught the one that would
print a reversed `"66022-66019"` for an inverted pair. Two functions that agree
are a convention; one function is an invariant.

`tests/test_nprm_retrieval.py` therefore asserts *identity* of the binding in each
module rather than equality of their output — a freshly re-introduced local copy
would pass every case anyone thought to list — plus, corpus-wide, that no
paragraph's range disagrees with its own document node. That second check is what
caught 25,687 adopted paragraphs reporting "page range not recorded" beside a
populated `fr_citation`, while the Register had stated their pages all along. A
page the source never gave must not be invented; a page it did give must not be
denied.

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
| `data/build/nodes.jsonl` | 10,456 nodes: Docket 2,396, Revision 2,161, AD 2,117, ServiceBulletin 1,832, ForeignAD 1,519, NPRM 431. Paragraph nodes are written to the paragraph files instead. Aircraft nodes are merged in by `engine.graph.aircraft_nodes --merge`. |
| `data/build/edges.jsonl` | 34,484 edges: HAS_PARAGRAPH 25,687, IN_DOCKET 2,550, HAS_REVISION 2,161, REFERENCES_SB 2,018, ADOPTS_MCAI 1,724, SUPERSEDES 303, PROPOSED_BY 41. There is no `HAS_PARAGRAPH` edge from an NPRM: the contract declares that edge `from: ["Revision"]` only, so a proposal's paragraphs are linked by their own `nprm_id` field (see `docs/contract_change_requests.md`). |
| `data/build/paragraphs.jsonl` | 25,687 adopted paragraphs. **This is the file the rules extractor reads**, and no proposal paragraph is ever written to it. |
| `data/build/nprm_paragraphs.jsonl` | 3,048 proposal paragraphs, every one `source_kind: NPRM`, `document_stage: PROPOSED` |
| `data/build/revision_text.jsonl` | sidecar: `plain_text` per revision (2,161) |
| `data/build/nprm_text.jsonl` | sidecar: `plain_text` per proposal (431), plus the Federal Register `fr_action`, `fr_publication_date`, `fr_citation`, `start_page`, `end_page`, `resolved_via`, and the spreadsheet's own `sheet_publish_date` / `sheet_pages` / `sheet_citation` kept verbatim as the source's words |
| `data/build/provenance.jsonl`, `data/build/provenance_nprm.jsonl` | audit manifests (2,161 and 431): SHA-256 over the raw response bytes, `retrieved_at`, `source_bytes`. `--verify-provenance` re-hashes both caches against them. |
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
                               [--nprm-index NPRM_INDEX] [--no-nprm-text]
```

| Flag | Default | Meaning |
|---|---|---|
| `--since` | `2021-01-01` | earliest `publication_date` |
| `--until` | today | latest `publication_date` |
| `--term` | `airworthiness directives` | Register search term |
| `--offline` | off | use the caches only; raise if a needed index response is absent |
| `--skip-nprm-dockets` | off | do not look up final rules for spreadsheet dockets outside the window |
| `--limit` | none | cap documents, for smoke runs |
| `--nprm-index` | `data/reference/challenge-4-ad-index.xlsx` | the challenge index to read proposals from |
| `--no-nprm-text` | off | skip the proposal full-text harvest; NPRM nodes are still emitted from the spreadsheet, without `plain_text` or paragraphs |

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

**Fixed: the built data predated a label-format change, and the build was a
one-month smoke window.** Both were resolved by a full rebuild at the CLI default:
`data/build/` now holds 2,161 revisions and 2,117 ADs from 2021-01-01 onward plus
all 431 proposals, with paragraph ids in the current label format. The retrieval
index was rebuilt against it (fingerprint `28735:1d5b1a33d4895b48`).

**Open: one genuine AD proposal has no sectioned text.** `04-28145` is a real AD
proposal whose legacy inline labels sit outside the `EXTRACT` wrapper
`ad_xml._sections_from_inline_labels` requires, so it contributes a document and
pages but no paragraphs. Relaxing the wrapper would change how all 2,161 adopted
revisions parse, which is too wide a blast radius for one document. Its full text
is still in `data/build/nprm_text.jsonl`.

**Open: `E8-18239` is not an airworthiness directive.** It is a 14 CFR Part 61
rulemaking (Robinson helicopter training requirements) and appears to be in the
challenge index by mistake. It is ingested as given — the index is the organizers'
dataset and this ingest does not second-guess its membership — but it has no AD
paragraph structure and never will.

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
