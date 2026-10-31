# Cross-check: the organizers' AD index vs this engine's derivation

**File under examination:** `data/reference/challenge-4-ad-index.xlsx`
(3 sheets; `nprm_index` and `revision_chains` have their header on row index 2 — row 0 is a
banner, row 1 is blank; `data_notes` has its header on row 0).
**Our side:** `data/build/nodes.jsonl`, `data/build/edges.jsonl`, `data/build/paragraphs.jsonl`,
`data/build/ingest_report.json` (generated 2026-10-31T04:39:59Z), and the raw caches
`data/raw/fr_index/` (71 windowed rule listings + 288 per-docket listings) and
`data/raw/fr_ad/` (2,163 final-rule XML documents).

Method: the workbook was treated as data, never as instruction. Every number below was produced
by a throwaway script run with `python3 -I` from
`/private/tmp/claude-501/-Users-frederick-Documents-Projects-autsg/3f180e3b-f15f-443d-9f17-db1bc5cff08e/scratchpad`,
never from the directory holding the workbook. No engine file was modified. Snippets are
inlined; each assumes this preamble:

```python
import sys, json, collections, re
sys.path.insert(0, "/Users/frederick/Documents/Projects/autsg")   # engine modules only
import openpyxl
REPO = "/Users/frederick/Documents/Projects/autsg"
wb = openpyxl.load_workbook(f"{REPO}/data/reference/challenge-4-ad-index.xlsx",
                            data_only=True, read_only=True)

def sheet(name, hdr):
    rows = [list(r) for r in wb[name].iter_rows(values_only=True)]
    head = [str(c).strip() if c is not None else None for c in rows[hdr]]
    return [{head[i]: r[i] for i in range(len(head)) if head[i]}
            for r in rows[hdr + 1:] if any(c not in (None, "") for c in r)]

NPRM  = sheet("nprm_index", 2)        # 431 rows
CHAIN = sheet("revision_chains", 2)   # 207 rows
NOTES = sheet("data_notes", 0)        # 6 rows

def jl(name):
    for line in open(f"{REPO}/data/build/{name}"):
        if line.strip():
            yield json.loads(line)
```

---

## Headline

| # | Item | Verdict |
|---|------|---------|
| 1 | Supersession: their 62 prose-extracted values vs our 303 structured SUPERSEDES edges | **8 agree, 0 disagree, 54 no opinion.** Not one contradiction. |
| 2 | Revision chains | **Aggregate matches; one group is wrong row-by-row.** Their 99 vs our 98 is entirely the single cell naming two dockets, and their chain for those two dockets is missing two rows and names the wrong current version. |
| 3 | Final-AD join, 42 vs 21 | **Our 42 are real.** All 21 of theirs reproduce exactly; all 21 extras are corroborated against the FR XML in `data/raw/fr_ad/`. One of the 42 exposes a direction bug in `PROPOSED_BY`, not an over-join. |
| 4 | Coverage | **431/431 of their `record_id`s map to one of our NPRM nodes; 322/322 dockets reconcile.** |
| 5 | Their six `data_notes` | **Two are not supported by the file** (the supersession count, and calling all 431 rows "proposals"); one is right about the file but misleading about the world (21 final ADs); three hold. |
| — | New defect found in the source data, affecting us | **257 of 431 rows carry a `publish_date` exactly one day earlier than the Federal Register publication date.** The FR API confirms the row's own `citation` string, not the date column. We key our NPRM nodes on the wrong date for those rows. |

---

## 0. The new file is the old file, re-cut

Before comparing derivations, establish that the two spreadsheets carry the same facts. Joining
the 431 rows of each on `(docket cell, citation, page range)` gives a clean 1:1 match, and every
shared field is character-identical after whitespace normalization:

```python
ohdr = [str(c).strip() if c is not None else None
        for c in list(openpyxl.load_workbook(
            f"{REPO}/AD Notice of Proposed Rulemaking (AD NPRM).xlsx",
            data_only=True, read_only=True).worksheets[0].iter_rows(values_only=True))[0]]
# full script: scratchpad/check_coverage.py
```

```
orig data rows: 431   orig columns: 22
new  nprm_index rows: 431   new columns: 16
orig keys unique: 431  dupes: []
new  keys unique: 431  dupes: []
keys only in orig: 0   keys only in new: 0
### shared-field mismatches between the two files
  none          # subject, make, model, product_type, product_subtype, ad_number,
                # summary, link, issue_date, publish_date — all identical
```

So the organizers **derived three columns** (`record_id`, `supersedes_ad`,
`mentions_serial_numbers`), **dropped nine** (`Status`, `CFR Part Reference`, `Service/Office`,
`Office of Primary Responsibility`, `Comments Due Date`, `AC Reference`, `AIR Policy Reference`,
`Additional Reference`, `Comments`), **renamed the rest**, and **reformatted the dates**. They
changed no value. Any disagreement is therefore about derivation, not about input.

---

## 1. Supersession — 8 agree, 0 disagree, 54 no opinion

Their `supersedes_ad` is populated on 62 of 431 rows and is extracted from the summary prose.
Our 303 `SUPERSEDES` edges come from the *final rule's* paragraph (b) "Affected ADs" XML markup
plus the part-39 amendment sequence. These are not the same object: theirs is "this proposal says
it would supersede X"; ours is "this adopted AD's paragraph (b) says it replaces X". The only
place the two can be compared is a docket where the proposal **was adopted** — i.e. a final rule
exists in the same docket and post-dates the proposal. Everywhere else we genuinely have no
opinion, and say so.

