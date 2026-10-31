"""FastAPI service streaming the engine's stages as Server-Sent Events.

Event names and payload keys are pinned in contracts/contract.json and
validated on the way out by contracts.contract.validate_event, so the UI and
this service cannot drift apart silently.

The order of the stages is the product argument: entities and retrieval and the
applicability decision all land before the answer writer is called, so the user
sees the evidence before any prose exists to be wrong.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from contracts.contract import enum, validate_event
from engine.api.answer import build_envelope, write_answer
from engine.api.applicability import ApplicabilityStore, decide_for_query, fleet_matrix
from engine.api.citations import EMPTY_BOOK, ReferenceBook, page_report, resolver_for
from engine.api.library import Library
from engine.graph.stage import annotate, split_obligation_evidence
from engine.ingest.user_parse import (
    MAX_UPLOAD_BYTES,
    MEDIA_TYPES,
    UploadRejected,
)
from engine.llm.client import LLMClient, LLMUnavailable, have_api_key
from engine.llm.ledger import CostLedger, default_cap_usd
from engine.retrieval.corpus import load_corpus
from engine.retrieval.entities import extract_entities
from engine.retrieval.graph_filter import DEFAULT_SOURCE_KINDS, EVERY_SOURCE_KIND
from engine.retrieval.layout import default_corpus_paths
from engine.retrieval.index import load_index
from engine.retrieval.plan import plan_query
from engine.retrieval.search import search
from engine.verify.gate import evaluate_gate
from engine.verify.refusals import resolvable_by as refusal_resolver
from engine.verify.verifier import verify

#: What the library listing tells the UI it may send. Read from the places that
#: enforce them, so a form cannot offer a value the engine will refuse.
_UPLOAD_MEDIA_TYPES = tuple(MEDIA_TYPES)
_DOCUMENT_STAGES = tuple(enum("document_stage"))

#: Ceiling on the whole upload request body. The document itself is capped at
#: MAX_UPLOAD_BYTES by engine.ingest.user_parse; this is the envelope around it,
#: checked before the body is read into memory so an oversized request is
#: refused rather than buffered.
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024

app = FastAPI(title="AD traceability engine")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class _State:
    """Loaded once at startup; a query must never pay corpus-load cost."""

    corpus = None
    index = None
    ledger: CostLedger | None = None
    client: LLMClient | None = None
    applicability: ApplicabilityStore | None = None
    #: Human-readable citation fields, from the same nodes the corpus came from.
    #: Never None: an empty book still gives every citation a document_stage.
    references: ReferenceBook = EMPTY_BOOK
    #: The size of the indexed corpus, which the latency target is relative to.
    corpus_size: dict[str, Any] | None = None
    #: Documents the user loaded. None until startup has run; its own errors
    #: are reported through /health rather than failing the whole service, since
    #: a library that will not attach must not take the shipped corpus down.
    library: Library | None = None
    library_attach: dict[str, Any] | None = None
    error: str | None = None


STATE = _State()


@app.on_event("startup")
def _startup() -> None:
    paths = default_corpus_paths()
    try:
        STATE.corpus = load_corpus(paths)
        STATE.index = load_index(STATE.corpus)
    except Exception as exc:  # surfaced per-request, not swallowed
        STATE.error = f"{type(exc).__name__}: {exc}"
        return
    # Loaded here, once, for the same reason the corpus is: a citation's
    # human reference is one dict lookup per query, never a file read.
    references = ReferenceBook.load(paths.nodes)
    pages = page_report(references, source=str(paths.nodes))
    # The library is attached AFTER the shipped index has been opened and
    # checked against the shipped corpus, so the fingerprint check still means
    # what it says. It then appends to both, in that order, and reports it.
    STATE.library = Library(STATE.corpus, STATE.index, references)
    try:
        STATE.library_attach = STATE.library.attach()
    except Exception as exc:  # a bad library must not take the corpus down
        STATE.library_attach = {"error": f"{type(exc).__name__}: {exc}"}
    STATE.references = STATE.library.references
    STATE.corpus_size = {
        "kind": paths.kind,
        "paragraphs": len(STATE.corpus.paragraphs),
        "ad_numbers": len(STATE.corpus.ad_numbers),
        "revisions": pages["adopted"]["documents"],
        "proposals": pages["proposed"]["documents"],
        "federal_register_pages": pages["total_distinct_pages"],
        "pages": pages,
    }
    STATE.ledger = CostLedger(cap_usd=default_cap_usd())
    STATE.client = LLMClient(STATE.ledger, offline=not have_api_key())
    STATE.applicability = ApplicabilityStore.load()


def _plain(obj: Any) -> Any:
    """Make engine dataclasses JSON-serializable without leaking their types."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_plain(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _retrieval_paragraphs(hits: Iterable[Any], resolve: Any) -> list[dict[str, Any]]:
    """The retrieved set, each paragraph carrying its human reference.

    The reference rides inside each paragraph rather than in a new top-level
    payload key, because the contract pins ``retrieval`` to exactly
    ``paragraphs``, ``scores`` and ``stage_ms`` and this engine does not add
    payload keys the contract has not declared. It also puts the reference
    exactly where the UI resolves a citation: against the retrieved paragraph.

    Each row is built from ``Hit.as_payload()``, the hit's own named wire shape,
    rather than from ``_plain``. ``_plain`` ends in ``str(obj)`` for anything it
    does not recognise, so a hit it did not recognise would reach the browser as
    a bare string inside a payload whose top-level keys still validate -- a
    paragraph that looks present and carries nothing. A hit that cannot name its
    own fields raises here instead.
    """
    out: list[dict[str, Any]] = []
    for hit in hits:
        as_payload = getattr(hit, "as_payload", None)
        if not callable(as_payload):
            raise TypeError(
                f"retrieval hit of type {type(hit).__name__} has no as_payload(); the "
                f"retrieval payload is built from named fields and is never stringified"
            )
        row = dict(as_payload())
        # as_payload is the scoring view and omits the paragraph text, which the
        # UI needs to draw the cited span inside it.
        row["text"] = str(getattr(hit, "text", "") or "")
        row["human_reference"] = resolve(str(row.get("citation_id") or "")).as_dict()
        out.append(row)
    return out


