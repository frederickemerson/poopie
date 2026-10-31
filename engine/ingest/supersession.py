"""Supersession, read out of paragraph (b) "Affected ADs" and the revision dates.

Paragraph (b) states the relationship in prose, and the verb carries the meaning.
Real text from the corpus::

    "None."
    "This AD replaces AD 2019-02-03, Amendment 39-19550 (84 FR 2437, February 7, 2019)."
    "This AD removes AD 2018-05-09, Amendment 39-19218 (83 FR 10360, March 9, 2018)."
    "This AD affects AD 2023-26-01, Amendment 39-22644 (89 FR 253, January 3, 2024)."
    "This AD is related to AD 2022-02-09, Amendment 39-21906 (87 FR 7029, ...)."
    "(1) This AD replaces AD 2021-24-20 ...; and AD 2023-03-05 ...  (2) This AD affects ..."

"replaces" and "removes" are supersession. "affects" and "is related to" are not,
and conflating them would wrongly retire an AD that is still in force, so the
verb is classified and only the superseding ones produce a SUPERSEDES edge. A
referenced AD outside the corpus is recorded as dangling; no node is invented
for it.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field

_SUPERSEDING_VERBS = ("replaces", "supersedes", "removes", "cancels", "revises")
_RELATED_VERBS = ("affects", "is related to", "relates to")
_VERB = re.compile(
    r"\bthis ad (?P<verb>" + "|".join(_SUPERSEDING_VERBS + _RELATED_VERBS) + r")\b",
    re.IGNORECASE,
)
_AD_NUMBER = re.compile(r"\bAD[ -](\d{2,4}-\d{2}-\d{2})\s?(R\d+)?\b")


@dataclass(frozen=True)
class AffectedADs:
    superseded: list[str]
    related: list[str]
    quote: str


def parse_affected_ads(text: str) -> AffectedADs:
    """Pull AD numbers out of an "Affected ADs" paragraph, grouped by verb."""
    superseded: list[str] = []
    related: list[str] = []
    matches = list(_VERB.finditer(text or ""))
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        clause = text[match.start() : end]
        bucket = superseded if match.group("verb").lower() in _SUPERSEDING_VERBS else related
        for number, _suffix in _AD_NUMBER.findall(clause):
            if number not in bucket:
                bucket.append(number)
    return AffectedADs(superseded=superseded, related=related, quote=" ".join((text or "").split()))


@dataclass
class RevisionFacts:
    """What the chain builder needs to know about one Federal Register document."""

    revision_id: str
    ad_number: str
    amendment: str | None
    publication_date: dt.date | None
    superseded_ad_numbers: list[str] = field(default_factory=list)


@dataclass
class SupersessionResult:
    edges: list[tuple[str, str]] = field(default_factory=list)
    superseded_by: dict[str, str] = field(default_factory=dict)
    is_current: dict[str, bool] = field(default_factory=dict)
    current_revision: dict[str, str] = field(default_factory=dict)
    dangling: list[tuple[str, str]] = field(default_factory=list)
    corrections: list[tuple[str, str]] = field(default_factory=list)


def _sort_key(fact: RevisionFacts) -> tuple[dt.date, str]:
    return (fact.publication_date or dt.date.min, fact.revision_id)


def build_chain(facts: list[RevisionFacts]) -> SupersessionResult:
    """Order revisions, then resolve both kinds of supersession.

    Inside one AD number, a later Federal Register document that carries a *new*
    part-39 amendment supersedes the earlier one; a later document with the
    *same* amendment is a correction of it (35 of the 40 multi-document ADs in
    the corpus are this case) and gets no SUPERSEDES edge, only loses currency.
    Across AD numbers, paragraph (b) decides.
    """
    result = SupersessionResult()
    by_ad: dict[str, list[RevisionFacts]] = defaultdict(list)
    for fact in facts:
        by_ad[fact.ad_number].append(fact)
    for revisions in by_ad.values():
        revisions.sort(key=_sort_key)

    for ad_number, revisions in by_ad.items():
        for previous, current in zip(revisions, revisions[1:]):
            if previous.amendment and current.amendment and previous.amendment == current.amendment:
                result.corrections.append((current.revision_id, previous.revision_id))
                continue
            result.edges.append((current.revision_id, previous.revision_id))
            result.superseded_by[previous.revision_id] = current.revision_id
        result.current_revision[ad_number] = revisions[-1].revision_id

    for fact in facts:
        for target_ad in fact.superseded_ad_numbers:
            if target_ad == fact.ad_number:
                continue
            candidates = by_ad.get(target_ad)
            if not candidates:
                result.dangling.append((fact.revision_id, target_ad))
                continue
            earlier = [
                candidate
                for candidate in candidates
                if candidate.publication_date
                and fact.publication_date
                and candidate.publication_date <= fact.publication_date
            ]
            target = (earlier or candidates)[-1]
            result.edges.append((fact.revision_id, target.revision_id))
            result.superseded_by[target.revision_id] = fact.revision_id

    for ad_number, revisions in by_ad.items():
        latest = revisions[-1].revision_id
        for fact in revisions:
            result.is_current[fact.revision_id] = (
                fact.revision_id == latest and latest not in result.superseded_by
            )
    return result


def ad_status(ad_number: str, result: SupersessionResult) -> str:
    """Lowercase to match the spreadsheet's own Status vocabulary ("Current")."""
    current = result.current_revision.get(ad_number)
    if current and result.is_current.get(current):
        return "current"
    return "superseded"
