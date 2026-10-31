"""Filesystem layout. One place, so ingest and graph never disagree on a path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "data"
RAW = DATA / "raw"
BUILD = DATA / "build"
FIXTURES = DATA / "fixtures"

FR_XML_CACHE = RAW / "fr_ad"
#: Proposals are cached apart from adopted rules, so a provenance sweep over
#: the citable corpus can never pick up a proposal by accident.
FR_NPRM_XML_CACHE = RAW / "fr_nprm"
FR_INDEX_CACHE = RAW / "fr_index"
NPRM_XLSX = RAW / "AD Notice of Proposed Rulemaking (AD NPRM).xlsx"
#: The challenge organizers' index: the same 431 proposals with a stable
#: record_id per row. Read by engine.ingest.nprm_index_xlsx.
NPRM_INDEX_XLSX = DATA / "reference" / "challenge-4-ad-index.xlsx"

NODES_JSONL = BUILD / "nodes.jsonl"
EDGES_JSONL = BUILD / "edges.jsonl"
#: Citable, obligation-bearing paragraphs: Revision paragraphs only. The rules
#: extractor reads this file, so a proposal must not be in it.
PARAGRAPHS_JSONL = BUILD / "paragraphs.jsonl"
#: PROPOSED paragraphs, in their own file. Separation is the guarantee: a
#: consumer that only knows about paragraphs.jsonl cannot reach a proposal.
NPRM_PARAGRAPHS_JSONL = BUILD / "nprm_paragraphs.jsonl"

# Sidecars. These carry data the pinned contract has no field for; see
# docs/contract_change_requests.md. They are never validated as nodes.
REVISION_TEXT_JSONL = BUILD / "revision_text.jsonl"
NPRM_TEXT_JSONL = BUILD / "nprm_text.jsonl"
NPRM_PROVENANCE_JSONL = BUILD / "provenance_nprm.jsonl"
MAKE_RAW_JSON = BUILD / "make_normalization.json"
INGEST_REPORT_JSON = BUILD / "ingest_report.json"


def ensure_dirs() -> None:
    for d in (BUILD, FR_XML_CACHE, FR_NPRM_XML_CACHE, FR_INDEX_CACHE):
        d.mkdir(parents=True, exist_ok=True)