def _revision_stage(revision_id: str | None) -> dict[str, Any] | None:
    """Legal stage of the revision an answer came from, or None if unknown."""
    if not revision_id or STATE.corpus is None:
        return None
    revisions = getattr(STATE.corpus, "revisions", None) or {}
    record = revisions.get(revision_id) if isinstance(revisions, dict) else None
    if record is None and not isinstance(revisions, dict):
        record = next(
            (r for r in revisions if getattr(r, "revision_id", None) == revision_id), None
        )
    if record is None:
        return None
    as_dict = record if isinstance(record, dict) else getattr(record, "__dict__", {})
    return annotate(dict(as_dict))


def _unreviewed_rules(revision_id: str | None) -> int:
    """How many rules behind this answer are machine-extracted, not reviewed.

    The envelope states this because a rule nobody has checked is a real
    limitation of the answer, not an implementation detail.
    """
    if not revision_id or STATE.applicability is None:
        return 0
    rules = STATE.applicability.rules_by_revision.get(revision_id) or []
    return sum(1 for r in rules if (r.get("review_status") or "UNREVIEWED") == "UNREVIEWED")


def _sse(name: str, payload: dict[str, Any]) -> str:
    """Serialize one event, refusing any shape the contract does not declare."""
    validate_event(name, payload)
    return f"event: {name}\ndata: {json.dumps(_plain(payload))}\n\n"


class Query(BaseModel):
    q: str
    tail_number: str | None = None
    #: Widen retrieval to the documents the user loaded. Off by default; see
    #: engine.retrieval.graph_filter for why that default is not a nicety. Even
    #: when on, a user document can appear in the retrieval trace and never in
    #: the answer: split_obligation_evidence removes it before the writer.
    include_user_documents: bool = False


class LibraryUpload(BaseModel):
    """One document, as text. See ``POST /library/documents``."""

    title: str
    authority: str
    document_stage: str
    content: str
    filename: str | None = None
    media_type: str | None = None


class LibraryQuery(BaseModel):
    q: str
    k: int = 8