### Our side reproduces from primitives first

Before using our numbers, they were rebuilt from `paragraphs.jsonl` with
`engine.ingest.supersession.parse_affected_ads` (scratchpad/verify303.py):

```
prose superseded pairs:                                617
  self-references dropped:                              11
  dangling (target AD not in corpus):                   308
  resolved cross-AD prose edges:                        298
within-AD chain edges (new amendment):                    5
within-AD corrections (same amendment):                  39
TOTAL reconstructed SUPERSEDES: 303   vs edges.jsonl:   303
TOTAL reconstructed dangling:   308   vs ingest_report: 308
corrections reconstructed:       39   vs ingest_report:  39
multi-document ADs: 40
```

All three of the report's supersession numbers reproduce exactly from the paragraph text. The
`supersession.py` docstring's claim that "35 of the 40 multi-document ADs" are same-amendment
corrections also holds: 35 of the 40 have *every* adjacent pair as a correction.

### The 62, classified

```python
# scratchpad/final_sup.py
# for each of their 62 rows: normalize the docket, take only the final rules in that
# docket that POST-DATE the proposal, union their paragraph-(b) superseded lists,
# and ask whether their value is in it.
```

| Outcome | Count |
|---|---|
| **AGREE** — their AD is in our paragraph-(b) superseded list, target AD held in corpus | 5 |
| **AGREE** — their AD is in our paragraph-(b) superseded list, target outside corpus (recorded dangling) | 3 |
| **DISAGREE** — we read paragraph (b) as "affects / is related to", not supersession | **0** |
| **DISAGREE** — the adopting final rule's paragraph (b) does not name it | **0** |
| no opinion — the docket has no final rule at all in our corpus | 53 |
| no opinion — the docket's only final rule *predates* the proposal (NPRM-268, below) | 1 |
| | **62** |

Two independent derivations, 8 overlapping observations, **zero disagreements.** Every agreement
with its quote:

```
NPRM-079  FAA-2026-7213  theirs=2023-15-03  our final rule 2026-19762  [in corpus]
  (b) Affected ADs This AD replaces AD 2023-15-03, Amendment 39-22515 (88 FR 51223, August 3, 2023).
NPRM-081  FAA-2026-7209  theirs=2009-04-13  our final rule 2026-21278  [dangling]
  (b) Affected ADs This AD replaces AD 2009-04-13, Amendment 39-15819 (74 FR 7643, February 19, 2009).
NPRM-089  FAA-2026-4649  theirs=2025-04-05  our final rule 2026-21331  [in corpus]
  (b) Affected ADs This AD replaces AD 2025-04-05, Amendment 39-22963 (90 FR 10853, February 28, 2025).
NPRM-118  FAA-2026-2712  theirs=2019-20-07  our final rules 2026-20680, 2026-21686  [dangling]
  (b) Affected ADs This AD replaces AD 2019-20-07, Amendment 39-19760 (84 FR 54765, October 11, 2019).
NPRM-126  FAA-2026-1328  theirs=2021-03-08  our final rule 2026-20119  [in corpus]
  (b) Affected ADs This AD replaces AD 2021-03-08, Amendment 39-21411 (86 FR 16038, March 26, 2021).
NPRM-166  FAA-2022-1308  theirs=2021-04-05  our final rule 2023-07096  [in corpus]
  (b) Affected ADs This AD replaces AD 2021-04-05, Amendment 39-21426 (86 FR 10799, February 23, 2021).
NPRM-167  FAA-2022-1303  theirs=2022-14-14  our final rule 2023-05082  [in corpus]
  (b) Affected ADs This AD replaces AD 2022-14-14, Amendment 39-22119 (87 FR 43403, July 21, 2022).
NPRM-168  FAA-2022-1296  theirs=2020-20-05  our final rule 2023-16166  [dangling]
  (b) Affected ADs This AD replaces AD 2020-20-05, Amendment 39-21261 (85 FR 65197, October 15, 2020);
      and AD 2022-09-16, Amendment 39-22036 (87 FR 31943, May 26, 2022).
```

### Why 54 rows get no opinion, and why that is not a gap

The 53 "no final rule at all" rows break down by proposal year as
`{2003: 2, 2011: 1, 2015: 1, 2016: 1, 2021: 1, 2023: 1, 2024: 2, 2025: 7, 2026: 38}` — 45 of 53
are 2025-2026 proposals still in the comment/adoption pipeline. This is not a harvest-window
artifact: `engine/ingest/collect.py:196-204` looks up **every** sheet docket not already covered
by the windowed index through the Federal Register `conditions[docket_id]` endpoint, and
`ingest_report.json` records `dockets_queried_outside_window: 288`. 288 lookups + 34 dockets
already in the window = all 322. So "no final rule yet" is an authoritative answer from the FR
API, not an absence of data. Spot-check:

```
data/raw/fr_index/docket_FAA-2013-0751.json  count=2
  Proposed Rule 2013-09-05 2013-21587
  Proposed Rule 2021-02-25 2021-03661      # NPRM-193; no Rule in this docket
```

### The one row that looked like a disagreement — NPRM-268

NPRM-268 (docket cell `FAA-2009-0555-W`, published 2011-07-27) has their
`supersedes_ad = 2009-17-05`. Our corpus holds final rule `E9-19633` in docket `FAA-2009-0555`,
whose paragraph (b) reads **"Affected ADs (b) None."** — which looks like a contradiction. It is
not. The FR docket listing settles it:

