# Citations: provable and findable

> Code: `engine/api/citations.py`, `engine/api/answer.py` (`build_envelope`),
> `engine/ingest/emit.py` (`_check_revision_pages`), `web/lib/citation.ts`.
> Tests: `tests/test_citations.py`. Contract: `contracts/contract.json`
> → `citation.id_format`, `citation.rules`, `citation.human_reference_fields`.

The challenge rubric asks for two things this document answers:

> **Citations** — Cite `record_id` plus the Federal Register citation and page
> range, and the section of the full document when used.
>
> **Latency** — The 3-second target applies to whatever corpus you index.
> State its size.

## A citation has two halves

**The anchor is provable.** The id is
`{document_id}#{label}@{char_start}-{char_end}`, where `document_id` is a
`revision_id` for an adopted AD and an `nprm_id` for a proposal. The offsets
are computed by `str.find` in `engine/api/answer.py`; the answer writer is
never asked for a number, only to quote. `engine/verify/verifier.py` then
re-checks that the text at the span is that quote, character for character. A
quote that is not present yields no citation, and a sentence with no surviving
citation is dropped rather than shown.

Nothing in this document changes that. The anchor is untouched.

**The reference is findable.** `2026-21864#(g)@4120-4193` cannot be taken to a
paper copy of the Federal Register. So every citation carries, beside the
anchor:

| Field | Adopted AD | Proposal |
|---|---|---|
| `handle` | `ad_number`, e.g. `2026-21-12` | `record_id`, e.g. `NPRM-001` |
| `fr_citation` | `91 FR 67442` | `91 FR 66019`, from the proposal's own `PRORULE` record |
| `page_range` | `67442-67445` | `66019-66022`, from that record's `start_page`/`end_page` |
| `paragraph_label` + `paragraph_role` | `¶(g) REQUIRED_ACTIONS` | same |
| `document_stage` | `EFFECTIVE` / `ADOPTED_NOT_YET_EFFECTIVE` / `SUPERSEDED` | always `PROPOSED` |
| `source_citation_text` | — | the source's own citation, verbatim, when no short form exists |
| `federal_register_link` | the document's XML URL | the organizers' `federal_register_link` |
| `not_recorded` | every field above the source does not hold, named | same |

One field is deliberately withheld: 246 of the 431 `NPRM` nodes carry the
`ad_number` the proposal was eventually adopted as (`NPRM-061` became
`2026-21-03`, two months later). The node keeps it — it is a real graph fact —
but a proposal's citation reference does not show it. The adopted AD is a
different document, with wording the proposal does not have and a compliance
date it cannot have, so printing its number beside proposed text is the
misreading the fourth rule forbids.

Rendered:

> **2026-21-12 · 91 FR 67442 · pp. 67442–67445 · ¶(g) REQUIRED_ACTIONS · in force**

> **NPRM-001 · 91 FR 66019 · pp. 66019–66022 · ¶(c) APPLICABILITY · proposal**
> *a proposal open for comment — not a requirement, and nothing to comply with*

## Where it appears

| Surface | Carries |
|---|---|
| `retrieval` SSE payload | `human_reference` inside each paragraph, so a retrieved proposal is recognisable before any sentence rests on it |
| `done` envelope → `citations[].references[]` | one reference per `citation_id`, same order |
| `done` envelope → `limitations` | a line naming cited proposals, and a line naming citations with no page range |
| `GET /health` → `corpus` | the indexed corpus size, including its page count |
| `CitationPill` | the number **and the stage word**, on the pill, not in a tooltip |
| `CitationReferences` | the numbered reference list under the answer, as body text |
| `SourcePanel` | the reference above the quoted span, and a `document`/`FR citation`/`pages`/`document stage` row block |

## Three rules, and what enforces them

### 1. Every rendered citation shows its `document_stage`

`HumanReference.__post_init__` raises `CitationStageMissing` unless
`document_stage` is a member of the contract's `document_stage` enum. There is
no constructor that skips it and no default. `build_envelope` routes every
citation through `reference_dicts`, which refuses anything that is not a
`HumanReference` — so a resolver that returned a bare dict cannot slip a
stage-less citation into the envelope.

`build_envelope`'s `references` argument defaults to a resolver over an **empty
book**, not to nothing. A corpus-less engine still reports `UNKNOWN` — a
contract value meaning "could not be determined from metadata" — and names
every field it could not find. Silence is not an option the code offers.

On the UI side `STAGE_WORDING` in `web/lib/citation.ts` and `STAGE_STYLE` in
`CitationPill.tsx` are both keyed by `DocumentStage`, so adding a stage to
`contracts/contract.json` fails `tsc` until it has been given wording and a
colour.

A proposal's stage word is **proposal**, spelled out, never abbreviated: the one
misreading this product must not permit is a proposal read as a requirement.

### 2. A page number cannot be fabricated

The Federal Register index returns `citation`, `start_page` and `end_page`
together, and the citation always names the start page. Checked against all
4,053 index responses cached under `data/raw/fr_index`: **zero exceptions**, and
`tests/test_citations.py::test_the_cached_index_really_does_corroborate_every_page`
re-checks it on every run. That makes the pair self-checking, and
`emit._check_revision_pages` is the check:

- a page number may not exist without an `fr_citation` to corroborate it;
- the citation's page must equal `start_page`;
- `end_page` may not precede `start_page`, and neither may be non-positive.

