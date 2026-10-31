/**
 * AD 2026-22-02 - Airbus SAS Model A330-941. Applicability is delegated to EASA
 * AD 2025-0208, a document this corpus does not hold.
 *
 * Paragraph text is verbatim from the Federal Register final rule
 * (data/fixtures/ad_airbus_a330_easa_delegated.xml, FR Doc. 2026-21861).
 * The NPRM record is verbatim from the AD NPRM spreadsheet, docket FAA-2026-8782.
 */
import { buildRevision } from "./build";
import type { ForeignAdNode, NprmNode } from "../events";

export const EASA_AD_2025_0208: ForeignAdNode = {
  foreign_ad_id: "EASA:2025-0208",
  authority: "EASA",
  ad_number: "2025-0208",
  dated: "2025-09-24",
  held: false,
};

export const NPRM_2026_16874: NprmNode = {
  nprm_id: "2026-16874",
  docket_id: "FAA-2026-8782",
  citation: "Federal Register, Volume 91 Number 159 (Wednesday, August 19, 2026)",
  page_range: "(Pages 53542-53545)",
  publish_date: "2026-08-19",
  comments_due_date: "2026-10-05",
  make: "Airbus SAS",
  model_text: "A330-941",
  product_type: "Aircraft",
  summary:
    "The FAA proposes to adopt a new airworthiness directive (AD) for certain Airbus SAS Model " +
    "A330-941 airplanes. This proposed AD was prompted by an occurrence of a triple \"PRIM FAULT\" " +
    "in the Flight Control Primary Computer (FCPC) at touchdown. This proposed AD would require " +
    "the installation of a new FCPC standard and applicable concurrent modifications.",
  comment_url:
    "https://www.federalregister.gov/documents/2026/08/19/2026-16874/airworthiness-directives-airbus-sas-airplanes",
  source: "nprm_spreadsheet",
};

export const REV_2026_21861 = buildRevision(
  {
    revision_id: "2026-21861",
    ad_number: "2026-22-02",
    docket_id: "FAA-2026-8782",
    fr_document_number: "2026-21861",
    amendment: "39-23504",
    publication_date: "2026-10-27",
    effective_on: "2026-12-01",
    full_text_xml_url:
      "https://www.federalregister.gov/documents/full_text/xml/2026/10/27/2026-21861.xml",
    is_current: true,
    superseded_by: null,
    // Real: Federal Register index for document 2026-21861.
    fr_citation: "91 FR 67455",
    start_page: 67455,
    end_page: 67457,
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
        "This AD applies to Airbus SAS Model A330-941 airplanes, certificated in any category, " +
        "as identified in European Union Aviation Safety Agency (EASA) AD 2025-0208, dated " +
        "September 24, 2025 (EASA AD 2025-0208).",
    },
    {
      label: "d",
      role: "SUBJECT",
      heading: "Subject",
      text: "Air Transport Association (ATA) of America Code 27, Flight controls.",
    },
    {
      label: "e",
      role: "UNSAFE_CONDITION",
      heading: "Unsafe Condition",
      text:
        "This AD was prompted by an occurrence of a triple “PRIM FAULT” at touchdown, " +
        "leading to loss of ground spoilers, thrust reversers, and autobrake. The FAA is issuing " +
        "this AD to update the Flight Control Primary Computer (FCPC) standard, which if not " +
        "addressed, could result in the loss of autobrake and thrust reversers, possibly resulting " +
        "in reduced control of the airplane.",
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
      heading: "Requirements",
      text:
        "Except as specified in paragraph (h) of this AD: Comply with all required actions and " +
        "compliance times specified in, and in accordance with, EASA AD 2025-0208.",
    },
    {
      label: "h",
      role: "EXCEPTIONS",
      heading: "Exceptions to EASA AD 2025-0208",
      text:
        "(1) Where EASA AD 2025-0208 refers to its effective date, this AD requires using the " +
        "effective date of this AD. (2) This AD does not adopt the “Remarks” section of " +
        "EASA AD 2025-0208.",
    },
    {
      label: "k",
      role: "IBR",
      heading: "Material Incorporated by Reference",
      text:
        "(1) The Director of the Federal Register approved the incorporation by reference of the " +
        "material listed in this paragraph under 5 U.S.C. 552(a) and 1 CFR part 51. (2) You must " +
        "use this material as applicable to do the actions required by this AD, unless this AD " +
        "specifies otherwise. (i) European Union Aviation Safety Agency (EASA) AD 2025-0208, " +
        "dated September 24, 2025.",
    },
  ],
);

/** The clause that hands applicability to a document we do not hold. */
export const DELEGATION_QUOTE =
  "as identified in European Union Aviation Safety Agency (EASA) AD 2025-0208, dated " +
  "September 24, 2025";

export const CITE_A330 = {
  applicability: REV_2026_21861.cite("c", "This AD applies to Airbus SAS Model A330-941 airplanes"),
  delegation: REV_2026_21861.cite("c", DELEGATION_QUOTE),
  effective: REV_2026_21861.cite("a", "effective December 1, 2026"),
  requirements: REV_2026_21861.cite(
    "g",
    "Comply with all required actions and compliance times specified in, and in accordance with, EASA AD 2025-0208.",
  ),
  ibr: REV_2026_21861.cite(
    "k",
    "European Union Aviation Safety Agency (EASA) AD 2025-0208, dated September 24, 2025.",
  ),
  unsafe: REV_2026_21861.cite("e", "loss of ground spoilers, thrust reversers, and autobrake"),
} as const;
