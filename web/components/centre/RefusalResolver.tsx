"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  SUPPLIED_DOCUMENT_LIMIT,
  SUPPLIED_VALUE_LIMIT,
  askWithDocumentText,
  askWithValues,
  blockingDocuments,
  documentLookup,
  documentName,
  fieldPlaceholder,
  fieldPrompt,
  type AskIntent,
  type MissingField,
} from "@/lib/conversation";
import type { ExternalDocumentRef, RefusalPayload } from "@/lib/events";

export interface FocusRequest {
  readonly field: string;
  readonly nonce: number;
}

interface RefusalResolverProps {
  readonly refusal: RefusalPayload;
  /** Fields the engine named in `unknown_fields`, with the rule behind each. */
  readonly missing: readonly MissingField[];
  /** Documents named by the decision; the unheld ones are the blockers. */
  readonly documents: readonly ExternalDocumentRef[];
  /** The aircraft the decision was made against, for phrasing an assertion. */
  readonly subject: string | null;
  /** The question that was refused, so a rephrase starts from the user's words. */
  readonly asked: string;
  readonly onAsk: (intent: AskIntent) => void;
  readonly busy: boolean;
  /** Set when another panel asked for one of these inputs to take focus. */
  readonly focusRequest?: FocusRequest | null;
}

const Note = ({ children }: { children: React.ReactNode }) => (
  <p className="t-mono mt-2 text-ink-2">{children}</p>
);

const Submit = ({ busy, children }: { busy: boolean; children: React.ReactNode }) => (
  <button
    type="submit"
    disabled={busy}
    className="t-label shrink-0 self-start border border-line-strong bg-raised px-3 py-1.5 text-ink transition-colors hover:border-accent focus-visible:border-accent disabled:cursor-not-allowed disabled:text-ink-3 disabled:hover:border-line-strong"
  >
    {children}
  </button>
);

/**
 * A refusal, turned into the next turn.
 *
 * Every code in the contract gets whatever action is honestly available for it,
 * and nothing more:
 *
 *  - NEED_CONFIG is the one a person can answer, so each field the engine named
 *    in `unknown_fields` gets a real labelled input, prompted from the rule the
 *    engine could not evaluate rather than from the bare field name.
 *  - EXTERNAL_SOURCE_REQUIRED is blocked on a document we do not hold, so the
 *    actions are to paste its applicability text (attributed to the user, in
 *    the question and in the thread) or to go and find it.
 *  - OUT_OF_SCOPE and NO_EVIDENCE are about the question, so the affordance is
 *    the question itself, seeded with what was asked.
 *  - CANNOT_DETERMINE gets no input at all. The contract says a human has to
 *    read the clause; offering a box here would imply otherwise.
 *
 * What it will not do is claim the re-ask clears the refusal. Verified against
 * the live engine: a value stated in the question leaves `aircraft_value` null
 * and the condition's outcome `unknown`, and pasted document text leaves the
 * gate refusing. Both limits are stated next to the button that sends them.
 */