It raises rather than dropping the field, because the values are copied
straight off the index response — tripping it means the index changed shape or
something edited them, and both deserve a stopped build.

`page_range` is **derived**, never stored twice: `RevisionRecord.page_range` is
a property over the two integers, so a stored copy cannot drift from them. It
is also formatted in exactly one place — `engine/graph/pages.py`, which the
ingest, the retrieval corpus and this module all call — because a page range
that differs between layers is a page range a reader cannot check.

Nothing is parsed out of prose. The NPRM spreadsheet's citation column holds
233 distinct shapes (`(Federal Register Volume 86, Number 187 (Thursday,
September 30, 2021))`, …) and its page column four more. None of them is read.
A proposal's `fr_citation` and `page_range` come from its own Federal Register
`PRORULE` record instead, reached by `fr_document_number`, so the short form is
the register's own string and the pages are the register's own integers. Where
a source holds only prose, that prose is shown verbatim as
`source_citation_text` and is never promoted to an `fr_citation`; all 431
proposals resolve today, so nothing currently falls back to it.

### 3. An absent field says so

Every surface renders `not recorded` for a field the source does not hold, and
`not_recorded` names which. The envelope adds a limitation:

> *1 cited document(s) have no Federal Register citation or page range recorded
> (2025-07990), so those citations can be checked against the indexed text but
> not against a printed page.*

and, for a cited proposal:

> *1 cited document(s) are proposals, not rules (NPRM-001). A proposal
> establishes no obligation and supplies no compliance deadline.*

The second fires on the stage of the **cited documents**, independently of the
answer's own `document_stage`: a sentence can cite a proposal while the AD it
is about is in force.

## The corpus, in Federal Register pages

```bash
python3 -m engine.api.citations              # from the built nodes
python3 -m engine.api.citations --from-index # from the cached index responses
```

**Field used:** `start_page` and `end_page` as the Federal Register index
returned them, per document — not the citation string, not the page count of
the XML, not an estimate from character length. A proposal's pages come from
the same place, reached by joining its `fr_document_number` to its `PRORULE`
record in that index; the challenge index's own page column is not used,
because its wrapper varies four ways (`66019-66022`, `Pages 45118-45119`,
`Page 6708`, `14293)`) and 200 of its 431 cells would be dropped.

**Volume:** from the citation when it is in `<volume> FR <page>` form, otherwise
from the publication year, since Federal Register volume 1 is 1936 and so
`volume == year - 1935`. Checked on all 4,053 cached index documents: no
exception. When both are available and disagree, neither is trusted and the
document is reported as unattributable rather than counted in the wrong volume.

**The arithmetic**, measured 2026-10-31:

| | Documents | Σ (end − start + 1) | Distinct (volume, page) | Shared |
|---|---|---|---|---|
| Adopted ADs (`Revision`) | 2,161, all with a page range | 8,370 | **7,081** | 1,289 |
| Proposals (`NPRM`) | 431, all with a page range | 1,338 | **1,282** | 56 |
| **Indexed corpus** | 2,592 | 9,708 | **8,363** | 1,345 |

The two sets turn out to be disjoint — 7,081 + 1,282 = 8,363 exactly — so no
page carries both an adopted AD and a proposal. That is expected rather than
designed: a proposal and the rule that adopts it are published months apart, in
different issues. The adopted pages fall across 13 Federal Register volumes and
the proposed pages across 26, and the page sets are compared as
`(volume, page)` pairs, so the same page number in two volumes is two pages.

Two counts are reported because they answer different questions.

`Σ (end − start + 1)` is the naive sum of each document's own span. It
**overstates** the corpus, because two documents published in the same Federal
Register issue can share a page: one ends on 67445 and the next begins on it.
1,345 pages are double-counted that way.

`Distinct (volume, page)` counts each physical page once. It is the only count
that is not an overstatement, so **8,363 pages** is the number quoted — against
the organizers' 1,000-page bar, 8.4×.

Where the figure differs from the spreadsheet's own, the Register wins and the
difference is accounted for: the sheet's proposal spans sum to 1,341 against the
Register's 1,338, and the whole 3-page gap is two withdrawal notices,
`NPRM-186` and `NPRM-287`, whose page cells name the pages of the *original*
proposal being withdrawn (74210-74213 and 29148-29149) rather than the
withdrawal itself (`86 FR 14289-14290` and `81 FR 13303`). In both rows the
sheet's own citation column agrees with the Register, which is how that was
confirmed rather than assumed. `docs/ingest.md` has the harvest side.

Every one of the 2,592 documents contributes a page range, so nothing is
silently missing from the figure. The two commands above compute it from
independent sources — the built nodes, and the cached index responses joined on
`fr_document_number` — and `tests/test_citations.py` fails if they disagree,
which is what caught the earlier 7,847 when 200 proposals' pages were still
being read off the spreadsheet's prose page column.

## Latency and corpus size together

The contract's `total_p95` is 3,000 ms for a whole query. That budget covers two
network calls to Anthropic — the Haiku query plan and the Sonnet answer writer —
whose latency is not this engine's to promise, so it is **not claimed** as a
measured figure anywhere.

What is measured is everything the engine is responsible for, which contains no
model call at all: entity pass p95 **0.09–0.11 ms** and retrieval p95
**62.2–66.5 ms** over nine runs, against the corpus above. See [`retrieval.md`](retrieval.md#latency). `GET
/health` serves the same corpus size at runtime, so the size a reader is quoted
is the size the engine actually loaded.
