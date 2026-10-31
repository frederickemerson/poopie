# Positioning: what this engine does that the incumbents do not

The competitive table identifies four classes of existing solution and a remaining
limitation for each. This document maps every one of those limitations to a specific,
checkable thing our engine does, and names the evidence we will show for it.

The through-line: **the differentiator is not that it answers. It is that it knows what
it cannot determine, and proves what it can.**

---

## Gap 1 — Regulatory portals (FAA DRS, EASA AD resources)

> *What they provide:* authoritative documents, searches, regulatory updates.
> *Remaining limitation:* **users still need to establish applicability and connect
> requirements to equipment records.**

This is the central gap and our central claim. A portal hands you the right document;
it does not tell you whether the document applies to *your* tail number.

**What we do:** applicability is a deterministic computation, not a reading exercise.
At ingest, each AD's paragraph (c) is turned into `Rule` records — `field`, `operator`,
`value`, and a `source_quote` that the contract gate verifies is a verbatim substring of
the paragraph it came from. At query time a rules engine evaluates those rules against a
real aircraft record and returns `APPLIES` / `DOES_NOT_APPLY` / `CANNOT_DETERMINE`,
together with the ids of the rules that fired.

**Evidence on stage:** the proof tree. Each condition shows the aircraft's value beside
the rule's value — `MSN 1342 in 1000-1500 ✓` — and clicking any node opens the exact
cited sentence. The BlastRadius grid runs the same engine across the whole fleet at once.

**Why it is trustworthy:** no language model produces a decision value. The LLM extracts
candidate rules at ingest (with a quote we verify) and writes prose at the end. Every
yes/no/cannot-determine between those two points is plain code, so it is reproducible and
can be unit tested. The contract encodes this as an invariant:
*"The rules engine, not the LLM, produces every value in `enums.decision`."*

---

## Gap 2 — Manufacturer documentation platforms (e.g. Airbus airnavX)

> *Remaining limitation:* **concerns one manufacturer's documentation ecosystem; does not
> establish a universal answer engine across manufacturers and regulators.**

**Across manufacturers:** our corpus is the Federal Register's AD series, which is
manufacturer-agnostic by construction. The 2021-2026 window alone spans Boeing, Airbus,
Embraer, Bombardier, Bell, Leonardo, Gulfstream, Cessna, Dassault, Rolls-Royce, GE,
Pratt & Whitney, Safran and more. No OEM relationship, subscription or ecosystem is
involved — one ingest path covers all of them.

**Across regulators:** FAA ADs that adopt Mandatory Continuing Airworthiness Information
name the foreign directive explicitly. Verified in our committed fixture:

> *(c) Applicability — This AD applies to Airbus SAS Model A330-941 airplanes, certificated
> in any category, **as identified in European Union Aviation Safety Agency (EASA) AD
> 2025-0208**, dated September 24, 2025.*

We extract those into `ForeignAD` nodes with `ADOPTS_MCAI` edges (authorities: EASA, TCCA,
ANAC, CAAC). That yields a genuine cross-regulator reference graph built from authoritative
in-document data — no scraping of EASA's site, which was in maintenance mode when we
checked and is not a dependency we want.

**And it is where we refuse.** Those `ForeignAD` nodes carry `held=false`, because we do
not have the EASA text. An engine that answered "applies" here would be guessing at a
condition it cannot see. Ours returns `EXTERNAL_SOURCE_REQUIRED` and names the document
you need. See `docs/refusals.md`.

---

## Gap 3 — Technical publication platforms (e.g. Veryon Publications)

> *Remaining limitation:* **access depends on publication subscriptions; public feature
> descriptions do not prove deterministic applicability checking.**

**On access:** every source we use is public and unauthenticated — the Federal Register
API (no key), the NPRM dataset, and the OpenSky public aircraft database. The whole index
rebuilds from scratch on any machine with no credentials and no vendor relationship. That
is a reproducibility property, not just a cost one: anyone can re-run our numbers.

**On proof:** we do not ask to be believed about deterministic applicability — the proof
tree *is* the determinism, rendered. Same inputs, same rules, same decision, every time,
with the rule ids and source quotes attached. The eval harness measures applicability
precision and recall against hand labels and publishes both.

---

## Gap 4 — AI reference tools (e.g. AeroRef)

> *Remaining limitation:* **these are vendor claims. Public claims about citations or "no
> hallucinations" do not independently demonstrate correctness.**

This is the sharpest critique in the table and it applies to us too unless we do something
about it. A claim of "cited answers" is worth nothing without a measured error rate. So:

**We make citation structural, not promised.** A sentence without a `citation_id` that
resolves to a paragraph *retrieved for that query* cannot reach the screen — the verifier
drops it, and if too much is dropped the answer converts to a refusal. The contract states
it as an invariant and the gate enforces the shape. This is an architectural property, not
a prompt instruction, which is the difference between "we asked the model nicely" and
"the model cannot do otherwise".

**We publish numbers against a baseline.** The eval harness runs our engine and a plain
"Claude + top-8 vector chunks" baseline over the same labelled set, and reports:

| Metric | Why it answers the critique |
|---|---|
| **Wrong-answer rate** | Confidently wrong answers — the number that actually matters in a safety domain. |
| Citation precision | Share of cited paragraphs that genuinely support the sentence. |
| Refusal recall | Share of should-refuse questions refused, *with the right code*. |
| Applicability precision / recall | Against hand labels over the real fleet. |
| Latency p50 / p95 | Per stage, shown live in the UI. |

**We show our failures.** A failure gallery of real cases we get wrong or cannot resolve,
each with a one-line reason and what would fix it. A system that publishes its failure
modes is making a different kind of claim from one that advertises having none.

---

## The one-sentence version

> Regulatory portals give you the document but not the decision; OEM platforms cover one
> manufacturer; publication platforms are subscription-gated and unproven on applicability;
> AI reference tools claim citation quality without measuring it. We compute applicability
> deterministically against real aircraft records, across every manufacturer and three
> regulators, from entirely public data — and we publish the error rate, including the
> cases where the honest answer is "I cannot determine that, here is the document you need."

## Honest limits we state on stage

- The AD corpus is the Federal Register 2021-2026 window (~1,900 final ADs), not the
  full register, plus 431 NPRMs from the supplied dataset.
- The fleet is real aircraft from a public database, but it carries no equipment,
  modification or part-number data — which is exactly why amber `CANNOT_DETERMINE`
  cells appear, and we show the null-rate table that explains them.
- Rule extraction quality is measured on a hand-checked sample, not on all ADs.
- Service bulletins and foreign ADs referenced by our corpus are not held, so any
  requirement that lives inside one is reported as external, never inferred.