def _stream(
    q: str, tail_number: str | None, *, include_user_documents: bool = False
) -> Iterator[str]:
    if STATE.error or STATE.corpus is None or STATE.index is None:
        yield _sse("error", {"message": STATE.error or "corpus not loaded"})
        return

    started = time.perf_counter()
    timings: dict[str, float] = {}

    # 1. Entity pass - pure code, no model, and often enough on its own.
    t0 = time.perf_counter()
    entities = extract_entities(q, known_ad_numbers=STATE.corpus.ad_numbers)
    timings["entity_pass"] = (time.perf_counter() - t0) * 1000
    yield _sse("entities", {"entities": _plain(entities), "stage_ms": round(timings["entity_pass"], 2)})

    # 2. Query plan - the first of only two model calls in the whole path.
    t0 = time.perf_counter()
    try:
        outcome = plan_query(STATE.client, q)
        plan = outcome.plan
    except LLMUnavailable:
        outcome, plan = None, None
    timings["query_plan"] = (time.perf_counter() - t0) * 1000
    yield _sse(
        "query_plan",
        {
            "plan": _plain(plan) if plan is not None else None,
            "stage_ms": round(timings["query_plan"], 2),
            "model": getattr(outcome, "model", None) if outcome else None,
        },
    )

    # 3. Retrieval - graph filter, then keyword + dense, fused. No model.
    t0 = time.perf_counter()
    result = search(
        STATE.index, q, entities,
        k=8,
        revision_scope=(getattr(plan, "revision_scope", None) or "current"),
        source_kinds=(
            EVERY_SOURCE_KIND if include_user_documents else DEFAULT_SOURCE_KINDS
        ),
    )
    timings["retrieval"] = (time.perf_counter() - t0) * 1000
    # One resolver for this query: it closes over the retrieved paragraphs, so
    # every reference it hands out can name the paragraph's role.
    reference_for = resolver_for(STATE.references, result.hits)
    yield _sse(
        "retrieval",
        {
            "paragraphs": _retrieval_paragraphs(result.hits, reference_for),
            "scores": [round(getattr(h, "score", 0.0), 4) for h in result.hits],
            "stage_ms": round(timings["retrieval"], 2),
        },
    )

    # 4. Applicability: the rules engine, not the model, decides. Pure code.
    t0 = time.perf_counter()
    outcome = decide_for_query(
        STATE.applicability,
        tail_number=tail_number,
        entities=entities,
        plan=plan,
        result=result,
    )
    gate = evaluate_gate(
        STATE.corpus, entities, result,
        plan=plan,
        rules_decision=outcome.decision,
    )
    timings["applicability"] = (time.perf_counter() - t0) * 1000
    stage_ms = round(timings["applicability"], 2)

    if outcome.available:
        payload = outcome.decision.sse_payload(stage_ms)
        # An AD adopted but not yet effective imposes no obligation today.
        # Stating the stage is part of being correct, not a footnote.
        tree = payload.get("proof_tree")
        if isinstance(tree, dict):
            tree["stage"] = _revision_stage(outcome.decision.revision_id)
        yield _sse("decision", payload)
    else:
        # No decision is itself information: say why, never emit a guess.
        yield _sse(
            "decision",
            {
                "decision": None,
                "fired_rule_ids": [],
                "unknown_fields": [],
                "proof_tree": {"unavailable": outcome.reason},
                "stage_ms": stage_ms,
            },
        )

    # A blocking refusal ends the turn here: no prose is generated at all,
    # which is the point - we never write a sentence we cannot support.
    refusals = list(gate.payloads())
    engine_refusal = outcome.decision.refusal_payload() if outcome.available else None
    if engine_refusal and not any(r["code"] == engine_refusal["code"] for r in refusals):
        refusals.append(engine_refusal)

    # **The writer only ever sees evidence that may carry an obligation.**
    # With the default retrieval scope every hit is an adopted revision and this
    # partitions to everything-eligible, so it changes nothing there. It is the
    # fence for the scopes that are opt-in: a proposal or a document the user
    # loaded can be retrieved, shown and cited in the trace above, and still
    # cannot reach the model that writes "you must". The writer's own prompt
    # calls its inputs "paragraphs retrieved from adopted FAA ADs", and the
    # verifier only checks that a quote is verbatim in a retrieved paragraph --
    # so nothing downstream would catch this, and it has to hold here.
    admissible, set_aside = split_obligation_evidence(list(result.hits))
    no_admissible_evidence = bool(result.hits) and not admissible
    if no_admissible_evidence:
        kinds = sorted({str(p.get("source_kind")) for p in set_aside})
        refusals.append(
            {
                "code": "NO_EVIDENCE",
                "detail": (
                    f"all {len(set_aside)} retrieved paragraph(s) came from "
                    f"{', '.join(kinds)} documents, none of which may establish an "
                    f"obligation in this engine. Nothing was written from them."
                ),
                "resolvable_by": refusal_resolver("NO_EVIDENCE"),
                "evidence_paragraph_ids": [
                    str(p.get("paragraph_id")) for p in set_aside
                ],
            }
        )
    for refusal in refusals:
        yield _sse("refusal", refusal)

    if (
        not gate.answer_allowed
        or no_admissible_evidence
        or (engine_refusal and engine_refusal.get("code") != "SUPERSEDED")
    ):
        # A refusal is a delivered answer, so it carries the same envelope an
        # answer would. Refusing without saying what was and was not
        # established, and what would resolve it, is just a dead end.
        blocked_revision = (
            getattr(outcome.decision, "revision_id", None)
            if outcome.available
            else (
                STATE.applicability.revision_from(entities=entities, result=result)
                if STATE.applicability
                else None
            )
        )
        blocked_stage = _revision_stage(blocked_revision) or {}
        yield _sse(
            "done",
            {
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
                "stage_timings": {k: round(v, 2) for k, v in timings.items()},
                "envelope": build_envelope(
                    answer_status="REFUSED",
                    document_stage=blocked_stage.get("document_stage"),
                    decision=outcome.decision if outcome.available else None,
                    decision_unavailable=outcome.reason,
                    verification=None,
                    answer=None,
                    revision_id=blocked_revision,
                    superseded_by=blocked_stage.get("superseded_by"),
                    refusals=refusals,
                    traversal=None,
                    unreviewed_rules=_unreviewed_rules(blocked_revision),
                    references=reference_for,
                ),
            },
        )
        return

    # 5. The answer writer: the second and last model call in the path. It is
    # given only the paragraphs already streamed above, and it names its
    # evidence by quoting it -- code, not the model, computes the offsets.
    revision_id = getattr(outcome.decision, "revision_id", None) if outcome.available else None
    if revision_id is None and STATE.applicability is not None:
        revision_id = STATE.applicability.revision_from(entities=entities, result=result)
    stage = _revision_stage(revision_id) or {}
    document_stage = stage.get("document_stage")

    t0 = time.perf_counter()
    drafted = write_answer(STATE.client, q, admissible, stage_note=document_stage)
    timings["answer"] = (time.perf_counter() - t0) * 1000
    for sentence in drafted.sentences:
        yield _sse(
            "answer_delta",
            {
                "sentence": sentence.text,
                "citation_ids": list(sentence.citation_ids),
                "index": sentence.index,
            },
        )

    # 6. Verification: pure code, and the only route to the screen. Sentences
    # are streamed above with their citations so the UI can show a drop
    # happening, which is the point: the gate is visible, not implied.
    retrieved = {hit.paragraph_id: hit for hit in result.hits}
    verification = verify(drafted.sentences, retrieved)
    timings["verify"] = verification.stage_ms
    yield _sse("verification", verification.as_payload())

    # A draft thinned past the floor becomes a refusal rather than a short
    # answer: a half-verified answer in this domain reads as a complete one.
    answer_status = "ANSWERED"
    thin_detail: str | None = None
    if not drafted.available:
        thin_detail = drafted.reason or "the answer writer produced no sentences"
    elif verification.too_thin:
        thin_detail = (
            f"{len(verification.kept)} of {len(verification.verdicts)} drafted "
            "sentences survived citation verification, below the floor for "
            "showing an answer at all"
        )
    if thin_detail is not None:
        answer_status = "REFUSED"
        yield _sse(
            "refusal",
            {
                "code": "NO_EVIDENCE",
                "detail": thin_detail,
                # Prose naming who can resolve this, read from the contract's
                # refusal_semantics. It is a string for every other producer;
                # this one emitted [] and was the second half of the type
                # inconsistency that made a consumer iterate a string.
                "resolvable_by": refusal_resolver("NO_EVIDENCE"),
                "evidence_paragraph_ids": sorted(retrieved),
            },
        )
    elif verification.dropped:
        answer_status = "PARTIAL"

    # The envelope rides on `done` rather than an event of its own: it is not a
    # pipeline stage, it is the finished result, and the contract keeps one
    # stage name per event.
    yield _sse(
        "done",
        {
            "total_ms": round((time.perf_counter() - started) * 1000, 2),
            "stage_timings": {k: round(v, 2) for k, v in timings.items()},
            "envelope": build_envelope(
                answer_status=answer_status,
                document_stage=document_stage,
                decision=outcome.decision if outcome.available else None,
                decision_unavailable=outcome.reason,
                verification=verification,
                answer=drafted,
                revision_id=revision_id,
                superseded_by=stage.get("superseded_by"),
                refusals=refusals,
                traversal=None,
                unreviewed_rules=_unreviewed_rules(revision_id),
                references=reference_for,
            ),
        },
    )


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness, plus the size of the corpus the latency target applies to.

    The 3-second target is only meaningful next to a corpus size, so the size
    is served from the same place as the readiness flags rather than quoted in
    a document that can go stale: paragraphs, documents, and the Federal
    Register page count the citations themselves add up to.
    """
    return {
        "corpus_loaded": STATE.corpus is not None,
        "index_loaded": STATE.index is not None,
        "llm": "live" if have_api_key() else "offline",
        "error": STATE.error,
        "spend": STATE.ledger.summary() if STATE.ledger else None,
        "corpus": STATE.corpus_size,
        "library": (
            {**STATE.library.as_report(), "attach": STATE.library_attach}
            if STATE.library is not None
            else {"error": STATE.error or "library not loaded"}
        ),
    }


@app.get("/blast/{revision_id}")
def blast(revision_id: str) -> dict[str, Any]:
    """Every fleet aircraft's decision for one revision, for BlastRadius."""
    if STATE.applicability is None:
        return {"error": STATE.error or "applicability store not loaded"}
    return fleet_matrix(STATE.applicability, revision_id)


