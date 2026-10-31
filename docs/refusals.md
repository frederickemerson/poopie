# The refusal catalogue

Specification and demo script for every case where the engine declines to answer.

In a safety domain a confident wrong answer is worse than no answer, so refusals are a
feature of this product, not a failure of it. Each one must be **code-triggered**,
**specific** (names the exact missing thing), and **actionable** (says what would resolve
it). A refusal that just says "I don't know" is a bug.

Codes are pinned in `contracts/contract.json` under `enums.refusal_code` and
`refusal_semantics`. Do not invent new ones — `tests/test_contract.py` fails the build if
any source file does.

---

## Decision rule: which code fires

The three "I can't tell you" codes are distinguished by **who can resolve it**. Getting
this wrong makes the UI useless, so the distinction is the important part:

| If the blocker is... | Code | Who resolves it |
|---|---|---|
| A value the *engineer knows* but did not type, and the fleet record lacks | `NEED_CONFIG` | **The user**, by supplying it |
| A document we *do not hold* (foreign AD, service bulletin) | `EXTERNAL_SOURCE_REQUIRED` | **Loading that document** |
| Applicability text our extractor *could not parse* | `CANNOT_DETERMINE` | **A human reading the clause** |
| Nothing retrieved above threshold | `NO_EVIDENCE` | Nobody — outside the corpus |
| Question isn't about AD content | `OUT_OF_SCOPE` | Nobody |
| Asked about an old revision | `SUPERSEDED` | *Answer is still given*, with a banner |

`SUPERSEDED` is the only code with `blocks_answer: false`. It warns, it does not withhold.

---

## 1. `EXTERNAL_SOURCE_REQUIRED` — applicability delegated to a document we don't have

**This is the headline demo.** Verified verbatim in `data/fixtures/ad_airbus_a330_easa_delegated.xml`:

> *(c) Applicability — This AD applies to Airbus SAS Model A330-941 airplanes, certificated
> in any category, **as identified in European Union Aviation Safety Agency (EASA) AD
> 2025-0208, dated September 24, 2025**.*

The FAA AD does not list the affected aircraft. It points at an EASA document. The set of
affected aircraft is defined *inside a file we do not hold*.

- **Naive RAG behaviour:** retrieves this paragraph, sees "Model A330-941", and answers
  "Yes, this AD applies to your A330-941." That is **wrong** — EASA AD 2025-0208 may scope
  by serial number, modification state or service-bulletin embodiment.
- **Our behaviour:** the ingest emits a `ForeignAD` node (`authority: "EASA"`,
  `ad_number: "2025-0208"`, `held: false`) and an `ADOPTS_MCAI` edge. The rules engine sees
  applicability delegated to an unheld document and refuses.
- **What the user sees:** *"Applicability for AD 2026-21-xx is defined in EASA AD 2025-0208
  (24 Sep 2025), which is not in this corpus. I can tell you this AD concerns Airbus A330-941
  FCPC software, but not whether it applies to MSN 1342. Load EASA AD 2025-0208 to resolve."*
  Plus the cited paragraph with the delegating clause highlighted.

This one case demonstrates the whole thesis: the engine refuses *precisely where a
plausible-sounding answer would be unsafe*, and it names the document that would fix it.

### 1b. Same code, compliance-time variant

Verified in `data/fixtures/ad_boeing_757_psu.xml`:

> *(g) Required Actions — ... **at the applicable times specified in the "Compliance"
> paragraph of Boeing Special Attention Requirements Bulletin 757-25-0320 RB, Revision 1,
> dated August 6, 2025**, do all applicable actions identified in ...*

The engineer's question is "by when?". The deadline is not in the AD — it is in a Boeing
service bulletin. The AD *is* applicable and we say so; we refuse only the deadline, and
name the bulletin. Answering part of the question and refusing the rest is the correct
behaviour, and the UI must support a partial answer with a scoped refusal.

---

## 2. `NEED_CONFIG` — the engineer knows it, we don't

Verified in the same Boeing fixture:

> *(c) Applicability — This AD applies to The Boeing Company Model 757-200 and -300 series
> airplanes, certificated in any category, **equipped with passenger service unit (PSU)-mounted
> video monitors**.*

Model and series we can check against the fleet record. Equipment fit we cannot — the
OpenSky aircraft database has no equipment column, and `docs/fleet.md` documents that
`equipment`, `modification`, `part_number` and `category` are structurally absent.

