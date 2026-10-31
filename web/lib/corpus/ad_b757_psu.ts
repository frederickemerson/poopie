/**
 * AD 2026-21-12 - The Boeing Company Model 757-200 and -300. Applicability is
 * conditioned on installed equipment, which the OpenSky fleet record does not
 * carry: this is the AD that makes amber cells unavoidable rather than sloppy.
 *
 * Paragraph text is verbatim from the Federal Register final rule
 * (data/fixtures/ad_boeing_757_psu.xml, FR Doc. 2026-21864).
 */
import { buildRevision } from "./build";
import { EXTERNAL_DOCUMENT_BASIS, type ActionNode, type ServiceBulletinNode } from "../events";

export const BOEING_RB_757_25_0320: ServiceBulletinNode = {
  sb_id: "BOEING:757-25-0320-RB",
  manufacturer: "The Boeing Company",
  number: "757-25-0320 RB",
  revision: "Revision 1",
  dated: "2025-08-06",
  held: false,
};

export const REV_2026_21864 = buildRevision(
  {
    revision_id: "2026-21864",
    ad_number: "2026-21-12",
    docket_id: "FAA-2025-0003",
    fr_document_number: "2026-21864",
    amendment: "39-23501",
    publication_date: "2026-10-27",
    effective_on: "2026-12-01",
    full_text_xml_url:
      "https://www.federalregister.gov/documents/full_text/xml/2026/10/27/2026-21864.xml",
    is_current: true,
    superseded_by: null,
  },
  [
    {
      label: "a",
      role: "EFFECTIVE_DATE",
      heading: "Effective Date",
      text: "This airworthiness directive (AD) is effective December 1, 2026.",
    },
    { label: "b", role: "AFFECTED_ADS", heading: "Affected ADs", text: "None." },
    {
      label: "c",
      role: "APPLICABILITY",
      heading: "Applicability",
      text:
        "This AD applies to The Boeing Company Model 757-200 and -300 series airplanes, " +
        "certificated in any category, equipped with passenger service unit (PSU)-mounted video " +
        "monitors.",
    },
    {
      label: "d",
      role: "SUBJECT",
      heading: "Subject",
      text: "Air Transport Association (ATA) of America Code 25, Equipment/furnishings.",
    },
    {
      label: "e",
      role: "UNSAFE_CONDITION",
      heading: "Unsafe Condition",
      text:
        "This AD was prompted by a report that some PSU-mounted video monitors became detached " +
        "from the PSU rails during a hard landing that did not exceed the emergency load " +
        "requirements for the PSUs. The FAA is issuing this AD to address PSU-mounted video " +
        "monitors that could become fully detached or be held at an unsafe height, which, if not " +
        "addressed, could result in injury to passengers and impede passenger and crew egress " +
        "during emergency evacuation.",
    },
    {
      label: "f",
      role: "COMPLIANCE",
      heading: "Compliance",
      text: "Comply with this AD within the compliance times specified, unless already done.",
    },
    {
      label: "g",
      role: "REQUIRED_ACTIONS",
      heading: "Required Actions",
      text:
        "(1) For airplanes identified in Boeing Special Attention Requirements Bulletin " +
        "757-25-0320 RB, Revision 1, dated August 6, 2025: Except as specified by paragraph (h) " +
        "of this AD, at the applicable times specified in the “Compliance” paragraph of " +
        "Boeing Special Attention Requirements Bulletin 757-25-0320 RB, Revision 1, dated " +
        "August 6, 2025, do all applicable actions identified in, and in accordance with, the " +
        "Accomplishment Instructions of Boeing Special Attention Requirements Bulletin " +
        "757-25-0320 RB, Revision 1, dated August 6, 2025.",
    },
  ],
);

export const ACTION_757_PSU: ActionNode = {
  action_id: "2026-21864:g:1",
  revision_id: "2026-21864",
  paragraph_id: "2026-21864#g",
  description:
    "Replace PSU-mounted video monitors that do not have secondary retention lanyards, per the " +
    "Accomplishment Instructions of Boeing Special Attention Requirements Bulletin 757-25-0320 RB.",
  compliance_time: "At the applicable times specified in the Compliance paragraph of the bulletin",
  compliance_basis: EXTERNAL_DOCUMENT_BASIS,
  source_quote:
    "at the applicable times specified in the “Compliance” paragraph of Boeing Special " +
    "Attention Requirements Bulletin 757-25-0320 RB, Revision 1, dated August 6, 2025",
  external_ref: BOEING_RB_757_25_0320.sb_id,
};

export const CITE_B757 = {
  applicability: REV_2026_21864.cite(
    "c",
    "This AD applies to The Boeing Company Model 757-200 and -300 series airplanes",
  ),
  equipment: REV_2026_21864.cite("c", "equipped with passenger service unit (PSU)-mounted video monitors"),
  effective: REV_2026_21864.cite("a", "effective December 1, 2026"),
  unsafe: REV_2026_21864.cite("e", "became detached from the PSU rails during a hard landing"),
  action: REV_2026_21864.cite("g", ACTION_757_PSU.source_quote),
} as const;
