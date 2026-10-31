/**
 * The AD registry. Four airworthiness directives, their revisions, their
 * applicability Rules and their supersession chains. Rule node fields and
 * operators are the contract's enums.rule_field and enums.rule_operator; every
 * source_quote is proved verbatim by buildRevision().cite() at module load.
 */
import type { RuleField, RuleOperator, Source } from "../contract";
import type { ForeignAdNode, NprmNode, ParagraphNode, RevisionNode, ServiceBulletinNode } from "../events";
import type { BuiltRevision } from "./build";
import { CITE_A320, NPRM_2026_16566, REV_2026_23114, ACTION_A320_SDI, MODEL_LIST_A320, SERIAL_RANGE_A320 } from "./ad_a320_nlg";
import { ACTION_757_PSU, BOEING_RB_757_25_0320, CITE_B757, REV_2026_21864 } from "./ad_b757_psu";
import { CITE_A330, EASA_AD_2025_0208, NPRM_2026_16874, REV_2026_21861 } from "./ad_a330_fcpc";
import { CITE_A330_RMP, NPRM_2026_21334, REV_2025_07990, REV_2026_22390 } from "./ad_a330_rmp";

export interface RuleNode {
  readonly rule_id: string;
  readonly revision_id: string;
  readonly paragraph_id: string;
  readonly field: RuleField;
  readonly operator: RuleOperator;
  /** As written. Lists are comma separated; ranges are "lo-hi". */
  readonly value: string;
  readonly source_quote: string;
  readonly confidence: number;
  readonly unparsed_reason: string | null;
  /** Citation for the exact span the rule was extracted from. */
  readonly citation_id: string;
}

export interface RevisionEntry {
  readonly built: BuiltRevision;
  readonly rules: readonly RuleNode[];
  /** federal_register = verbatim text; derived = written in FR house style. */
  readonly text_source: Source;
  /** A ForeignAD this revision adopts. held=false blocks applicability. */
  readonly adopts_mcai?: ForeignAdNode;
  readonly references_sb?: ServiceBulletinNode;
  readonly nprm?: NprmNode;
  readonly summary: string;
}

export interface AdEntry {
  readonly ad_number: string;
  readonly docket_id: string;
  readonly title: string;
  readonly make: string;
  readonly subject: string;
  /** Oldest first. The last entry is the current revision. */
  readonly revisions: readonly RevisionEntry[];
}

const rule = (
  built: BuiltRevision,
  n: number,
  label: string,
  field: RuleField,
  operator: RuleOperator,
  value: string,
  source_quote: string,
  citation_id: string,
  confidence = 1,
): RuleNode => {
  const paragraph = built.paragraph(label);
  if (!paragraph.text.includes(source_quote)) {
    throw new Error(`${paragraph.paragraph_id}: rule r${n} source_quote is not verbatim`);
  }
  return {
    rule_id: `${built.revision.revision_id}:r${n}`,
    revision_id: built.revision.revision_id,
    paragraph_id: paragraph.paragraph_id,
    field,
    operator,
    value,
    source_quote,
    confidence,
    unparsed_reason: null,
    citation_id,
  };
};

export const AD_A320_NLG: AdEntry = {
  ad_number: "2026-23-05",
  docket_id: "FAA-2026-8779",
  title: "Nose landing gear sliding tube - special detailed inspection",
  make: "Airbus SAS",
  subject: "ATA 32, Landing gear",
  revisions: [
    {
      built: REV_2026_23114,
      text_source: "derived",
      nprm: NPRM_2026_16566,
      summary: ACTION_A320_SDI.description,
      rules: [
        rule(REV_2026_23114, 1, "c", "manufacturer", "in", "Airbus SAS", "This AD applies to Airbus SAS Model", CITE_A320.applicability),
        rule(REV_2026_23114, 2, "c", "model", "model_matches", MODEL_LIST_A320, MODEL_LIST_A320, CITE_A320.models),
        rule(REV_2026_23114, 3, "c", "serial_number", "serial_in_range", "1000-2500", SERIAL_RANGE_A320, CITE_A320.serials),
      ],
    },
  ],
};

export const AD_B757_PSU: AdEntry = {
  ad_number: "2026-21-12",
  docket_id: "FAA-2025-0003",
  title: "PSU-mounted video monitors - secondary retention",
  make: "The Boeing Company",
  subject: "ATA 25, Equipment/furnishings",
  revisions: [
    {
      built: REV_2026_21864,
      text_source: "federal_register",
      references_sb: BOEING_RB_757_25_0320,
      summary: ACTION_757_PSU.description,
      rules: [
        rule(REV_2026_21864, 1, "c", "manufacturer", "in", "The Boeing Company", "This AD applies to The Boeing Company Model", CITE_B757.applicability),
        rule(REV_2026_21864, 2, "c", "model", "model_matches", "757-200 series, 757-300 series", "Model 757-200 and -300 series airplanes", CITE_B757.applicability),
        rule(REV_2026_21864, 3, "c", "equipment", "exists", "passenger service unit (PSU)-mounted video monitors", "equipped with passenger service unit (PSU)-mounted video monitors", CITE_B757.equipment),
      ],
    },
  ],
};

