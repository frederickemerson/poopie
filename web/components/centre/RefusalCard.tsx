"use client";

import { motion } from "framer-motion";
import { paragraphRef, sameParagraph } from "@/lib/citation";
import { REFUSAL_SEMANTICS } from "@/lib/contract";
import type { AskIntent, MissingField } from "@/lib/conversation";
import { useMotionPrefs } from "@/lib/motion";
import type { ExternalDocumentRef, ParagraphNode, RefusalPayload } from "@/lib/events";
import { QuoteInText } from "../ui/QuoteSpan";
import { RefusalResolver, type FocusRequest } from "./RefusalResolver";

interface RefusalCardProps {
  readonly refusal: RefusalPayload;
  readonly paragraphs: readonly ParagraphNode[];
  /**
   * The documents the decision was blocked on, from the same run's decision
   * event. The live refusal detail is a sentence, so these are the only
   * structured facts about the missing document and they come from the engine.
   */
  readonly externalDocuments?: readonly ExternalDocumentRef[];
  /**
   * What turns this refusal into the next question. Omitted on an archived or
   * recorded run, where there is nothing to re-ask.
   */
  readonly onAsk?: (intent: AskIntent) => void;
  /** Fields the engine named in `unknown_fields`, with the rule behind each. */
  readonly missing?: readonly MissingField[];
  /** The aircraft the decision was made against, for phrasing an assertion. */
  readonly subject?: string | null;
  /** The question that was refused, so a rephrase starts from the user's words. */
  readonly asked?: string;
  readonly busy?: boolean;
  readonly focusRequest?: FocusRequest | null;
}

/** How many evidence paragraphs are shown in full before they are counted. */
const EVIDENCE_SHOWN = 3;

/** Who can clear the blocker. The product's whole point is this distinction. */
const RESOLVER: Readonly<Record<string, string>> = {
  NEED_CONFIG: "you can clear this — the value is known on the aircraft, not in the record",
  EXTERNAL_SOURCE_REQUIRED: "loading the named document clears this — nobody can reason it out",
  CANNOT_DETERMINE: "a human reading the clause clears this — our extractor could not",
};

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="grid grid-cols-1 items-baseline gap-x-2 gap-y-0.5 sm:grid-cols-[92px_minmax(0,1fr)] border-t border-line px-3 py-2">
    <span className="t-label !tracking-[0.06em] break-words">{label}</span>
    <div className="t-body min-w-0 text-ink-2">{children}</div>
  </div>
);

/**
 * A refusal is a card, never prose. It states the contract code, the trigger the
 * contract documents for that code, what would resolve it, and the evidence it
 * is standing on.
 */
