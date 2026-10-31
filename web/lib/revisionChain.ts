/**
 * The supersession chain and the applicability diff between two revisions.
 * An NPRM is part of the chain: a proposal node precedes the final rule it
 * became, joined through the shared docket (the contract's PROPOSED_BY edge).
 */
import type { RuleField, Source } from "./contract";
import type { AdEntry, RevisionEntry } from "./corpus";

export type ChainNodeKind = "proposal" | "final";

export interface ChainNode {
  readonly id: string;
  readonly kind: ChainNodeKind;
  readonly title: string;
  readonly date: string;
  readonly docket_id: string;
  readonly revision_id: string | null;
  readonly amendment: string | null;
  readonly effective_on: string | null;
  readonly comments_due_date: string | null;
  readonly citation: string | null;
  readonly url: string | null;
  readonly is_current: boolean;
  readonly superseded: boolean;
  readonly text_source: Source | null;
}

export function buildChain(ad: AdEntry): readonly ChainNode[] {
  const nodes: ChainNode[] = [];
  for (const entry of ad.revisions) {
    const rev = entry.built.revision;
    if (entry.nprm) {
      nodes.push({
        id: `nprm:${entry.nprm.nprm_id}`,
        kind: "proposal",
        title: `NPRM ${entry.nprm.nprm_id}`,
        date: entry.nprm.publish_date,
        docket_id: entry.nprm.docket_id,
        revision_id: null,
        amendment: null,
        effective_on: null,
        comments_due_date: entry.nprm.comments_due_date,
        citation: entry.nprm.citation,
        url: entry.nprm.comment_url,
        is_current: false,
        superseded: false,
        text_source: entry.nprm.source,
      });
    }
    nodes.push({
      id: `rev:${rev.revision_id}`,
      kind: "final",
      title: `AD ${rev.ad_number}`,
      date: rev.publication_date,
      docket_id: rev.docket_id,
      revision_id: rev.revision_id,
      amendment: rev.amendment,
      effective_on: rev.effective_on,
      comments_due_date: null,
      citation: null,
      url: rev.full_text_xml_url,
      is_current: rev.is_current,
      superseded: rev.superseded_by !== null,
      text_source: entry.text_source,
    });
  }
  return nodes;
}

export type ChangeKind = "added" | "removed" | "changed" | "same";

export interface RuleDiffRow {
  readonly field: RuleField;
  readonly before: string | null;
  readonly after: string | null;
  readonly change: ChangeKind;
}

export interface ApplicabilityDiff {
  readonly rows: readonly RuleDiffRow[];
  readonly before_text: string | null;
  readonly after_text: string;
  readonly before_label: string | null;
  readonly after_label: string;
}

const applicabilityText = (entry: RevisionEntry): string => {
  const para = entry.built.paragraphs.find((p) => p.role === "APPLICABILITY");
  return para?.text ?? "";
};

/** What changed in applicability, taken from the Rule nodes rather than prose. */
export function diffApplicability(before: RevisionEntry | null, after: RevisionEntry): ApplicabilityDiff {
  const fields = new Set<RuleField>();
  for (const r of before?.rules ?? []) fields.add(r.field);
  for (const r of after.rules) fields.add(r.field);

  const describe = (entry: RevisionEntry | null, field: RuleField): string | null => {
    const r = entry?.rules.find((x) => x.field === field);
    return r ? `${r.operator} ${r.value}` : null;
  };

  const rows: RuleDiffRow[] = [...fields].map((field) => {
    const b = describe(before, field);
    const a = describe(after, field);
    const change: ChangeKind =
      b === a ? "same" : b === null ? "added" : a === null ? "removed" : "changed";
    return { field, before: b, after: a, change };
  });

  return {
    rows,
    before_text: before ? applicabilityText(before) : null,
    after_text: applicabilityText(after),
    before_label: before ? `AD ${before.built.revision.ad_number}` : null,
    after_label: `AD ${after.built.revision.ad_number}`,
  };
}