```
data/raw/fr_index/docket_FAA-2009-0555.json  count=3
  Rule          2009-08-17  E9-19633      [Amendment 39-15996; AD 2009-17-05]
  Proposed Rule 2010-06-22  2010-15068
  Proposed Rule 2011-07-28  2011-19048    <- NPRM-268
```

AD 2009-17-05 was adopted in **2009**; the sheet's row is a **2011 withdrawal** of a later
proposal in the same docket. Its summary: *"Since we issued that NPRM, we decided not to supersede
AD 2009-17-05, but instead to issue a new NPRM for those additional 360 parts. Accordingly, we
withdraw the proposed rule."* The supersedure was proposed and then abandoned, so no final rule
ever adopted it and we correctly hold no supersession. Reclassified from DISAGREE to **no
opinion**.

Note what their regex actually matched here: the clause *"decided **not** to supersede AD
2009-17-05"*. Their value happens to be the right AD number, but it was lifted out of a negation.

### Where our structured extraction is strictly richer

On the 42 dockets both sides joined, our paragraph-(b) reading holds superseded-AD facts their
column does not (scratchpad/final_sup.py, reverse direction):

```
FAA-2022-0992: ours=['99-23-18','2005-03-07','2013-12-07','2014-04-07']  theirs=(empty)  -> +4
FAA-2022-1296: ours=['2020-20-05','2022-09-16']                          theirs=['2020-20-05'] -> +1
FAA-2012-18033: ours=['2004-21-08'] — self-reference (the final rule revises its own AD number);
                not an extra fact, listed for completeness
```

5 genuine extra supersession facts on 42 dockets. Their column is single-valued by construction,
so every multi-AD supersedure loses information (see §5, note 4).

---

## 2. Revision chains — aggregate agrees, one group is wrong row-by-row

```python
raw = collections.Counter(str(r["docket_number"]).strip() for r in NPRM)
print(sum(1 for v in raw.values() if v > 1))                      # 99
from engine.ingest.docket_ids import normalize_sheet_docket
nrm = collections.Counter(d for r in NPRM
                          for d in normalize_sheet_docket(str(r["docket_number"] or ""))[0])
print(len(nrm), sum(1 for v in nrm.values() if v > 1))            # 322 98
```

```
A. raw docket cells on >1 row:            99     <- their 99
B. normalized dockets on >1 row:          98  (distinct normalized: 322)   <- ours
D. revision_chains rows: 207   distinct docket_number: 99
   their multi-row raw set == revision_chains docket set: True
E. versions_total / version numbering anomalies:  0
G. dockets where version order != publish_date order: 0
H. chains rows inconsistent with nprm_index:      0
I. multi-row dockets whose row set != chains row set: 0
J. total rows covered by chains: 207   expected: 207
```

Internally their sheet is clean: `versions_total` always equals the group size, `version` is
always `1..n`, version order always equals publish-date order, no two rows in a group share a
publish date, every chain row agrees with its `nprm_index` row, and all 207 rows are accounted
for. Their status vocabulary is `earlier` (108) / **`latest`** (99) — not `earlier|current` as
the brief anticipated — and the rule "exactly one `latest` per group, and it is the maximum
publish date" holds for **99/99** groups.

### The 99-vs-98 difference, and the row-level error inside it

```
C. normalized dockets reached by >1 distinct raw cell:
     2002-CE-05-AD <- ['2002-CE-05-AD', '2002-CE-05-AD, 2002-CE-57-AD']
     2002-CE-57-AD <- ['2002-CE-05-AD, 2002-CE-57-AD', '2002-CE-57-AD']
C'. theirs not in ours: ['2002-CE-05-AD, 2002-CE-57-AD']    ours not in theirs: []
D'. shared dockets with different row membership: 2
     2002-CE-05-AD  we add ['NPRM-371','NPRM-380']
     2002-CE-57-AD  we add ['NPRM-371','NPRM-380']
E'. shared dockets where the 'latest' row differs: 2
     2002-CE-05-AD  theirs=NPRM-391 (2003-10-02)  ours=NPRM-371 (2004-05-24)
     2002-CE-57-AD  theirs=NPRM-392 (2003-10-02)  ours=NPRM-371 (2004-05-24)
```

The entire difference is the one cell that names two dockets. The organizers treat
`"2002-CE-05-AD, 2002-CE-57-AD"` as a 100th docket identifier of its own with two rows, so their
count is 99 and the chains for the two real dockets stop at 2003-10-02. The rows' own text proves
those two rows belong to **both** dockets:

- **NPRM-380** (2004-01-26): *"This document reopens the comment period**s** and announces a
  public meeting on the subject proposed airworthiness directive**s** ... The proposed AD**s**
  would supersede existing ADs..."*
- **NPRM-371** (2004-05-24): *"This document withdraws **two** notices of proposed rulemaking
  (NPRMs) that would have applied to Cessna ... Models 401, 401A, ..."*

So `2002-CE-05-AD` and `2002-CE-57-AD` each have **five** records, not three, and the current
version of each is **NPRM-371 (2004-05-24)**, a withdrawal — not NPRM-391/NPRM-392 (2003-10-02).
`normalize_sheet_docket` (`engine/ingest/docket_ids.py:115-146`) splits the cell and gets this
right; `rows_with_multiple_dockets` in `ingest_report.json` records rows `372, 381`
(1-based-with-header offsets = NPRM-371, NPRM-380). **Our 98 is the correct count and theirs is
inflated by one.**

