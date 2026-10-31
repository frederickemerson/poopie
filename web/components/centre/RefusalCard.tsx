"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import { REFUSAL_SEMANTICS } from "@/lib/contract";
import { useMotionPrefs } from "@/lib/motion";
import type { ParagraphNode, RefusalPayload } from "@/lib/events";
import { QuoteInText } from "../ui/QuoteSpan";

interface RefusalCardProps {
  readonly refusal: RefusalPayload;
  readonly paragraphs: readonly ParagraphNode[];
  /** NEED_CONFIG is resolvable by the user; supplying the value re-runs. */
  readonly onSupplyValue?: (field: string, value: string) => void;
}

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
export function RefusalCard({ refusal, paragraphs, onSupplyValue }: RefusalCardProps) {
  const { dur } = useMotionPrefs();
  const semantics = REFUSAL_SEMANTICS[refusal.code];
  const blocks = semantics.blocks_answer;
  const [supplied, setSupplied] = useState("");

  const needConfig =
    refusal.code === "NEED_CONFIG" && "which_value" in refusal.detail
      ? refusal.detail.which_value
      : null;
  const externalDoc =
    refusal.code === "EXTERNAL_SOURCE_REQUIRED" && "external_doc_needed" in refusal.detail
      ? refusal.detail.external_doc_needed
      : null;
  const unparsed =
    refusal.code === "CANNOT_DETERMINE" && "unparsed_clause" in refusal.detail
      ? refusal.detail.unparsed_clause
      : null;
  const notInCorpus =
    refusal.code === "NO_EVIDENCE" && "not_in_corpus" in refusal.detail
      ? refusal.detail.not_in_corpus
      : null;
  const scope =
    refusal.code === "OUT_OF_SCOPE" && "scope_statement" in refusal.detail
      ? refusal.detail.scope_statement
      : null;

  const evidence = refusal.evidence_paragraph_ids
    .map((id) => paragraphs.find((p) => p.paragraph_id === id))
    .filter((p): p is ParagraphNode => p !== undefined);

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

      <Row label="trigger">{semantics.trigger}</Row>

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
        <span className="text-ink">{refusal.resolvable_by}</span>
        <span className="t-mono ml-2 text-ink-3">(contract resolvable_by)</span>
      </Row>

      {evidence.length > 0 ? (
        <div className="border-t border-line bg-sunken/50 px-3 py-2.5">
          <p className="t-label mb-2">standing on</p>
          <ul className="flex flex-col gap-2.5">
            {evidence.map((p) => (
              <li key={p.paragraph_id}>
                <p className="t-mono mb-1 text-ink-3">
                  {p.revision_id} &para;({p.label}) {p.heading}
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
