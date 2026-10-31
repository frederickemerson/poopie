"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import { paragraphRef, sameParagraph } from "@/lib/citation";
import { REFUSAL_SEMANTICS } from "@/lib/contract";
import { useMotionPrefs } from "@/lib/motion";
import type { ExternalDocumentRef, ParagraphNode, RefusalPayload } from "@/lib/events";
import { QuoteInText } from "../ui/QuoteSpan";

interface RefusalCardProps {
  readonly refusal: RefusalPayload;
  readonly paragraphs: readonly ParagraphNode[];
  /**
   * The documents the decision was blocked on, from the same run's decision
   * event. The live refusal detail is a sentence, so these are the only
   * structured facts about the missing document and they come from the engine.
   */
  readonly externalDocuments?: readonly ExternalDocumentRef[];
  /** NEED_CONFIG is resolvable by the user; supplying the value re-runs. */
  readonly onSupplyValue?: (field: string, value: string) => void;
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
  <div className="grid grid-cols-[92px_1fr] items-baseline gap-2 border-t border-line px-3 py-2">
    <span className="t-label !tracking-[0.06em]">{label}</span>
    <div className="t-body text-ink-2">{children}</div>
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
  onSupplyValue,
}: RefusalCardProps) {
  const { dur } = useMotionPrefs();
  const semantics = REFUSAL_SEMANTICS[refusal.code];
  const blocks = semantics.blocks_answer;
  const [supplied, setSupplied] = useState("");

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
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-maybe/40 px-3 py-2">
        <span aria-hidden className="t-mono !text-[13px] font-bold text-maybe">
          &#9650;
        </span>
        <h3 className="t-mono !text-[13px] font-bold tracking-tight text-maybe">{refusal.code}</h3>
        <span className="t-label !tracking-[0.06em] text-ink-3">
          {blocks ? "answer withheld" : "answer still given"}
        </span>
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
          <div className="border-t border-line px-3 py-2">
            <p className="t-label mb-1.5">supply the value</p>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (supplied.trim()) {
                  onSupplyValue?.(needConfig.field, supplied.trim());
                }
              }}
            >
              <input
                aria-label="manufacturer serial number"
                value={supplied}
                onChange={(e) => setSupplied(e.target.value)}
                placeholder="MSN, e.g. 1224"
                className="t-mono w-32 border border-line bg-sunken px-2 py-1 text-ink placeholder:text-ink-3"
              />
              <button
                type="submit"
                className="t-label border border-line-strong bg-sunken px-3 py-1 text-ink hover:border-accent"
              >
                re-ask
              </button>
            </form>
          </div>
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