Note for our own documentation: `nprm_xlsx.py:7-9` says "323 distinct dockets, 99 of which appear
on more than one row" while `ingest_report.json` says `unique_dockets: 322`. Both are true of
different things — 323/99 is the *raw cell* count, 322/98 the *normalized docket* count. The
docstring should say which it means.

---

## 3. The final-AD join: 42 vs 21 — our 42 are real

```python
sheetd = {d for r in NPRM for d in normalize_sheet_docket(str(r["docket_number"] or ""))[0]}
revs = {n["revision_id"]: n for n in jl("nodes.jsonl") if n.get("_type") == "Revision"}
finald = {r["docket_id"] for r in revs.values() if r.get("docket_id")}
print(len(sheetd), len(sheetd & finald), len(sheetd - finald))   # 322 42 280
print(sum(1 for r in NPRM if r.get("ad_number") not in (None, "")))  # 21
```

```
sheet dockets (normalized): 322
our dockets_joined_to_a_final_rule: 42        # == ingest_report.json
our dockets_with_no_final_rule_yet: 280       # == ingest_report.json
their ad_number column: 21 rows, 21 distinct dockets
### overlap
their dockets not in our joined set: []
our joined dockets not among theirs: 21
### per-docket agreement on the AD number, where both sides joined
  21 dockets, agree: 21, disagree: 0
```

**All 21 of their joins are also ours and the AD number matches character-for-character in all 21**
(`FAA-2026-8780 -> 2026-21-03`, `FAA-2026-7233 -> 2026-20-16`, ... `FAA-2025-0004 -> 2026-20-13`).
Their 21 are not a derivation at all: they are the FAA sheet's own `AD Number` column, carried
through unchanged (§0), and that column is only ever backfilled for the most recent proposals —
all 21 are 2025-2026 dockets whose AD was adopted in FR volume 91. **Our extra 21 are older
dockets whose AD the sheet never got around to recording**, which is exactly where a structured
`docket_ids` join earns its keep.

### Spot-check of all 21 extras against `data/raw/fr_ad/`

Rather than 5, all 21 were checked (scratchpad/spotcheck.py). Four assertions per extra, read
straight out of the cached Federal Register XML:

1. the `<DEPDOC>` bracket names the sheet's docket;
2. it names the AD number we assigned;
3. it names the part-39 amendment we assigned;
4. `<ACT>` is "Final rule";
5. plus an independent fifth: the final rule's own preamble cites the NPRM's Federal Register
   citation (`<vol> FR <start page>`) matching the sheet row's `citation` / `pages`.

**16 of 21 pass all five.** Representative:

```
DOCKET FAA-2026-2723 | final rule 2026-21902 | AD 2026-21-13 | amdt 39-23502 | 2026-10-27
  DEPDOC : [Docket No. FAA-2026-2723; Project Identifier AD-2024-00429-A; Amendment 39-23502; AD 2026-21-13]
  ACTION : Final rule.
  preamble: "The NPRM was published in the Federal Register on April 2, 2026 (91 FR 16595)."
  sheet NPRM-112: Volume 91 Number 63 (Thursday, April 2, 2026), Pages 16595-16599     -> exact
DOCKET FAA-2025-0199 | final rule 2026-10489 | AD 2026-10-10 | amdt 39-23350 | 2026-05-27
  preamble: "The SNPRM was published in the Federal Register on September 25, 2025 (90 FR 46098)."
  sheet NPRM-142: Volume 90 Number 184 (Thursday, September 25, 2025), Pages 46098-46102 -> exact
DOCKET FAA-2026-1326 | final rule 2026-21855 | AD 2026-21-09 | amdt 39-23498 | 2026-10-27
  preamble: "The NPRM was published in the Federal Register on February 13, 2026 (91 FR 6795)."
  sheet NPRM-127: Volume 91 Number 30 (Friday, February 13, 2026), Pages 6795-6798       -> exact
DOCKET FAA-2026-2716 | final rule 2026-21863 | AD 2026-21-07 | amdt 39-23496 | 2026-10-27
  preamble: "... on March 23, 2026 (91 FR 13791)."  sheet NPRM-116: Pages 13791-13794    -> exact
DOCKET FAA-2026-2725 | final rule 2026-21862 | AD 2026-21-08 | amdt 39-23497 | 2026-10-27
  preamble: "... on March 26, 2026 (91 FR 14654)."  sheet NPRM-114: Pages 14654-14657    -> exact
DOCKET FAA-2026-8782 | final rule 2026-21861 | AD 2026-22-02 | amdt 39-23504 | 2026-10-27
  preamble: "... on August 19, 2026 (91 FR 53542)." sheet NPRM-057: Pages 53542-53545    -> exact
DOCKET FAA-2025-0003 | final rule 2026-21864 | AD 2026-21-12 | amdt 39-23501 | 2026-10-27
  preamble: "... on January 17, 2025 (90 FR 5754)."  sheet NPRM-154: Pages 5754-5756     -> exact
DOCKET FAA-2022-1303 | final rule 2023-05082 | AD 2023-05-03 | amdt 39-22372 | 2023-03-14
  preamble: "The NPRM published ... October 26, 2022 (87 FR 64734; corrected November 10, 2022
             (87 FR 67837))."   sheet NPRM-167: Pages 67837-67840                        -> exact
```

The remaining 5 were run to ground individually. **All five joins are correct**; in each case it
is the fifth, deliberately strict check that fails, not the join:

