"""Federal Register page arithmetic: the one place that formats a page range.

A page number is only meaningful with its volume. Volume 1 of the Federal
Register is 1936, so ``volume == year - 1935``, and pages run continuously
through a volume -- which is what makes ``(volume, start_page)`` a unique
address for a document and lets a corpus be counted in distinct pages.

This module exists because three layers need the same two facts and a page
range that differs between them is a page range a reader cannot check:

* ``engine.ingest.nprm_text`` formats the range it writes onto a proposal node;
* ``engine.retrieval.corpus`` formats the range it hands to a retrieval hit;
* ``engine.api.citations`` formats the range it renders in a citation.

Every function here takes integers and returns a string or None. **Nothing is
parsed out of prose.** A range this engine cannot state from two numbers is not
stated at all, because a guessed page is worse than an absent one: a reader who
is told "pages 66019-66022" and finds something else there has no way to tell
which of the two is wrong.

Equally, an *absent* range must be a real absence. A field that is null for most
of the corpus while the correct value sits one join away reads as "the Register
did not say", which is a false claim about the source. That failure is what
``tests/test_nprm_retrieval.py`` pins corpus-wide.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

#: Volume 1 of the Federal Register is 1936, so volume == year - 1935. Checked
#: against the ``citation`` of all 4,053 cached index documents: no exception.
VOLUME_EPOCH = 1935


def page_number(value: Any) -> int | None:
    """One page number, or None when the value is not one.

    Zero and negatives are not page numbers: the Federal Register starts at 1,
    so a 0 means "no value recorded" and must not become a page.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def page_range(start: Any, end: Any) -> str | None:
    """``start-end``, the start alone for a one-page document, or None.

    The shape is ``^(\\d+)(?:-(\\d+))?$``, which is what every consumer parses
    back. An end that is absent, unusable or not after the start yields the
    start alone rather than a reversed or zero-width range.
    """
    first = page_number(start)
    if first is None:
        return None
    last = page_number(end)
    if last is None or last <= first:
        return str(first)
    return f"{first}-{last}"


def volume_for(publication_date: Any) -> int | None:
    """The volume a document published on this date belongs to.

    From the year alone, which fixes the volume exactly. Note that this is why
    a publication date must be the Register's own: a date one day early turns a
    1 January notice into a previous-volume page, and a page attributed to the
    wrong volume corrupts a distinct-page count silently.
    """
    if isinstance(publication_date, dt.date):
        return publication_date.year - VOLUME_EPOCH
    try:
        return dt.date.fromisoformat(str(publication_date)[:10]).year - VOLUME_EPOCH
    except (TypeError, ValueError):
        return None


def pages_touched(start: Any, end: Any, publication_date: Any) -> set[tuple[int, int]]:
    """Every ``(volume, page)`` pair this document occupies, or an empty set.

    Empty when the volume or the first page is unknown, so a caller that unions
    these sets gets a floor rather than a number inflated by guesses.
    """
    first = page_number(start)
    volume = volume_for(publication_date)
    if first is None or volume is None:
        return set()
    last = page_number(end)
    final = last if last is not None and last > first else first
    return {(volume, page) for page in range(first, final + 1)}