@app.post("/stream")
def stream(query: Query) -> StreamingResponse:
    return StreamingResponse(
        _stream(
            query.q,
            query.tail_number,
            include_user_documents=query.include_user_documents,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------- library
#
# Documents the user loaded. Three endpoints, and the shape of each response
# states what a user document is *not*: it never joins the default retrieval
# scope, and it can never establish an obligation. That is in the payload rather
# than in a docstring because the UI renders the payload.


def _library_or_error() -> tuple[Library | None, JSONResponse | None]:
    if STATE.library is None:
        return None, JSONResponse(
            status_code=503,
            content={"error": STATE.error or "the engine has not finished starting"},
        )
    return STATE.library, None


@app.get("/library")
def library_list() -> Any:
    """Every document the user has loaded, newest first."""
    library, failure = _library_or_error()
    if library is None:
        return failure
    return {
        "documents": library.documents(),
        "status": library.as_report(),
        "limits": {
            "max_bytes": MAX_UPLOAD_BYTES,
            "media_types": sorted(_UPLOAD_MEDIA_TYPES),
            "document_stages": list(_DOCUMENT_STAGES),
        },
    }


@app.post("/library/documents")
async def library_upload(request: Request) -> Any:
    """Load one document.

    JSON, not multipart: the body is ``{"title", "authority",
    "document_stage", "content", "filename"}`` with the document itself as the
    ``content`` string. One shape to validate, trivially proxied by the Next
    route, and the size check can happen before the body is read.

    The upload is never executed, never written over an existing artifact and
    never passed to a shell. It lands in ``data/user_documents/uploads`` under a
    name derived from its own content hash.
    """
    library, failure = _library_or_error()
    if library is None:
        return failure

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_REQUEST_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "error": f"request body is {declared} bytes; the limit is "
                f"{MAX_UPLOAD_REQUEST_BYTES}"
            },
        )
    body = await request.body()
    if len(body) > MAX_UPLOAD_REQUEST_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "error": f"request body is {len(body)} bytes; the limit is "
                f"{MAX_UPLOAD_REQUEST_BYTES}"
            },
        )
    try:
        payload = LibraryUpload.model_validate_json(body)
    except ValueError as exc:
        return JSONResponse(
            status_code=400, content={"error": f"the upload body is not valid: {exc}"}
        )

    try:
        # Parsing and embedding are CPU work; off the event loop so an upload
        # cannot stall an answer already streaming.
        report = await run_in_threadpool(
            library.add,
            payload.content.encode("utf-8"),
            title=payload.title,
            authority=payload.authority,
            document_stage=payload.document_stage,
            filename=payload.filename,
            media_type=payload.media_type,
        )
    except UploadRejected as exc:
        # A refusal the uploader can act on, not a server error.
        return JSONResponse(status_code=422, content={"error": str(exc)})
    return report


@app.post("/library/search")
def library_search(query: LibraryQuery) -> Any:
    """Search the user's own documents, and only those."""
    library, failure = _library_or_error()
    if library is None:
        return failure
    return library.search(query.q, k=query.k)
