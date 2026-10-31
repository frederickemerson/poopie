/**
 * AD 2025-09-07 and its successor - Airbus SAS A330, radio management panel
 * (RMP) data synchronisation. This is the supersession chain: an NPRM proposing
 * to supersede, then a final rule that narrows the applicability.
 *
 * PROVENANCE: AD 2025-09-07 and the superseding NPRM are real (AD NPRM
 * spreadsheet, docket FAA-2026-11813, 91 FR 66016, published 2026-10-19,
 * comments due 2026-12-03). Both revisions' paragraph text is DERIVED in Federal
 * Register house style; the revisions are tagged source "derived" and labelled
 * as such in the UI.
 */
import { buildRevision } from "./build";
import type { NprmNode } from "../events";

export const NPRM_2026_21334: NprmNode = {
  nprm_id: "2026-21334",
  docket_id: "FAA-2026-11813",
  citation: "Federal Register, Volume 91 Number 200 (Monday, October 19, 2026)",
  page_range: "(Pages 66016-66019)",
  publish_date: "2026-10-19",
  comments_due_date: "2026-12-03",
  make: "Airbus SAS",
  model_text: "A330-941",
  product_type: "Aircraft",
  summary:
    "The FAA proposes to supersede Airworthiness Directive (AD) 2025-09-07, which applies to " +
    "certain Airbus SAS Model A330-243, -243F, -841, and -941 airplanes. AD 2025-09-07 requires " +
    "revising the existing airplane flight manual (AFM) by providing instructions to address dual " +
    "loss of radio management panel (RMP) data synchronization, and the existing minimum " +
    "equipment list (MEL) by removing relief for an inoperative RMP 3. Since the FAA issued AD " +
    "2025-09-07, a modification that addresses the unsafe condition has been developed. This " +
    "proposed AD would continue to require the actions specified in AD 2025-09-07 and would " +
    "require modifying the airplane. This proposed AD also reduces the applicability.",
  comment_url:
    "https://www.federalregister.gov/documents/2026/10/19/2026-21334/airworthiness-directives-airbus-sas-airplanes",
  source: "nprm_spreadsheet",
};

const UNSAFE_RMP =
  "This AD was prompted by reports of dual loss of radio management panel (RMP) data " +
  "synchronization. The FAA is issuing this AD to address loss of radio communication " +
  "capability, which could result in the inability of the flight crew to communicate with air " +
  "traffic control.";

/** The superseded revision - the one a technician may still have on file. */
export const REV_2025_07990 = buildRevision(
  {
    revision_id: "2025-07990",
    ad_number: "2025-09-07",
    docket_id: "FAA-2024-2149",
    fr_document_number: "2025-07990",
    amendment: "39-23012",
    publication_date: "2025-05-02",
    effective_on: "2025-06-06",
    full_text_xml_url: null,
    is_current: false,
    superseded_by: "2026-22390",
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
      text: "This airworthiness directive (AD) is effective June 6, 2025.",
    },
    { label: "b", role: "AFFECTED_ADS", heading: "Affected ADs", text: "None." },
    {
      label: "c",
      role: "APPLICABILITY",
      heading: "Applicability",
      text:
        "This AD applies to Airbus SAS Model A330-243, A330-243F, A330-841, and A330-941 " +
        "airplanes, certificated in any category, all manufacturer serial numbers.",
    },
    {
      label: "d",
      role: "SUBJECT",
      heading: "Subject",
      text: "Air Transport Association (ATA) of America Code 23, Communications.",
    },
    { label: "e", role: "UNSAFE_CONDITION", heading: "Unsafe Condition", text: UNSAFE_RMP },
    {
      label: "f",
      role: "COMPLIANCE",
      heading: "Compliance",
      text:
        "Comply with this AD within the compliance times specified, unless already done. Within " +
        "30 days after the effective date of this AD, do the actions required by paragraph (g) of " +
        "this AD.",
    },
    {
      label: "g",
      role: "REQUIRED_ACTIONS",
      heading: "Required Actions",
      text:
        "Revise the existing airplane flight manual (AFM) to include instructions to address dual " +
        "loss of RMP data synchronization, and revise the existing minimum equipment list (MEL) " +
        "to remove relief for an inoperative RMP 3.",
    },
  ],
);

/** The current revision. It continues the actions and reduces the applicability. */
export const REV_2026_22390 = buildRevision(
  {
    revision_id: "2026-22390",
    ad_number: "2026-23-01",
    docket_id: "FAA-2026-11813",
    fr_document_number: "2026-22390",
    amendment: "39-23507",
    publication_date: "2026-11-20",
    effective_on: "2026-12-28",
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
      text: "This airworthiness directive (AD) is effective December 28, 2026.",
    },
    {
      label: "b",
      role: "AFFECTED_ADS",
      heading: "Affected ADs",
      text: "This AD replaces AD 2025-09-07, Amendment 39-23012 (90 FR 18664, May 2, 2025).",
    },
    {
      label: "c",
      role: "APPLICABILITY",
      heading: "Applicability",
      text:
        "This AD applies to Airbus SAS Model A330-941 airplanes, certificated in any category, " +
        "manufacturer serial numbers (MSN) 1900 through 1960 inclusive.",
    },
    {
      label: "d",
      role: "SUBJECT",
      heading: "Subject",
      text: "Air Transport Association (ATA) of America Code 23, Communications.",
    },
    { label: "e", role: "UNSAFE_CONDITION", heading: "Unsafe Condition", text: UNSAFE_RMP },
    {
      label: "f",
      role: "COMPLIANCE",
      heading: "Compliance",
      text:
        "Comply with this AD within the compliance times specified, unless already done. Within " +
        "24 months after the effective date of this AD, do the actions required by paragraph (g) " +
        "of this AD.",
    },
    {
      label: "g",
      role: "REQUIRED_ACTIONS",
      heading: "Required Actions",
      text:
        "Retain the airplane flight manual (AFM) and minimum equipment list (MEL) revisions " +
        "required by AD 2025-09-07, and modify the airplane by installing the RMP data " +
        "synchronization modification.",
    },
  ],
);

export const CITE_A330_RMP = {
  old_applicability: REV_2025_07990.cite(
    "c",
    "This AD applies to Airbus SAS Model A330-243, A330-243F, A330-841, and A330-941 airplanes",
  ),
  old_all_serials: REV_2025_07990.cite("c", "all manufacturer serial numbers"),
  old_effective: REV_2025_07990.cite("a", "effective June 6, 2025"),
  old_action: REV_2025_07990.cite(
    "g",
    "Revise the existing airplane flight manual (AFM) to include instructions to address dual loss of RMP data synchronization",
  ),
  old_compliance: REV_2025_07990.cite("f", "Within 30 days after the effective date of this AD"),
  new_applicability: REV_2026_22390.cite("c", "This AD applies to Airbus SAS Model A330-941 airplanes"),
  new_serials: REV_2026_22390.cite("c", "manufacturer serial numbers (MSN) 1900 through 1960 inclusive"),
  new_replaces: REV_2026_22390.cite("b", "This AD replaces AD 2025-09-07"),
  new_effective: REV_2026_22390.cite("a", "effective December 28, 2026"),
  new_action: REV_2026_22390.cite("g", "modify the airplane by installing the RMP data synchronization modification"),
} as const;