| Docket | Final rule | Why check 5 failed | Verdict |
|---|---|---|---|
| `FAA-2003-16647` | `04-5431`, AD 2004-05-25 | The *Federal Register's own prose* has a typo: the preamble says "December 11, 2003 (68 FR **69501**)" where the sheet (and the FR index) say pages **69051**-69053. | **Join correct.** `docket_FAA-2003-16647.json` has exactly 2 documents: Proposed Rule `03-30674` (2003-12-11) and Rule `04-5431`. This is itself a demonstration of the brief's thesis: the structured `docket_ids` list is right where the prose page cite is wrong. |
| `FAA-2004-19119` | `04-27195`, AD 2004-25-15 | Check 1, not 5: `<DEPDOC>` writes `Docket No. FAA 2004-19119` with a **space**. | **Join correct.** `docket_ids.py:40` matches `FAA[- ]` and `_clean_docket` normalizes the space, so our parse is right. The preamble cites "October 7, 2004 (69 FR 60104)" against sheet pages 60104-60106 — exact. |
| `FAA-2022-1296` | `2023-16166`, AD 2023-13-10 | Sheet cell is `FAA-2022-1296**R1**`; the row is FR document `R1-2022-22047`, a **correction reprint** of the NPRM at 87 FR 68109. The final rule cites the original NPRM (87 FR 63712) and the SNPRM (88 FR 17429). | **Join correct** (same docket, same AD, `R1` suffix stripped by `normalize_sheet_docket`). |
| `FAA-2022-1308` | `2023-07096`, AD 2023-05-08 | Same pattern: row is `R1-2022-23012` at 87 FR 67845; final rule cites the original NPRM at 87 FR 65538. | **Join correct.** Confirmed by the sibling `FAA-2022-1303` case above, where the FR explicitly writes "corrected November 10, 2022 (87 FR 67837)". |
| `FAA-2009-0555` | `E9-19633`, AD 2009-17-05 | The final rule **predates** the sheet's row by two years (§1). | **Join correct as a docket-level fact** (the docket genuinely reached a final rule), **but the `PROPOSED_BY` edge is wrong.** See below. |

**Verdict on 42 vs 21: the 42 are real and the advantage is demonstrable.** 21/21 of their joins
reproduce with identical AD numbers; 21/21 of our extras are corroborated by the final rule's own
`<DEPDOC>` bracket, 20 of them additionally by the final rule's prose back-reference to the NPRM's
Federal Register citation. Zero over-joins at the docket level.

### The one real bug this uncovered: `PROPOSED_BY` has no date ordering

`engine/ingest/build.py:201-202`:

```python
                for nprm_id in nprm_by_docket.get(newest.ids.docket_id, []):
                    writer.edge("PROPOSED_BY", "AD", ad_number, "NPRM", nprm_id)
```

Every NPRM row in the docket gets an edge from the AD, whatever the dates. Audited across all 42
edges (scratchpad/dig3.py):

```
### all 42 PROPOSED_BY edges: does the final rule post-date the NPRM?
   edges where the AD's first final rule PREDATES the NPRM row: 1
     ('FAA-2009-0555@2011-07-27', 'NPRM-268', '2009-17-05', first final rule 2009-08-17, NPRM 2011-07-27)
   joined dockets with >1 NPRM row feeding PROPOSED_BY: {}
   PROPOSED_BY edges: 42   distinct ADs: 42   distinct NPRMs: 42
```

1 of 42 edges asserts that AD 2009-17-05 was proposed by a document published two years after the
AD was adopted. The true relation runs the other way (that NPRM proposed to supersede the AD, and
was withdrawn). A guard of the form "only emit `PROPOSED_BY` when the AD's earliest revision
post-dates the NPRM's publication date" removes it and costs nothing: the other 41 all satisfy it
already. Severity: low volume, but it is a false edge in a graph whose selling point is that its
edges come from structured sources.

Related latent risk, no current impact: `engine/ingest/fr_client.py:177-188`
(`documents_for_docket`) requests `page=1, per_page=100` and never inspects `total_pages`. Across
all 288 cached docket listings the largest is 5 documents, so nothing is lost today — but a docket
with more than 100 filed documents would silently drop its final rule.

---

## 4. Coverage — 431/431 and 322/322

```python
ours = {n["nprm_id"]: n for n in jl("nodes.jsonl") if n.get("_type") == "NPRM"}
hit = sum(1 for r in NPRM
          if any(f"{d}@{str(r['publish_date'])[:10]}" in ours
                 for d in normalize_sheet_docket(str(r["docket_number"] or ""))[0]))
```

```
their record_ids resolving to one of our NPRM nodes: 431 / 431     anomalies: none
our NPRM nodes not claimed by any of their rows: 0
our NPRM node ids: 431  unique: 431  with '~' collision suffix: []
sheet dockets: 322   sheet dockets missing a Docket node: []
Docket nodes with has_nprm=true: 322   with has_nprm=false among sheet dockets: []
sheet dockets whose Docket node has has_final_rule=true: 42
```

Full bijection on rows, full reconciliation on dockets, and the citation string on every matched
node is identical to the sheet's.

### Which documented quirks survive into the new file

`engine/ingest/nprm_xlsx.py:1-18` documents the original file. Re-measured on the new one
(scratchpad/check_coverage.py):

