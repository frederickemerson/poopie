"""Parse the Federal Register ``docket_ids`` structured list.

``docket_ids`` is the authoritative source for docket number, part-39 amendment
and AD number. The prose body of the rule is never consulted for these three
facts: it restates them in free text and restates them inconsistently.

Shapes observed across every FAA final rule in the cached index (2,166 documents
at the time of writing, and growing as the harvest runs -- so the counts here
are deliberately not pinned past the one that matters, which is that each shape
below occurred at least once and drove a branch). Recount any time with::

    python3 -m engine.ingest.docket_ids --survey

Every one of these is real::

    ["Docket No. FAA-2026-2723", "Project Identifier AD-2024-00429-A",
     "Amendment 39-23502", "AD 2026-21-13"]      # the common case, ~99% of docs
    "Docket No.: FAA-2021-0419"                  # colon after No.
    "Docket FAA-2023-2234"                       # no "No."
    "Docket No. FAA-2022-0992 Project Identifier MCAI-2022-00173-R"  # two facts, one entry
    "Amendment 39-21656 AD 2021-15-09"           # amendment and AD in one entry
    "Amendment 39-21749-"                        # trailing dash
    "AD 2021-03-16R1"                            # revision suffix, no space
    "AD 92-02-14 R1"                             # two-digit year, spaced suffix
    "AD-2025-05-15"                              # hyphen instead of space
    "2026-08-11"                                 # bare AD number, no "AD" token
    "Docket No. 2002-NM-352-AD"                  # legacy directorate docket
    "Amdt. Nos. 11-64, 21-105, 43-51, 107-8"     # not an AD at all -> no ad_number

Because entries are not positional and sometimes carry two facts, each pattern is
searched for inside the relevant entries rather than full-matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Modern docket, e.g. FAA-2026-8782.
_FAA_DOCKET = re.compile(r"\b(FAA[- ]\d{4}-\d{3,5})")
#: Legacy directorate docket, e.g. 2002-NM-352-AD, 90-CE-35-AD, 2000-SW-38-AD-W,
#: and the one occurrence that omits the -AD suffix entirely ("99-NE-46").
_LEGACY_DOCKET = re.compile(r"\b(\d{2,4}-[A-Z]{2,4}-\d{1,4}(?:-AD(?:-W)?)?)\b")
#: Part-39 amendment. AD amendments are always part 39, which keeps the
#: "Amdt. Nos. 21-106, 23-65, ..." entries of non-AD rules out.
_AMENDMENT = re.compile(r"\b(39-\d{4,6})\b")
#: AD number with an explicit AD token, with either separator.
_AD_TOKEN = re.compile(r"\bAD[ -](\d{2,4}-\d{2}-\d{2})\s*(R\d+)?", re.IGNORECASE)
#: Bare AD number occupying a whole entry.
_AD_BARE = re.compile(r"^(\d{2,4}-\d{2}-\d{2})\s*(R\d+)?$")
_PROJECT = re.compile(r"\b((?:Project|Product) Identifier)\s+([A-Za-z0-9-]+)")


@dataclass(frozen=True)
class DocketIds:
    """What the structured list actually told us. Absent facts stay ``None``."""

    docket_id: str | None
    amendment: str | None
    ad_number: str | None
    ad_revision_suffix: str | None
    project_identifier: str | None

    @property
    def is_airworthiness_directive(self) -> bool:
        """An FAA rule is an AD exactly when the structured list names an AD number."""
        return self.ad_number is not None


def _clean_docket(raw: str) -> str:
    return raw.replace(" ", "-")


def parse_docket_ids(entries: list[str] | None) -> DocketIds:
    """Extract docket, amendment and AD number from one document's ``docket_ids``."""
    docket = amendment = ad_number = suffix = project = None
    for entry in entries or []:
        text = (entry or "").strip()
        if not text:
            continue
        lowered = text.lower()

        if docket is None and lowered.startswith("docket"):
            modern = _FAA_DOCKET.search(text)
            legacy = _LEGACY_DOCKET.search(text)
            if modern:
                docket = _clean_docket(modern.group(1))
            elif legacy:
                docket = legacy.group(1)

        if amendment is None and ("amendment" in lowered or "amdt" in lowered):
            found = _AMENDMENT.search(text)
            if found:
                amendment = found.group(1)

        if project is None:
            found = _PROJECT.search(text)
            if found:
                project = found.group(2)

        if ad_number is None:
            found = _AD_TOKEN.search(text) or _AD_BARE.match(text)
            if found:
                ad_number, suffix = found.group(1), found.group(2)

    return DocketIds(
        docket_id=docket,
        amendment=amendment,
        ad_number=ad_number,
        ad_revision_suffix=(suffix or "").upper() or None,
        project_identifier=project,
    )


