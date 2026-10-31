"""Walk the engine end to end on a few questions and print the whole trace.

    python3 scripts/demo.py                 # no model calls, free
    python3 scripts/demo.py --write-answers # also runs the Sonnet writer

This is the defensibility check. It calls the same functions the SSE server
calls, in the same order, so a result here is a result in the product -- it
does not reimplement the pipeline, and if it diverges from the server that is
a bug in one of them.

What it prints per question: the entities code found, how the graph filter
narrowed, what was retrieved, what the rules engine decided and on which
rule, every refusal with its code, and -- with --write-answers -- each drafted
sentence with the citation code computed for it and whether the verifier kept
it.

Without --write-answers nothing calls a model, so this runs free and offline.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api.answer import build_envelope, write_answer  # noqa: E402
from engine.api.applicability import ApplicabilityStore, decide_for_query  # noqa: E402
from engine.graph.stage import annotate  # noqa: E402
from engine.llm.client import LLMClient, have_api_key  # noqa: E402
from engine.llm.ledger import CostLedger, default_cap_usd  # noqa: E402
from engine.retrieval.corpus import load_corpus  # noqa: E402
from engine.retrieval.entities import extract_entities  # noqa: E402
from engine.retrieval.index import load_index  # noqa: E402
from engine.retrieval.search import search  # noqa: E402
from engine.verify.gate import evaluate_gate  # noqa: E402
from engine.verify.verifier import verify  # noqa: E402

DIM = "\033[2m"
BOLD = "\033[1m"
OFF = "\033[0m"


def rule(char: str = "-", width: int = 78) -> str:
    return char * width


#: Chosen to exercise a different outcome each, not to flatter the engine.
#: The tail numbers are real rows in the built fleet.
QUESTIONS: list[tuple[str, str | None, str]] = [
    (
        "What does AD 2026-20-03 require and by when?",
        None,
        "a named AD with no aircraft: retrieval and stage should work, "
        "applicability cannot be decided without a tail number",
    ),
    (
        "Does AD 2026-20-03 apply to N220CY?",
        "N220CY",
        "a named AD and a real tail number: the rules engine should reach a "
        "decision and show which rule fired",
    ),
    (
        "Which ADs apply to my Airbus A330-941?",
        None,
        "a model with no tail number: a model alone matches many aircraft, so "
        "this should refuse rather than pick one",
    ),
    (
        "What is the best airline to fly to Tokyo?",
        None,
        "out of scope: there is no AD evidence for this and the engine must "
        "say so instead of answering",
    ),
]


def show(label: str, value: Any) -> None:
    print(f"  {label:22} {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-answers",
        action="store_true",
        help="also run the answer writer (costs money; needs ANTHROPIC_API_KEY)",
    )
    parser.add_argument("--cap", type=float, default=None, help="spend cap in USD")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    corpus = load_corpus()
    index = load_index(corpus)
    store = ApplicabilityStore.load()
    load_seconds = time.perf_counter() - started

    print(rule("="))
    print(f"{BOLD}AD traceability engine -- end to end{OFF}")
    print(rule("="))
    show("corpus", f"{len(corpus.paragraphs)} paragraphs, {len(corpus.ad_numbers)} ADs")
    show("fleet", f"{len(store.aircraft)} aircraft")
    show("rules loaded", f"{sum(len(v) for v in store.rules_by_revision.values())}")
    show(
        "delegations loaded",
        f"{sum(len(v) for v in store.delegations_by_revision.values())}",
    )
    show("load time", f"{load_seconds:.2f}s (the server pays this once at startup)")

    client = None
    ledger = None
    if args.write_answers:
        if not have_api_key():
            print("\n--write-answers needs ANTHROPIC_API_KEY; running without it")
        else:
            ledger = CostLedger(cap_usd=args.cap or default_cap_usd())
            client = LLMClient(ledger, offline=False)

    for question, tail, why in QUESTIONS:
        print()
        print(rule("="))
        print(f"{BOLD}Q: {question}{OFF}")
        if tail:
            print(f"   tail number: {tail}")
        print(f"{DIM}   expecting: {why}{OFF}")
        print(rule("-"))

        entities = extract_entities(question, known_ad_numbers=corpus.ad_numbers)
        show("AD numbers found", getattr(entities, "ad_numbers", None) or "none")
        show("models found", getattr(entities, "models", None) or "none")

        result = search(index, question, entities, k=8, revision_scope="current")
        show("graph filter", result.filter_report)
        if result.hits:
            top = result.hits[0]
            show("top paragraph", f"{top.paragraph_id}  role={top.role}")
            # None when the keyword arm alone produced this hit, which is not
            # the same as a cosine of zero and must not be printed as one.
            cosine = top.dense_cosine
            show(
                "top dense cosine",
                f"{cosine:.3f}" if cosine is not None else "none (keyword arm only)",
            )
        else:
            show("retrieved", "nothing")

        outcome = decide_for_query(
            store, tail_number=tail, entities=entities, plan=None, result=result
        )
        gate = evaluate_gate(corpus, entities, result, plan=None, rules_decision=outcome.decision)

        revision_id = (
            getattr(outcome.decision, "revision_id", None)
            if outcome.available
            else store.revision_from(entities=entities, result=result)
        )
        stage: dict[str, Any] = {}
        if revision_id:
            record = corpus.revisions.get(revision_id)
            if record is not None:
                as_dict = record if isinstance(record, dict) else getattr(record, "__dict__", {})
                stage = annotate(dict(as_dict))
        show("revision", revision_id or "none")
        show("document stage", stage.get("document_stage") or "UNKNOWN")

        if outcome.available:
            decision = outcome.decision
            show("DECISION", f"{BOLD}{decision.decision}{OFF}")
            show("fired rules", list(decision.fired_rule_ids) or "none")
            show("unknown fields", list(decision.unknown_fields) or "none")
            for condition in decision.conditions:
                as_dict = condition.as_dict()
                print(
                    f"    - {as_dict.get('field')} {as_dict.get('operator')} "
                    f"{as_dict.get('rule_value')!r} vs aircraft "
                    f"{as_dict.get('aircraft_value')!r} -> {as_dict.get('outcome')}"
                )
        else:
            show("DECISION", f"none -- {outcome.reason}")

        refusals = list(gate.payloads())
        engine_refusal = outcome.decision.refusal_payload() if outcome.available else None
        if engine_refusal and not any(r["code"] == engine_refusal["code"] for r in refusals):
            refusals.append(engine_refusal)
        if refusals:
            for refusal in refusals:
                print(f"  {BOLD}REFUSAL{OFF}              {refusal['code']}")
                print(f"    detail: {refusal.get('detail')}")
                if refusal.get("resolvable_by"):
                    print(f"    resolvable by: {refusal['resolvable_by']}")
        else:
            show("refusals", "none")

        verification = None
        drafted = None
        if client is not None and gate.answer_allowed and result.hits:
            drafted = write_answer(
                client, question, list(result.hits),
                stage_note=stage.get("document_stage"), label="demo_answer",
            )
            retrieved = {h.paragraph_id: h for h in result.hits}
            verification = verify(drafted.sentences, retrieved)
            print(rule("-"))
            show("drafted sentences", len(drafted.sentences))
            show("unresolved quotes", len(drafted.unresolved))
            for verdict in verification.verdicts:
                mark = f"{BOLD}KEPT{OFF}" if verdict.kept else "DROP"
                print(f"  [{mark}] {verdict.text}")
                if verdict.kept:
                    print(f"         cite {verdict.supporting_citation_id}")
                    print(f"         coverage {verdict.coverage:.2f}")
                else:
                    print(f"         {verdict.reason}: {verdict.detail}")

        answer_status = "REFUSED"
        if verification is not None and not verification.too_thin:
            answer_status = "PARTIAL" if verification.dropped else "ANSWERED"
        envelope = build_envelope(
            answer_status=answer_status,
            document_stage=stage.get("document_stage"),
            decision=outcome.decision if outcome.available else None,
            decision_unavailable=outcome.reason,
            verification=verification,
            answer=drafted,
            revision_id=revision_id,
            superseded_by=stage.get("superseded_by"),
            refusals=refusals,
            traversal=None,
            unreviewed_rules=sum(
                1
                for r in (store.rules_by_revision.get(revision_id or "") or [])
                if (r.get("review_status") or "UNREVIEWED") == "UNREVIEWED"
            ),
        )
        print(rule("-"))
        show("answer_status", envelope["answer_status"])
        for limitation in envelope["limitations"]:
            print(f"    limitation: {limitation}")
        if envelope["missing_inputs"]:
            show("missing inputs", envelope["missing_inputs"])

    if ledger is not None:
        print()
        print(rule("="))
        summary = ledger.summary()
        print(f"spend this run: ${summary['spent_usd']:.4f} lifetime, cap ${summary['cap_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