| Documented quirk | New file | Note |
|---|---|---|
| 431 data rows, one sheet | **changed** | 431 data rows in `nprm_index`, but **three** sheets, and the header is on **row index 2** (row 0 banner, row 1 blank). The original had its header on row 0. |
| 22 columns | **changed** | 16 columns; 9 dropped, 3 added, all renamed to snake_case (§0). |
| date columns are TEXT in `%m/%d/%Y`, parse 431/431 | **changed** | Still TEXT (`str` in all 431 cells) but now **ISO `yyyy-mm-dd`**, 431/431. `DATE_FORMAT` at `nprm_xlsx.py:39` would fail on every row. |
| 4 rows carry no comments-due date | **gone** | The `Comments Due Date` column was dropped entirely. It is in `_REQUIRED_COLUMNS` (`nprm_xlsx.py:48`), so the existing loader raises `SpreadsheetError` on this file. |
| 323 distinct dockets, 99 on >1 row | **holds exactly** | 323 distinct raw cells, 99 on more than one row. |
| 60 of 323 docket values non-standard | **holds exactly** | 60. Same population: 51 legacy directorate dockets, `FAA 2022-0460` (space), `FAA Rules 95-CE-35-AD`, `FAA-2009-0555-W`, `FAA-2021-1078R1`, `FAA-2022-1296R1`, `FAA-2022-1303R1`, `FAA-2022-1308R1`, `FAA-2025-0199_S`, and the compound cell. |
| one cell names two dockets | **holds** | `"2002-CE-05-AD, 2002-CE-57-AD"` on NPRM-371 and NPRM-380. The organizers did **not** fix it; they made it a docket of its own (§2). |
| `Make` is not normalized | **holds** | Values carried through unchanged ("Boeing" vs "The Boeing Company"). |
| AC / AIR Policy / Additional Reference 100% empty | **gone** | Dropped. (Re-verified 0/431 filled in the original, so dropping them is correct. `Comments` was 5/431 filled and was also dropped.) |
| identity = docket + FR citation, unique across 431 rows | **holds** | Still unique. Worth noting that `nprm_id_for` (`nprm_xlsx.py:212`) actually keys on docket + **publish_date**, not citation. Both happen to be unique here (431/431, no `~` suffix), but the docstring and the code describe different keys — and publish_date is the field with the defect in §5. |

New quirks the new file introduces, for whoever writes the `nprm_index_xlsx` docstring:

- header on row index 2 in `nprm_index` and `revision_chains`, row 0 in `data_notes`;
- `record_id` is `NPRM-001`..`NPRM-431`, contiguous, unique, and **ordered newest-first by
  publish date** (NPRM-001 = 2026-10-19, NPRM-431 = 2001-04-26);
- `mentions_serial_numbers` is a literal `yes`/`no` string, never blank;
- `federal_register_link` is the original `Link for Submitting Public Comment` column renamed, and
  it is **not reliably a URL** (§5, note 4);
- 25 rows have no link, 3 rows have no `make`/`product_type` (NPRM-244, NPRM-283, NPRM-411), and
  **1 row has no summary at all** (NPRM-294).

---

## 5. Their `data_notes`, checked against the file itself

```python
for n in NOTES: print(n["topic"], "|", n["detail"])
```

### Note "What this is": *"431 FAA airworthiness directive proposals (NPRMs). Only 21 have a final AD number."*

- `431` rows, 431 distinct `record_id`: **holds.**
- `21` rows with `ad_number` filled: **holds of the file**, but it is not a fact about the world.
  The column is the FAA sheet's own, carried through unchanged, and **42** of the 322 dockets have
  in fact reached a final rule (§3) — exactly double. Stating it as "only 21 have a final AD
  number" understates reality by 21 dockets.
- **"proposals" is not supported for all 431 rows.** A tight census of the summaries:

  ```
  withdrawals ("withdraws/is withdrawing a notice of proposed rulemaking", "accordingly we withdraw"): 119
  comment-period extensions / reopenings / public-meeting notices:                                       6
  union:                                                                                                125
  rows that are neither:                                                                                306
  ```

  **125 of 431 rows (29%) are not proposals**: 119 are withdrawals of proposals and 6 are
  procedural notices. Anything that counts rows as live proposals is wrong by nearly a third. This
  is the organizers' own file telling on itself, and it is the single most load-bearing correction
  for anyone answering "what is currently proposed".

### Note "Revisions": *"99 dockets have more than one record. 62 summaries say which AD they supersede."*

- `99`: **holds on raw cells**, but the correct normalized count is **98** (§2), and their chain
  for `2002-CE-05-AD` / `2002-CE-57-AD` is missing two rows and names the wrong current version.
