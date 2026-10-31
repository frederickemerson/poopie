"""Filesystem layout. One place, so ingest and graph never disagree on a path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "data"
RAW = DATA / "raw"
BUILD = DATA / "build"
FIXTURES = DATA / "fixtures"

FR_XML_CACHE = RAW / "fr_ad"
FR_INDEX_CACHE = RAW / "fr_index"
NPRM_XLSX = RAW / "AD Notice of Proposed Rulemaking (AD NPRM).xlsx"

NODES_JSONL = BUILD / "nodes.jsonl"
EDGES_JSONL = BUILD / "edges.jsonl"
PARAGRAPHS_JSONL = BUILD / "paragraphs.jsonl"

# Sidecars. These carry data the pinned contract has no field for; see
# docs/contract_change_requests.md. They are never validated as nodes.
REVISION_TEXT_JSONL = BUILD / "revision_text.jsonl"
MAKE_RAW_JSON = BUILD / "make_normalization.json"
INGEST_REPORT_JSON = BUILD / "ingest_report.json"


def ensure_dirs() -> None:
    for d in (BUILD, FR_XML_CACHE, FR_INDEX_CACHE):
        d.mkdir(parents=True, exist_ok=True)
