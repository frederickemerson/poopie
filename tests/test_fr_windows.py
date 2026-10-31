"""Regression tests for Federal Register date windowing.

The month splitter built its own day-length table and gave February 29 days in
every year. The API rejected 2021-02-29 with HTTP 400 and the harvest stopped
after January, so the corpus silently stayed tiny. These tests pin the real
calendar.
"""

from __future__ import annotations

import calendar
import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.ingest.fr_client import FederalRegisterClient  # noqa: E402


class _NoNetwork(FederalRegisterClient):
    """Captures the windows that would be requested without calling the API."""

    def __init__(self):  # noqa: D107 - test double, no base init needed
        self.windows: list[tuple[str, str]] = []

    def _cached_json(self, name, params):  # type: ignore[override]
        self.windows.append((params["conditions[publication_date][gte]"],
                             params["conditions[publication_date][lte]"]))
        return {"count": 0, "results": []}

    def _rule_window(self, gte, lte, term):  # type: ignore[override]
        return {
            "conditions[publication_date][gte]": gte,
            "conditions[publication_date][lte]": lte,
        }


def _split(gte: str, lte: str) -> list[tuple[str, str]]:
    client = _NoNetwork()
    list(client._split_by_month(gte, lte, "airworthiness directives"))
    return client.windows


@pytest.mark.parametrize("year", [2021, 2022, 2023, 2025, 2026])
def test_february_window_never_exceeds_the_real_month(year: int):
    """2021-02-29 does not exist; requesting it returns HTTP 400."""
    for gte, lte in _split(f"{year}-01-01", f"{year}-12-31"):
        for value in (gte, lte):
            # Raises ValueError on an impossible date such as 2021-02-29.
            dt.date.fromisoformat(value)


@pytest.mark.parametrize("year,month", [(2021, 2), (2024, 2), (2023, 4), (2023, 12)])
def test_window_end_matches_calendar(year: int, month: int):
    expected = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    windows = _split(f"{year}-01-01", f"{year}-12-31")
    ends = {lte for _, lte in windows if lte.startswith(f"{year}-{month:02d}")}
    assert expected in ends, f"expected window ending {expected}, got {sorted(ends)}"


def test_leap_year_february_has_29_days():
    """The fix must not over-correct February to 28 in a leap year."""
    windows = _split("2024-02-01", "2024-02-29")
    assert any(lte == "2024-02-29" for _, lte in windows)


def test_windows_cover_every_day_of_the_year():
    """No gap between consecutive month windows, or documents go missing."""
    windows = sorted(_split("2023-01-01", "2023-12-31"))
    covered: set[dt.date] = set()
    for gte, lte in windows:
        start, end = dt.date.fromisoformat(gte), dt.date.fromisoformat(lte)
        day = start
        while day <= end:
            covered.add(day)
            day += dt.timedelta(days=1)
    expected = {dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(365)}
    assert covered == expected, f"missing days: {sorted(expected - covered)[:5]}"
