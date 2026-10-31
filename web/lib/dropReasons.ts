/**
 * Plain English for the verifier's drop codes.
 *
 * The codes are the engine's own stable vocabulary (engine/verify/verifier.py).
 * They are always shown verbatim next to the sentence that was dropped; this
 * table only adds the explanation, and an unrecognised code falls through to the
 * code itself rather than to a vague apology.
 */
export const DROP_REASON_TEXT: Readonly<Record<string, string>> = {
  sentence_carries_no_citation: "the writer offered no quote for this sentence at all",
  numeric_term_absent_from_cited_span:
    "a number or identifier in the sentence does not appear inside the span it cited",
  term_coverage_below_threshold:
    "too little of the sentence's wording is carried by the span it cited",
  citation_not_in_retrieved_set:
    "the cited paragraph was not in the set retrieved for this question",
  span_not_verbatim_in_paragraph: "the cited span is not a character-for-character substring",
  span_outside_paragraph: "the cited offsets fall outside the paragraph they name",
  citation_unparseable: "the citation id does not match the contract's citation format",
  dropped_by_the_verifier: "the verifier rejected this sentence",
};

export function describeDropReason(code: string): string | null {
  return DROP_REASON_TEXT[code] ?? null;
}