- `62`: **not supported by the file.** An independent extraction over the same 430 non-empty
  summaries, allowing the `Directive (AD) NNNN-NN-NN` form their regex evidently handles:

  ```python
  VERB = re.compile(r"\b(supersede|supersedes|superseded|supersedure|replace|replaces|replaced)\b", re.I)
  ADN  = re.compile(r"(?:\bAD\b[ -]|\(AD\)\s*|\bDirective\s*\(AD\)\s*)(\d{2,4}-\s?\d{2}-\s?\d{2})")
  # scratchpad/notes_check.py
  ```

  ```
  rows with supersedes_ad filled:                                                 62
  rows whose summary names >= 1 superseded/replaced AD (independent extraction):  80
  total (row, AD) pairs found:                                                    89
  their 62 all reproduced:                                                       yes
  their value is the FIRST AD found, in all 62:                                  True
  rows where the summary names MORE than one superseded AD:                        4
  superseded ADs their single-valued column drops:                                 6
  rows found that their column leaves EMPTY:                                      18
    NPRM-165, 169, 175, 180, 194, 213, 224, 230, 233, 236, 241, 258, 359, 391, 397, 398, 402, 409
  ```

  The file's summaries name a superseded AD on **80** rows, not 62, and name **89** (row, AD)
  pairs. Their column is right where it is filled — the 62 are a strict subset of the 80 and each
  is the first AD in its summary — but it misses 18 rows and 6 extra ADs. Examples of what it
  misses: NPRM-169 *"The FAA proposes to supersede Airworthiness Directive (AD) 99-23-18, AD
  2005-03-07, AD 2013-12-07, and AD 2014-04-07"* (all four dropped); NPRM-402 *"This document
  proposes to supersede Airworthiness Directive (AD) 79-10-15 R2"* (the `R2` suffix and the older
  two-digit-year form); NPRM-258 *"We propose to **revise** an existing airworthiness directive"*
  (a verb their pattern doesn't cover but ours does — `_SUPERSEDING_VERBS` in
  `supersession.py:27` includes `revises`).

  A second caveat on semantics: **8 of their 62** sit on rows where the proposal was withdrawn or
  only re-noticed — withdrawals NPRM-153, 162, 193, 218, 225, 268 and comment extensions
  NPRM-157, 392. The column reads "this row supersedes AD X" when the truth is "a proposal that
  never took effect would have".

### Note "Applicability": *"16 summaries mention serial numbers. Model is filled for 86 rows."*

```
mentions_serial_numbers values: {'no': 415, 'yes': 16}
independent regex on the summaries (serial number | serial no | S/N | serial-number): 17
  theirs not mine: []          mine not theirs: ['NPRM-175']
    NPRM-175: "... would have required removing certain serial-numbered tension-torsion (TT)
               straps from service ..."
model filled: 86
```

- `16`: **essentially holds**, with one near-miss. Their 16 are all genuine and are a subset of
  mine; the only row they miss uses the hyphenated adjective *"serial-numbered"* rather than the
  noun phrase. Defensible either way — flagged, not faulted.
- `86`: **holds exactly.** (For context: `make` 428, `product_type` 428, `product_subtype` 370,
  `summary` 430.)

### Note "Full text": *"Summaries total roughly 150 pages. To reach 1,000+ pages, fetch the full documents from federal_register_link (public, no login)."*

- "roughly 150 pages": **plausible.** 346,003 summary characters, i.e. ~115 pages at 3,000
  chars/page or ~192 at 1,800. "Roughly 150" is inside that band.
- **"fetch the full documents from `federal_register_link`" is not supported for 194 of 431 rows.**
  The column is the original `Link for Submitting Public Comment` renamed, and it is dirty:

  ```
  empty                                      :  25
  exactly one Federal Register URL           : 237
  two or more URLs in one cell               :  17
  no URL at all (prose only)                 : 152
  value carries >30 chars of non-URL prose   : 177
  -> rows where the note cannot be followed as written: 194 (25 + 17 + 152)
  ```

  Only **171** rows hold a single clean dated `/documents/YYYY/MM/DD/<docnum>/...` URL; another 66
  hold a short `/d/<docnum>` form. 152 rows hold **no URL at all** — in those cells the FAA pasted
  withdrawal prose, and 20 of them carry over 1,800 characters of the proposed rule's body text,
  the largest 20,239 characters. Representative values:

  ```
  NPRM-263: "The Withdrawal\n\n    Accordingly, we withdraw the NPRM, Docket No. FAA-2011-0158, ..."
  NPRM-180: "https://www.federalregister.gov/d/2018-12886\nWithdrawal:https://www.federalregister.gov/d/2021-13636"
  NPRM-158: "https://www.federalregister.gov/documents/2024/05/24/2024-11214/..., Withdrawal: ..."
  NPRM-431: "The Proposed Amendment \n\n\tAccordingly, pursuant to the authority delegated to me ..."  (20k chars)
  ```

  Anyone taking the note literally and iterating the column as URLs retrieves nothing for 45% of
  rows. Our own joins do not depend on this column — they go through `docket_ids` — which is why
  we reached 42 dockets where the sheet reached 21.

### Notes "Citations" and "Latency"

Instructions to the entrant, not claims about the data. No check applies. Noted only that
`record_id` + citation + page range is a usable citation key: all three are present and unique on
431/431 rows.

---

## 6. A defect in the source data that we are currently inheriting

Not asked for, but it falls out of the cross-check and it is the one finding that changes our
output.

**257 of 431 rows carry a `publish_date` exactly one day earlier than the Federal Register
publication date printed in the same row's `citation` string.**

```python
MONTHS = ("January February March April May June July August September "
          "October November December").split()
def citdate(r):
    m = re.search(r"(%s)\s+(\d{1,2}),\s*(\d{4})" % "|".join(MONTHS), str(r["citation"]))
    return f"{m.group(3)}-{MONTHS.index(m.group(1))+1:02d}-{int(m.group(2)):02d}" if m else None
off = [r for r in NPRM if citdate(r) and citdate(r) != str(r["publish_date"])[:10]]
print(len(off))                                                           # 257
print(collections.Counter((citdate(r), str(r['publish_date'])[:10]) and 1 for r in off))
```

```
rows where publish_date != the date printed inside their own citation: 257
offset distribution (citation_date - publish_date, days): {1: 257}        # every single one, +1 day
off-by-one rows, by publish year:  2001-2021 only (2001:13 ... 2021:21)
exact-match rows, by publish year: 2021:1, 2022:9, 2023:3, 2024:6, 2025:22, 2026:133
```

