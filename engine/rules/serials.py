"""Ordering aircraft serial numbers against an AD's serial range.

Serials in the real fleet data are not numbers. They look like ``24729``,
``E-3121``, ``31-7852015``, ``20407``. An AD range is written against one
manufacturer's scheme, so the only safe comparison is between serials of the
*same shape*: the same literal separators in the same places and the same
number of digit groups. Anything else is unorderable, and unorderable returns
None -- never a guess, because guessing here grounds the wrong airplane.

Bounds are inclusive: ADs write "serial numbers 20003 through 20407 inclusive".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"(\d+)|([^\d]+)")


@dataclass(frozen=True)
class Serial:
    """A serial split into its literal shape and its ordered digit groups."""

    raw: str
    shape: tuple[str, ...]
    numbers: tuple[int, ...]

    @property
    def orderable(self) -> bool:
        return bool(self.numbers)


def parse(raw: str | None) -> Serial | None:
    """Split a serial into (shape, numbers); None when there is nothing to parse."""
    if raw is None:
        return None
    text = " ".join(str(raw).split()).upper()
    if not text:
        return None
    shape: list[str] = []
    numbers: list[int] = []
    for digits, literal in _TOKEN.findall(text):
        if digits:
            numbers.append(int(digits))
        else:
            # Separators are part of the shape; "-" and " " are not interchangeable
            # on purpose, so "31-7852015" never compares against "31 7852015".
            shape.append(literal.strip() or literal)
    return Serial(raw=text, shape=tuple(shape), numbers=tuple(numbers))


def comparable(a: Serial, b: Serial) -> bool:
    """True when two serials belong to the same numbering scheme."""
    return a.orderable and b.orderable and a.shape == b.shape and len(a.numbers) == len(b.numbers)


def in_range(serial: str | None, low: str | None, high: str | None) -> bool | None:
    """Is ``serial`` within [low, high] inclusive? None when it cannot be ordered."""
    s, lo, hi = parse(serial), parse(low), parse(high)
    if s is None or lo is None or hi is None:
        return None
    if not (comparable(s, lo) and comparable(s, hi) and comparable(lo, hi)):
        return None
    if lo.numbers > hi.numbers:
        return None
    return lo.numbers <= s.numbers <= hi.numbers


def equal(serial: str | None, other: str | None) -> bool | None:
    """Serial identity. Same shape required; None when either side is empty."""
    s, o = parse(serial), parse(other)
    if s is None or o is None:
        return None
    if s.raw == o.raw:
        return True
    if not comparable(s, o):
        return None
    return s.numbers == o.numbers


def describe(serial: str | None) -> str:
    s = parse(serial)
    if s is None:
        return "no serial number on the fleet record"
    if not s.orderable:
        return f"serial {s.raw!r} has no digit group to order"
    return f"serial {s.raw!r} (shape {''.join(s.shape) or 'plain digits'})"