def normalize_sheet_docket(raw: str) -> tuple[list[str], str]:
    """Normalize a spreadsheet ``Docket Number`` cell to docket ids plus the raw text.

    The column is hand-maintained and 60 of its 323 distinct values are not in
    the FAA-YYYY-NNNN form the contract's note describes. Real values::

        "FAA-2026-11814"                 -> ["FAA-2026-11814"]
        "FAA 2022-0460"                  -> ["FAA-2022-0460"]   (space separator)
        "FAA-2021-1078R1"                -> ["FAA-2021-1078"]    (re-notice suffix)
        "FAA-2025-0199_S"                -> ["FAA-2025-0199"]    (supplemental suffix)
        "FAA-2009-0555-W"                -> ["FAA-2009-0555"]    (withdrawal suffix)
        "2002-NM-352-AD"                 -> ["2002-NM-352-AD"]   (legacy, kept as is)
        "FAA Rules 95-CE-35-AD"          -> ["95-CE-35-AD"]
        "2002-CE-05-AD, 2002-CE-57-AD"   -> both, in cell order

    Returns ``(docket_ids, raw)``; the list is empty when nothing parses.
    """
    raw = (raw or "").strip()
    found = [_clean_docket(m) for m in _FAA_DOCKET.findall(raw)]
    found += [m for m in _LEGACY_DOCKET.findall(raw)]
    seen: list[str] = []
    for item in found:
        if item not in seen:
            seen.append(item)
    return seen, raw


def _survey() -> int:
    """Recount this module's docstring against the cached Federal Register index.

    The docstring names shapes rather than frequencies on purpose: the harvest
    keeps adding documents, so a pinned count is stale the moment it is
    written. What this proves is the claim that actually matters -- every
    branch below is driven by real data, and nothing in the index fails to
    yield a docket number.
    """
    import collections
    import json

    from engine.paths import FR_INDEX_CACHE

    # Two populations, reported separately because they are not the same thing
    # and conflating them is how a percentage becomes wrong. rules_*.json is
    # the windowed FAA final-rule index -- the population this parser's
    # branches were derived from. docket_*.json is a per-docket lookup, which
    # returns every document filed under a docket including notices and
    # proposals, so its mix of shapes is different by construction.
    populations: dict[str, dict[str, list[str]]] = {
        "windowed FAA final rules (rules_*.json)": {},
        "per-docket lookups (docket_*.json)": {},
    }
    for path in sorted(FR_INDEX_CACHE.glob("*.json")):
        if path.name.startswith("rules_"):
            bucket = populations["windowed FAA final rules (rules_*.json)"]
        elif path.name.startswith("docket_"):
            bucket = populations["per-docket lookups (docket_*.json)"]
        else:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in payload.get("results") or []:
            number = row.get("document_number")
            if number and row.get("docket_ids"):
                bucket[number] = row["docket_ids"]

    if not any(populations.values()):
        print(f"no cached index under {FR_INDEX_CACHE}; run the ingest first")
        return 1

    print(f"cached index: {FR_INDEX_CACHE}")
    for name, documents in populations.items():
        print()
        print(f"{name}: {len(documents)} documents with docket_ids")
        if not documents:
            continue
        shapes: collections.Counter[str] = collections.Counter()
        no_docket = no_ad = 0
        for entries in documents.values():
            parsed = parse_docket_ids(entries)
            if not parsed.docket_id:
                no_docket += 1
            if not parsed.ad_number:
                no_ad += 1
            listed = entries if isinstance(entries, list) else [entries]
            if len(listed) == 4 and str(listed[0]).startswith("Docket No. FAA-"):
                shapes["four entries, 'Docket No. FAA-' first"] += 1
            else:
                shapes["anything else"] += 1
        total = len(documents)
        for shape, count in shapes.most_common():
            print(f"  {shape}: {count} ({100 * count / total:.1f}%)")
        print(f"  no docket number parsed: {no_docket}")
        print(f"  no AD number parsed: {no_ad} (expected: documents that are not ADs)")
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Survey the cached docket_ids shapes.")
    parser.add_argument("--survey", action="store_true", help="recount the docstring's claims")
    args = parser.parse_args()
    if not args.survey:
        parser.error("nothing to do; pass --survey")
    sys.exit(_survey())