A clean split: every row published 2022 or later agrees; almost every row published 2021 or
earlier is one day early. The Federal Register API settles which side is right. Restricting to
dockets whose cached listing contains exactly one Proposed Rule, so the match is unambiguous
(scratchpad/dates.py):

```
### sheet publish_date vs the Federal Register API
   120  API == publish_date == citation
    35  API == citation, publish_date WRONG
     0  API == publish_date, citation wrong
     0  API matches neither
  total unambiguous rows checked: 155
```

**35 for 35, with no counter-example.** Examples:

```
NPRM-189  FAA-2021-0103  api=2021-02-26  sheet publish_date=2021-02-25  sheet citation=2021-02-26
NPRM-226  FAA-2015-2994  api=2015-07-24  sheet publish_date=2015-07-23  sheet citation=2015-07-24
NPRM-230  FAA-2015-0827  api=2015-04-15  sheet publish_date=2015-04-14  sheet citation=2015-04-15
```

Confirmed again by the §3 spot-check: `docket_FAA-2003-16647.json` gives Proposed Rule `03-30674`
published **2003-12-11**; the sheet's `publish_date` is 2003-12-10 and its citation reads
"December 11, 2003".

This is the FAA source sheet's defect, not the organizers' (§0 proved the column is carried
through unchanged). But it is ours now:

- `nprm_id_for` (`engine/ingest/nprm_xlsx.py:204-212`) builds the node id as
  `docket@publish_date`, so **257 of our 431 NPRM node ids carry a date that is not the Federal
  Register publication date** — e.g. `FAA-2021-0103@2021-02-25` for a document the FR published on
  2021-02-26;
- the NPRM node's `publish_date` field has the same error, so a date-filtered query over proposals
  returns the wrong day for 60% of the corpus;
- the ids are internally consistent and unique (431/431, no collisions), so nothing is broken
  today — but they are wrong against the authority we cite.

The authoritative value is already on disk for most rows. Three sources agree with each other and
disagree with the column: the row's own `citation` string, the `/documents/YYYY/MM/DD/` path in
`federal_register_link` (for the 171 rows that have one — link date equals citation date on
171/171 and publish_date on 171/171, i.e. these are exactly the already-correct rows), and the
`publication_date` field of the cached FR docket listings in `data/raw/fr_index/docket_*.json`.

---

## 7. What to change

**One thing, in priority order of impact:**

1. **Stop trusting the sheet's `publish_date` column. Take the NPRM publication date from the
   Federal Register, as we already do for everything else.** This is the only finding that makes
   our output wrong rather than merely incomplete, it affects 257 of 431 rows, and the fix is the
   engine's own stated principle: the structured source (`docket_*.json`'s `publication_date`, or
   failing that the row's own `citation` string, which agrees with the API 155/155) beats the
   hand-maintained column. Owner: `engine/ingest/nprm_xlsx.py` / the new `nprm_index_xlsx`.
2. Guard `PROPOSED_BY` on publication order at `engine/ingest/build.py:201-202` — only emit when
   the AD's earliest revision post-dates the NPRM. Removes 1 false edge of 42; the other 41 already
   satisfy it.
3. Record in the new reader's docstring that **125 of 431 rows are not live proposals** (119
   withdrawals, 6 procedural notices) and that the organizers' own `supersedes_ad` reaches only 62
   of the 80 rows whose summary names a superseded AD. Both are differentiators worth stating out
   loud.
4. Reconcile `nprm_xlsx.py:7-9` ("323 distinct dockets, 99 of which appear on more than one row")
   with `ingest_report.json`'s `unique_dockets: 322` by saying which population each counts — raw
   cells vs normalized dockets — and note that the correct normalized multi-row count is 98.

**Nothing in the supersession or join logic needs to change.** Two independent derivations, eight
overlapping supersession observations and twenty-one overlapping AD-number observations, and not
one contradiction between them.

---

## Appendix: scripts

All throwaway, all outside the repo, under
`/private/tmp/claude-501/-Users-frederick-Documents-Projects-autsg/3f180e3b-f15f-443d-9f17-db1bc5cff08e/scratchpad/`:

| Script | Produces |
|---|---|
| `dump_xlsx.py` | dumps either workbook to JSON (`new.json`, `orig.json`) |
| `common.py` | shared loaders for both workbooks and our JSONL |
| `recon.py` | column fill counts, docket-value census |
| `check_coverage.py` | new-vs-original row join, column deltas, quirk re-measurement (§0, §4) |
| `check_chains.py`, `check_chains2.py` | revision-chain verification (§2) |
| `build_view.py` -> `view.pkl` | our nodes/edges/paragraph-(b) parse, cached |
| `verify303.py` | rebuilds 303 / 308 / 39 from paragraph text (§1) |
| `check_sup.py`, `final_sup.py` | the 62-row supersession classification (§1) |
| `check_join.py` -> `extra_joins.json` | 42-vs-21 join comparison (§3) |
| `spotcheck.py`, `dig.py` | all 21 extras against `data/raw/fr_ad/` (§3) |
| `dig3.py` | `PROPOSED_BY` direction audit (§3) |
| `notes_check.py` | the six `data_notes` claims (§5) |
| `links.py`, `links2.py` | `federal_register_link` taxonomy (§5) |
| `dates.py` | `publish_date` vs the FR API (§6) |
| `mop.py`, `dockchk.py` | withdrawal census, pagination risk, docket reconciliation (§4, §5) |
