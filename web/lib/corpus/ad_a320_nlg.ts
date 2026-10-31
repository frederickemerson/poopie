/**
 * AD 2026-23-05 - Airbus SAS A318/A319/A320/A321, nose landing gear sliding tube.
 *
 * PROVENANCE: the docket, the NPRM record and the NPRM summary below are real
 * (AD NPRM spreadsheet, docket FAA-2026-8779, 91 FR 52266, published
 * 2026-08-13). No final rule for that docket is in the corpus, so the final-rule
 * paragraph text here is DERIVED - written in Federal Register house style to
 * exercise a serial-number-conditioned applicability. The revision is tagged
 * source "derived" and the UI labels it, so nothing synthesized is ever shown as
 * if it came from the Federal Register.
 */
import { buildRevision } from "./build";
import type { ActionNode, NprmNode } from "../events";

export const NPRM_2026_16566: NprmNode = {
  nprm_id: "2026-16566",
  docket_id: "FAA-2026-8779",
  citation: "Federal Register, Volume 91 Number 155 (Thursday, August 13, 2026)",
  page_range: "(Pages 52266-52268)",
  publish_date: "2026-08-13",
  comments_due_date: "2026-09-28",
  make: "Airbus SAS",
  model_text: "A318 series | A319 series | A320 series | A321 series",
  product_type: "Aircraft",
  summary:
    "This proposed AD was prompted by reports of a certain nose landing gear (NLG) sliding tube " +
    "having widespread overheat damage and multiple cracks on the base metal during shop visits. " +
    "This proposed AD would require a special detailed inspection (SDI) of the affected NLG " +
    "sliding tube and replacement, as applicable. This proposed AD would also prohibit the " +
    "installation of affected parts.",
  comment_url:
    "https://www.federalregister.gov/documents/2026/08/13/2026-16566/airworthiness-directives-airbus-sas-airplanes",
  source: "nprm_spreadsheet",
};

export const MODEL_LIST_A320 =
  "A318-111, A318-112, A318-121, A318-122, A319-111, A319-112, A319-113, A319-114, A319-115, " +
  "A319-131, A319-132, A319-133, A320-211, A320-212, A320-214, A320-216, A320-231, A320-232, " +
  "A320-233, A321-111, A321-112, A321-131, A321-211, A321-212, A321-213, A321-231, and A321-232";

export const SERIAL_RANGE_A320 = "manufacturer serial numbers (MSN) 1000 through 2500 inclusive";

export const REV_2026_23114 = buildRevision(
  {
    revision_id: "2026-23114",
    ad_number: "2026-23-05",
    docket_id: "FAA-2026-8779",
    fr_document_number: "2026-23114",
    amendment: "39-23511",
    publication_date: "2026-12-01",
    effective_on: "2027-01-05",
    full_text_xml_url: null,
    is_current: true,
    superseded_by: null,
    // This revision's paragraph text is DERIVED, so it has no Federal Register
    // citation or page range. Null, never a plausible-looking number: the UI
    // renders it as "not recorded".
    fr_citation: null,
    start_page: null,
    end_page: null,
  },
  [
    {
      label: "a",
      role: "EFFECTIVE_DATE",
      heading: "Effective Date",
      text: "This airworthiness directive (AD) is effective January 5, 2027.",
    },
    { label: "b", role: "AFFECTED_ADS", heading: "Affected ADs", text: "None." },
    {
      label: "c",
      role: "APPLICABILITY",
      heading: "Applicability",
      text:
        `This AD applies to Airbus SAS Model ${MODEL_LIST_A320} airplanes, certificated in any ` +
        `category, ${SERIAL_RANGE_A320}.`,
    },
    {
      label: "d",
      role: "SUBJECT",
      heading: "Subject",
      text: "Air Transport Association (ATA) of America Code 32, Landing gear.",
    },
    {
      label: "e",
      role: "UNSAFE_CONDITION",
      heading: "Unsafe Condition",
      text:
        "This AD was prompted by reports of a certain nose landing gear (NLG) sliding tube having " +
        "widespread overheat damage and multiple cracks on the base metal during shop visits. The " +
        "FAA is issuing this AD to address cracking of the NLG sliding tube, which could result in " +
        "collapse of the NLG and consequent reduced controllability of the airplane on the ground.",
    },
    {
      label: "f",
      role: "COMPLIANCE",
      heading: "Compliance",
      text:
        "Comply with this AD within the compliance times specified, unless already done. Within " +
        "6,000 flight cycles or 36 months after the effective date of this AD, whichever occurs " +
        "first, do the actions required by paragraph (g) of this AD.",
    },
    {
      label: "g",
      role: "REQUIRED_ACTIONS",
      heading: "Required Actions",
      text:
        "At the applicable compliance time specified in paragraph (f) of this AD, do a special " +
        "detailed inspection (SDI) of the affected NLG sliding tube for cracking and overheat " +
        "damage. If any crack or overheat damage is found, before further flight, replace the " +
        "affected NLG sliding tube with a serviceable part.",
    },
    {
      label: "h",
      role: "EXCEPTIONS",
      heading: "Parts Installation Prohibition",
      text:
        "As of the effective date of this AD, no person may install an affected NLG sliding tube " +
        "on any airplane, unless it has passed the special detailed inspection required by " +
        "paragraph (g) of this AD.",
    },
  ],
);

export const ACTION_A320_SDI: ActionNode = {
  action_id: "2026-23114:g:1",
  revision_id: "2026-23114",
  paragraph_id: "2026-23114#g",
  description:
    "Special detailed inspection (SDI) of the affected nose landing gear sliding tube for " +
    "cracking and overheat damage; replace with a serviceable part before further flight if any " +
    "crack or overheat damage is found.",
  compliance_time: "6,000 flight cycles or 36 months after 2027-01-05, whichever occurs first",
  compliance_basis: "FLIGHT_CYCLES",
  source_quote:
    "Within 6,000 flight cycles or 36 months after the effective date of this AD, whichever " +
    "occurs first",
  external_ref: null,
};

export const CITE_A320 = {
  applicability: REV_2026_23114.cite("c", "This AD applies to Airbus SAS Model A318-111"),
  models: REV_2026_23114.cite("c", MODEL_LIST_A320),
  serials: REV_2026_23114.cite("c", SERIAL_RANGE_A320),
  category: REV_2026_23114.cite("c", "certificated in any category"),
  effective: REV_2026_23114.cite("a", "effective January 5, 2027"),
  compliance: REV_2026_23114.cite("f", ACTION_A320_SDI.source_quote),
  action: REV_2026_23114.cite(
    "g",
    "do a special detailed inspection (SDI) of the affected NLG sliding tube for cracking and overheat damage",
  ),
  replace: REV_2026_23114.cite(
    "g",
    "before further flight, replace the affected NLG sliding tube with a serviceable part",
  ),
  prohibition: REV_2026_23114.cite("h", "no person may install an affected NLG sliding tube"),
  unsafe: REV_2026_23114.cite("e", "collapse of the NLG and consequent reduced controllability"),
} as const;