export const AD_A330_FCPC: AdEntry = {
  ad_number: "2026-22-02",
  docket_id: "FAA-2026-8782",
  title: "Flight Control Primary Computer standard - MCAI adoption",
  make: "Airbus SAS",
  subject: "ATA 27, Flight controls",
  revisions: [
    {
      built: REV_2026_21861,
      text_source: "federal_register",
      adopts_mcai: EASA_AD_2025_0208,
      nprm: NPRM_2026_16874,
      summary:
        "Install a new FCPC standard and the applicable concurrent modifications, and observe the " +
        "parts installation prohibition, all as specified in EASA AD 2025-0208.",
      rules: [
        rule(REV_2026_21861, 1, "c", "manufacturer", "in", "Airbus SAS", "This AD applies to Airbus SAS Model", CITE_A330.applicability),
        rule(REV_2026_21861, 2, "c", "model", "model_matches", "A330-941", "Airbus SAS Model A330-941 airplanes", CITE_A330.applicability),
      ],
    },
  ],
};

export const AD_A330_RMP: AdEntry = {
  ad_number: "2026-23-01",
  docket_id: "FAA-2026-11813",
  title: "Radio management panel data synchronisation",
  make: "Airbus SAS",
  subject: "ATA 23, Communications",
  revisions: [
    {
      built: REV_2025_07990,
      text_source: "derived",
      summary:
        "Revise the AFM to address dual loss of RMP data synchronisation and remove MEL relief " +
        "for an inoperative RMP 3.",
      rules: [
        rule(REV_2025_07990, 1, "c", "manufacturer", "in", "Airbus SAS", "This AD applies to Airbus SAS Model", CITE_A330_RMP.old_applicability),
        rule(REV_2025_07990, 2, "c", "model", "model_matches", "A330-243, A330-243F, A330-841, A330-941", "Model A330-243, A330-243F, A330-841, and A330-941 airplanes", CITE_A330_RMP.old_applicability),
        rule(REV_2025_07990, 3, "c", "serial_number", "exists", "all manufacturer serial numbers", "all manufacturer serial numbers", CITE_A330_RMP.old_all_serials),
      ],
    },
    {
      built: REV_2026_22390,
      text_source: "derived",
      nprm: NPRM_2026_21334,
      summary:
        "Retain the AFM and MEL revisions required by AD 2025-09-07 and modify the airplane by " +
        "installing the RMP data synchronisation modification.",
      rules: [
        rule(REV_2026_22390, 1, "c", "manufacturer", "in", "Airbus SAS", "This AD applies to Airbus SAS Model", CITE_A330_RMP.new_applicability),
        rule(REV_2026_22390, 2, "c", "model", "model_matches", "A330-941", "Airbus SAS Model A330-941 airplanes", CITE_A330_RMP.new_applicability),
        rule(REV_2026_22390, 3, "c", "serial_number", "serial_in_range", "1900-1960", "manufacturer serial numbers (MSN) 1900 through 1960 inclusive", CITE_A330_RMP.new_serials),
      ],
    },
  ],
};

export const ADS: readonly AdEntry[] = [AD_A320_NLG, AD_B757_PSU, AD_A330_FCPC, AD_A330_RMP];

const REVISION_INDEX = new Map<string, { ad: AdEntry; entry: RevisionEntry }>();
for (const ad of ADS) {
  for (const entry of ad.revisions) {
    REVISION_INDEX.set(entry.built.revision.revision_id, { ad, entry });
  }
}

export function revisionEntry(revisionId: string): { ad: AdEntry; entry: RevisionEntry } | undefined {
  return REVISION_INDEX.get(revisionId);
}

/** An AD by its own number or by the number any of its revisions carried. */
export function findAd(adNumber: string | null): AdEntry | null {
  if (!adNumber) return null;
  const direct = ADS.find((a) => a.ad_number === adNumber);
  if (direct) return direct;
  return (
    ADS.find((a) => a.revisions.some((r) => r.built.revision.ad_number === adNumber)) ?? null
  );
}

/** The revision that carried a given AD number, within an AD's chain. */
export function revisionForAdNumber(ad: AdEntry, adNumber: string | null): RevisionEntry | null {
  if (!adNumber) return null;
  return ad.revisions.find((r) => r.built.revision.ad_number === adNumber) ?? null;
}

export function currentRevision(ad: AdEntry): RevisionEntry {
  const last = ad.revisions[ad.revisions.length - 1];
  if (!last) throw new Error(`${ad.ad_number} has no revisions`);
  return last;
}

export function revisionNodes(revisionId: string): readonly RevisionNode[] {
  const found = revisionEntry(revisionId);
  return found ? [found.entry.built.revision] : [];
}

export function paragraphsOf(revisionId: string): readonly ParagraphNode[] {
  return revisionEntry(revisionId)?.entry.built.paragraphs ?? [];
}

export {
  ACTION_757_PSU,
  ACTION_A320_SDI,
  BOEING_RB_757_25_0320,
  CITE_A320,
  CITE_A330,
  CITE_A330_RMP,
  CITE_B757,
  EASA_AD_2025_0208,
  REV_2025_07990,
  REV_2026_21861,
  REV_2026_21864,
  REV_2026_22390,
  REV_2026_23114,
};