export function RefusalResolver({
  refusal,
  missing,
  documents,
  subject,
  asked,
  onAsk,
  busy,
  focusRequest = null,
}: RefusalResolverProps) {
  const baseId = useId();
  const [values, setValues] = useState<Readonly<Record<string, string>>>({});
  const [docText, setDocText] = useState("");
  const [rephrased, setRephrased] = useState(asked);
  const fieldRefs = useRef(new Map<string, HTMLInputElement>());

  // The question changes under this component when a new run starts, so the
  // rephrase box follows it rather than holding a stale question.
  useEffect(() => setRephrased(asked), [asked]);

  // Another panel (the envelope's "what would settle this" list) can ask for
  // one of these inputs. Focus moves, and nothing is asserted on the user's
  // behalf: a button that re-asked with the rule's own value filled in would be
  // the UI inventing a fact about the aircraft.
  useEffect(() => {
    if (!focusRequest) return;
    const el = fieldRefs.current.get(focusRequest.field);
    el?.focus();
    el?.scrollIntoView({ block: "center", behavior: "auto" });
  }, [focusRequest]);

  if (refusal.code === "NEED_CONFIG") {
    if (missing.length === 0) return null;
    return (
      <form
        className="border-t border-line px-3 py-3"
        onSubmit={(event) => {
          event.preventDefault();
          const answers = missing
            .map((field) => ({ missing: field, value: values[field.field] ?? "" }))
            .filter((answer) => answer.value.trim() !== "");
          if (answers.length === 0) return;
          onAsk(askWithValues(asked, answers, subject));
        }}
      >
        <p className="t-label mb-2">answer what the record cannot</p>
        <div className="flex flex-col gap-3">
          {missing.map((field) => {
            const id = `${baseId}-${field.field}`;
            return (
              <div key={field.field} className="flex flex-col gap-1">
                <label htmlFor={id} className="t-body text-ink">
                  {fieldPrompt(field)}
                </label>
                {field.reason ? (
                  <p className="t-mono text-ink-3">{field.reason}</p>
                ) : null}
                <input
                  id={id}
                  name={field.field}
                  ref={(el) => {
                    if (el) fieldRefs.current.set(field.field, el);
                    else fieldRefs.current.delete(field.field);
                  }}
                  value={values[field.field] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.field]: event.target.value }))
                  }
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={fieldPlaceholder(field)}
                  className="t-body w-full max-w-[46ch] border border-line-strong bg-sunken px-2.5 py-1.5 text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-accent"
                />
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Submit busy={busy}>ask again with your answer</Submit>
          <span className="t-mono text-ink-3">
            {missing.length === 1 ? "one field" : `${missing.length} fields`} &middot; stated in the
            question, attributed to you
          </span>
        </div>
        <Note>{SUPPLIED_VALUE_LIMIT}</Note>
      </form>
    );
  }

  if (refusal.code === "EXTERNAL_SOURCE_REQUIRED") {
    const blocking = blockingDocuments(refusal, documents);
    const doc = blocking[0];
    if (!doc) return null;
    const lookup = documentLookup(doc);
    const id = `${baseId}-doc`;
    return (
      <div className="border-t border-line px-3 py-3">
        <p className="t-label mb-2">
          supply the document, or go and read it
        </p>
        <form
          className="flex flex-col gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            if (docText.trim() === "") return;
            onAsk(askWithDocumentText(asked, doc, docText));
          }}
        >
          <label htmlFor={id} className="t-body text-ink">
            Paste the applicability text of {documentName(doc)}
          </label>
          <textarea
            id={id}
            rows={3}
            value={docText}
            onChange={(event) => setDocText(event.target.value)}
            spellCheck={false}
            placeholder="&ldquo;This bulletin applies to &hellip;&rdquo;"
            className="t-body w-full resize-y border border-line-strong bg-sunken px-2.5 py-1.5 text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-accent"
          />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Submit busy={busy}>ask again with your text quoted</Submit>
            <a
              href={lookup.href}
              target="_blank"
              rel="noopener noreferrer"
              className="t-label border border-line bg-raised px-3 py-1.5 text-ink-2 transition-colors hover:border-accent hover:text-ink focus-visible:border-accent"
            >
              {lookup.label} &#8599;
            </a>
          </div>
        </form>
        {blocking.length > 1 ? (
          <Note>
            {blocking.length - 1} further document
            {blocking.length === 2 ? "" : "s"} {blocking.length === 2 ? "is" : "are"} also named by
            this decision. The gate is blocked on all of them, so clearing one would not settle it.
          </Note>
        ) : null}
        <Note>{lookup.note}</Note>
        <Note>{SUPPLIED_DOCUMENT_LIMIT}</Note>
      </div>
    );
  }

  if (refusal.code === "OUT_OF_SCOPE" || refusal.code === "NO_EVIDENCE") {
    const id = `${baseId}-rephrase`;
    const scope = refusal.code === "OUT_OF_SCOPE";
    return (
      <form
        className="border-t border-line px-3 py-3"
        onSubmit={(event) => {
          event.preventDefault();
          const next = rephrased.trim();
          if (next === "" || next === asked.trim()) return;
          onAsk({ asked: next, question: next, carried: null, supplied: [] });
        }}
      >
        <p className="t-label mb-2">ask it differently</p>
        <label htmlFor={id} className="t-body mb-1 block text-ink">
          {scope
            ? "Rewrite this as a question about an airworthiness directive — an AD number, a docket, or a tail number and what it must comply with."
            : "Name an AD number or a docket this corpus holds, or narrow the subject."}
        </label>
        <textarea
          id={id}
          rows={2}
          value={rephrased}
          onChange={(event) => setRephrased(event.target.value)}
          spellCheck={false}
          className="t-body w-full resize-y border border-line-strong bg-sunken px-2.5 py-1.5 text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-accent"
        />
        <div className="mt-2">
          <Submit busy={busy}>ask again</Submit>
        </div>
        <Note>
          Your original words are kept above in the thread, so the rewrite is visibly a rewrite.
        </Note>
      </form>
    );
  }

  return null;
}