- **Behaviour:** rules on `model` evaluate normally; the `equipment` rule has no value to
  evaluate against, so the decision is withheld pending one input.
- **What the user sees:** *"This AD applies to 757-200/-300 airplanes **equipped with
  PSU-mounted video monitors**. N12345 is a 757-200 ✓. Is it fitted with PSU-mounted video
  monitors?"* — with an inline control to answer, which re-runs the decision live.
- **Why not `CANNOT_DETERMINE`:** a B1 technician can answer this in seconds by looking at
  the cabin. Marking it undeterminable would be wrong and would waste them.

The serial-number variant is the same shape: AD scopes by MSN range, query gave no MSN,
fleet record has a serial we can match — or doesn't, in which case ask.

---

## 3. `CANNOT_DETERMINE` — we could not parse the clause

Fires when rule extraction emits `operator: "unparsed"`. Real applicability prose gets
genuinely hard — nested exceptions, "except those with modification X embodied unless
also Y", tables of serial ranges by variant.

- **Behaviour:** the unparsed clause is surfaced verbatim and highlighted, never silently
  dropped and never guessed at.
- **What the user sees:** the clause, with *"I could not reduce this to a checkable rule —
  read paragraph (c) yourself."* plus a direct link to the paragraph.
- **Demo value:** this is the honest one. We will put 2-3 of these in the failure gallery
  with the actual text, because a system that hides its parse failures is the thing the
  competitive critique is about.

---

## 4. `NO_EVIDENCE` — not in the corpus

Top fused retrieval score below a tuned threshold.

- **What the user sees:** *"Not found in the N ADs loaded (Federal Register 2021-2026 plus
  431 NPRMs). This may exist in the full register."* — stating the corpus bound, not
  implying the AD doesn't exist.
- **Demo question:** an AD number from 2003, outside the ingest window.
- **Tuning:** the threshold is set on the eval set, and both false-refusal and
  false-answer rates at that threshold get reported. Picking it by eye is not acceptable.

---

## 5. `OUT_OF_SCOPE` — not an AD question

Query plan returns an intent outside AD content, or names a model absent from the corpus.

- **Demo questions:** *"What's the MEL dispatch limit for an inoperative APU?"* (different
  document class entirely), *"Who is the CEO of Boeing?"*
- **What the user sees:** a plain statement of what the engine does cover. No apology, no
  attempt to be helpful outside its evidence base.

---

## 6. `SUPERSEDED` — answered, with a warning

The only non-blocking code. The user asked about a revision that has a newer one.

- **Behaviour:** answer from the revision they asked about, banner at the top, link to
  current, and a diff of what changed in applicability between the two.
- **What the user sees:** *"AD 2024-xx-xx was superseded by AD 2026-xx-xx (effective
  2026-12-01). Answering from the revision you asked about — applicability widened to add
  the -300 series."*
- **Why it matters:** "which revision is current?" is one of the four questions in the
  user's job statement, and silently answering from a stale revision is a realistic way to
  ground an aircraft wrongly.

---

## Demo sequence (the refusal showcase)

Run these in order; it builds from "it works" to "it knows its limits":

1. **Clean hit** — a 737 AD with model-only applicability. Green proof tree, 3 citations,
   sub-3s. *Establishes competence.*
2. **`NEED_CONFIG`** — the 757 PSU case. Amber node, inline question, answer it, tree goes
   green live. *Shows it asks instead of guessing.*
3. **`EXTERNAL_SOURCE_REQUIRED`** — the A330-941 / EASA case, side by side with what plain
   vector RAG answers for the same question. *The money slide.*
4. **`SUPERSEDED`** — answer plus banner plus applicability diff. *Shows revision awareness.*
5. **BlastRadius** — one AD across the real fleet: red / grey / amber at once, with the
   amber cells traced back to the fleet null-rate table. *Shows it scales and stays honest.*

## Implementation requirements

- Every refusal is produced by code in the rules engine or verifier. The LLM never decides
  to refuse — if the model returns a refusal, that is a signal to check why retrieval or
  the rules engine did not catch it first.
- Every refusal payload carries `code`, `detail`, `resolvable_by` and
  `evidence_paragraph_ids` (per the contract's `refusal` SSE event). A refusal with no
  evidence paragraph is itself a defect — we must always be able to show *why*.
- Refusal recall is measured per code in the eval harness. Refusing with the *wrong* code
  counts as a miss, because the code is what tells the user who can fix it.