export function RefusalCard({
  refusal,
  paragraphs,
  externalDocuments = [],
  onAsk,
  missing = [],
  subject = null,
  asked = "",
  busy = false,
  focusRequest = null,
}: RefusalCardProps) {
  const { dur } = useMotionPrefs();
  const semantics = REFUSAL_SEMANTICS[refusal.code];
  const blocks = semantics.blocks_answer;

  // The live service sends `detail` as one sentence naming the exact missing
  // thing; the recorded stream sends a keyed object. Both are rendered as they
  // arrive - a sentence is never reshaped into fields it does not contain.
  const sentence = typeof refusal.detail === "string" ? refusal.detail : null;
  const keyed = typeof refusal.detail === "string" ? null : refusal.detail;

  const needConfig =
    refusal.code === "NEED_CONFIG" && keyed && "which_value" in keyed ? keyed.which_value : null;
  const externalDoc =
    refusal.code === "EXTERNAL_SOURCE_REQUIRED" && keyed && "external_doc_needed" in keyed
      ? keyed.external_doc_needed
      : null;
  const unparsed =
    refusal.code === "CANNOT_DETERMINE" && keyed && "unparsed_clause" in keyed
      ? keyed.unparsed_clause
      : null;
  const notInCorpus =
    refusal.code === "NO_EVIDENCE" && keyed && "not_in_corpus" in keyed ? keyed.not_in_corpus : null;
  const scope =
    refusal.code === "OUT_OF_SCOPE" && keyed && "scope_statement" in keyed
      ? keyed.scope_statement
      : null;

  // Documents the corpus does not hold. Only shown for the code that is about
  // them, so a NEED_CONFIG card never implies a missing document.
  const missingDocs =
    refusal.code === "EXTERNAL_SOURCE_REQUIRED"
      ? externalDocuments.filter((d) => d.held !== true)
      : [];
  const resolverNote = RESOLVER[refusal.code] ?? null;

  const resolved = refusal.evidence_paragraph_ids
    .map((id) => paragraphs.find((p) => sameParagraph(p.paragraph_id, id)))
    .filter((p): p is ParagraphNode => p !== undefined);
  // A gate-level refusal can stand on the whole retrieved set. Show the first
  // few in full and count the rest, so the card stays readable without hiding
  // that the refusal rests on more than what is on screen.
  const evidence = resolved.slice(0, EVIDENCE_SHOWN);
  const moreEvidence = resolved.length - evidence.length;

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: dur(240), ease: [0.2, 0.8, 0.2, 1] }}
      aria-label={`refusal ${refusal.code}`}
      className="m-4 border border-maybe/60 bg-maybe-bg/40"
    >
      {/* The verdict, when the verdict is a refusal. It leads at heading scale
          because it is the answer to what was asked -- not a warning strip
          above the real content. Ember is spent here on purpose: the refusal
          code is one of the three things in this system allowed to carry it. */}
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-maybe/40 px-4 py-3">
        <span aria-hidden className="t-mono !text-[12px] text-accent">
          &#9650;
        </span>
        {/* EXTERNAL_SOURCE_REQUIRED is 24 unbreakable characters at heading
            size. Without these it is wider than a 320px phone and gives the
            whole page a horizontal scrollbar. */}
        <h3 className="t-heading min-w-0 break-words text-accent">{refusal.code}</h3>
        <span className="t-label">{blocks ? "answer withheld" : "answer still given"}</span>
      </header>

      {resolverNote ? (
        <p className="t-body border-b border-maybe/40 bg-maybe-bg/60 px-3 py-1.5 text-ink">
          {resolverNote}
        </p>
      ) : null}

      {sentence ? (
        <Row label="detail">
          <span className="text-ink">{sentence}</span>
        </Row>
      ) : null}

      <Row label="trigger">{semantics.trigger}</Row>

      {missingDocs.length > 0 ? (
        <div className="border-t border-line px-3 py-2.5">
          <p className="t-label mb-2">
            document{missingDocs.length === 1 ? "" : "s"} required &middot; not in this corpus
          </p>
          <ul className="flex flex-col gap-2">
            {missingDocs.map((doc, i) => (
              <li key={doc.doc_id ?? i} className="border border-line-strong bg-sunken">
                <div className="flex flex-wrap items-stretch">
                  <div className="border-r border-line-strong px-3 py-2">
                    <p className="t-label !tracking-[0.06em]">kind</p>
                    <p className="t-mono !text-[13px] font-bold text-ink">
                      {doc.doc_type ?? "document"}
                    </p>
                  </div>
                  <div className="border-r border-line-strong px-3 py-2">
                    <p className="t-label !tracking-[0.06em]">dated</p>
                    <p className="t-mono !text-[13px] text-ink">{doc.dated ?? "undated"}</p>
                  </div>
                  <div className="border-r border-line-strong px-3 py-2">
                    <p className="t-label !tracking-[0.06em]">held</p>
                    <p className="t-mono !text-[13px] font-bold text-maybe">{String(doc.held === true)}</p>
                  </div>
                  <div className="min-w-0 flex-1 px-3 py-2">
                    <p className="t-label !tracking-[0.06em]">reference</p>
                    <p className="t-mono !text-[13px] text-ink">{doc.doc_id ?? "unidentified"}</p>
                  </div>
                </div>
                {doc.label ? <p className="t-body border-t border-line px-3 py-1.5 text-ink-2">{doc.label}</p> : null}
                {doc.source_quote ? (
                  <p className="t-body border-t border-line px-3 py-1.5 text-ink-3">
                    &ldquo;{doc.source_quote}&rdquo;
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="t-mono mt-2 text-ink-3">
            The affected set is defined inside the document above. Guessing membership from the AD
            text alone is exactly the failure mode this refusal exists to prevent.
          </p>
        </div>
      ) : null}

      {needConfig ? (
        <>
          <Row label="question">
            <span className="text-ink">{needConfig.question}</span>
          </Row>
          <Row label="rule value">
            <span className="t-mono text-ink">{needConfig.rule_value}</span>
          </Row>
        </>
      ) : null}

      {externalDoc ? (
        <>
          <Row label="delegated">
            <span className="text-ink">
              Paragraph (c) hands the affected-set definition to a document this corpus does not
              hold, so membership cannot be established from the AD text alone.
            </span>
          </Row>
          <div className="border-t border-line px-3 py-2.5">
            <p className="t-label mb-2">document required</p>
            <div className="flex flex-wrap items-stretch gap-0 border border-line-strong bg-sunken">
              <div className="border-r border-line-strong px-3 py-2">
                <p className="t-label !tracking-[0.06em]">authority</p>
                <p className="t-mono !text-[13px] font-bold text-ink">
                  {externalDoc.authority}
                </p>
              </div>
              <div className="border-r border-line-strong px-3 py-2">
                <p className="t-label !tracking-[0.06em]">AD</p>
                <p className="t-mono !text-[13px] font-bold text-ink">
                  {externalDoc.ad_number}
                </p>
              </div>
              <div className="border-r border-line-strong px-3 py-2">
                <p className="t-label !tracking-[0.06em]">dated</p>
                <p className="t-mono !text-[13px] text-ink">{externalDoc.dated}</p>
              </div>
              <div className="px-3 py-2">
                <p className="t-label !tracking-[0.06em]">held</p>
                <p className="t-mono !text-[13px] font-bold text-maybe">
                  {String(externalDoc.held)}
                </p>
              </div>
            </div>
            <p className="t-mono mt-2 text-ink-3">
              available from the EASA AD publishing tool at ad.easa.europa.eu, and in the AD docket
              on regulations.gov
            </p>
          </div>
        </>
      ) : null}

      {unparsed ? (
        <Row label="clause">
          <span className="t-mono text-ink">{unparsed}</span>
        </Row>
      ) : null}

      {notInCorpus ? <Row label="corpus">{notInCorpus}</Row> : null}

      {scope ? <Row label="scope">{scope}</Row> : null}

      <Row label="resolved by">
        <span className="text-ink">{refusal.resolvable_by}</span>{" "}
        <span className="t-mono text-ink-3">(as the engine reported it)</span>
      </Row>

      {/* The refusal, as the next turn. Every input a code honestly has lives
          in one place, so no code can grow a bespoke half-input beside it. */}
      {onAsk ? (
        <RefusalResolver
          refusal={refusal}
          missing={missing}
          documents={externalDocuments}
          subject={subject}
          asked={asked}
          onAsk={onAsk}
          busy={busy}
          focusRequest={focusRequest}
        />
      ) : null}

      {evidence.length > 0 ? (
        <div className="border-t border-line bg-sunken/50 px-3 py-2.5">
          <p className="t-label mb-2">
            standing on{moreEvidence > 0 ? ` · ${evidence.length} of ${resolved.length} shown` : ""}
          </p>
          <ul className="flex flex-col gap-2.5">
            {evidence.map((p) => (
              <li key={p.paragraph_id}>
                <p className="t-mono mb-1 text-ink-3">
                  {p.revision_id} {paragraphRef(p.label)} {p.heading}
                </p>
                <QuoteInText
                  text={p.text}
                  quote={externalDoc?.delegated_quote ?? needConfig?.source_quote ?? ""}
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </motion.section>
  );
}
