"""Federal Register API client: final-rule index plus cached document XML.

Two verified constraints shape this module:

* ``per_page`` caps at 1000 while ``count`` can exceed it (the window
  2021-01-01..2026-01-01 reports count=1873 and returns 1000 rows), so the index
  is fetched one publication year at a time and a window that still overflows is
  split by month. Nothing is ever silently truncated: an overflow that cannot be
  split raises.
* ``conditions[docket_id]`` is supported and returns every document filed under a
  docket regardless of publication date, which is how final rules for the
  spreadsheet's older dockets are found.

Every document XML is cached under ``data/raw/fr_ad/<document_number>.xml`` and
never re-downloaded.
"""

from __future__ import annotations

import calendar
import concurrent.futures as futures
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import requests

from engine.paths import FR_INDEX_CACHE, FR_XML_CACHE

API = "https://www.federalregister.gov/api/v1/documents.json"
USER_AGENT = "autsg-ad-ingest/1.0 (research prototype; Federal Register public API)"
MAX_PER_PAGE = 1000

#: Fields requested from the index. docket_ids, effective_on, publication_date
#: and full_text_xml_url are the authoritative ones the contract names.
INDEX_FIELDS = (
    "document_number",
    "docket_ids",
    "title",
    "type",
    "action",
    "publication_date",
    "effective_on",
    "citation",
    "start_page",
    "end_page",
    "full_text_xml_url",
    "html_url",
)


class FederalRegisterError(RuntimeError):
    """The API answered with something this ingest cannot use."""


@dataclass
class FetchStats:
    index_requests: int = 0
    index_cache_hits: int = 0
    xml_downloads: int = 0
    xml_cache_hits: int = 0
    xml_failures: list[str] | None = None

    def __post_init__(self) -> None:
        if self.xml_failures is None:
            self.xml_failures = []


class FederalRegisterClient:
    def __init__(self, *, sleep_seconds: float = 0.2, offline: bool = False) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.sleep_seconds = sleep_seconds
        self.offline = offline
        self.stats = FetchStats()

    # ---------------------------------------------------------------- index

    def _get(self, params: list[tuple[str, str]], attempts: int = 4) -> dict:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self.session.get(API, params=params, timeout=180)
            except requests.RequestException as exc:  # network-level failure
                last = exc
            else:
                if response.status_code == 200:
                    self.stats.index_requests += 1
                    time.sleep(self.sleep_seconds)
                    return response.json()
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise FederalRegisterError(
                        f"HTTP {response.status_code} from {response.url}: {response.text[:200]}"
                    )
                last = FederalRegisterError(f"HTTP {response.status_code} from {response.url}")
            time.sleep(1.5 * (attempt + 1))
        raise FederalRegisterError(f"giving up on {params}: {last}")

    def _cached_json(self, name: str, params: list[tuple[str, str]]) -> dict:
        path = FR_INDEX_CACHE / f"{name}.json"
        if path.exists():
            self.stats.index_cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        if self.offline:
            raise FederalRegisterError(f"offline and no cached index at {path}")
        payload = self._get(params)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def _rule_window(self, gte: str, lte: str, term: str) -> list[tuple[str, str]]:
        params = [
            ("conditions[agencies][]", "federal-aviation-administration"),
            ("conditions[type][]", "RULE"),
            ("conditions[term]", term),
            ("conditions[publication_date][gte]", gte),
            ("conditions[publication_date][lte]", lte),
            ("per_page", str(MAX_PER_PAGE)),
            ("page", "1"),
            ("order", "oldest"),
        ]
        params += [("fields[]", f) for f in INDEX_FIELDS]
        return params

    def final_rules_between(
        self, gte: str, lte: str, term: str = "airworthiness directives"
    ) -> Iterator[dict]:
        """Yield every FAA final rule published in [gte, lte], windowing as needed."""
        name = f"rules_{gte}_{lte}"
        payload = self._cached_json(name, self._rule_window(gte, lte, term))
        results = payload.get("results") or []
        count = payload.get("count") or 0
        if count > len(results):
            if gte[:4] != lte[:4] or len(results) >= MAX_PER_PAGE:
                yield from self._split_by_month(gte, lte, term)
                return
            raise FederalRegisterError(
                f"window {gte}..{lte} reports {count} documents but returned {len(results)}"
            )
        yield from results

    def _split_by_month(self, gte: str, lte: str, term: str) -> Iterator[dict]:
        year_start, year_end = int(gte[:4]), int(lte[:4])
        for year in range(year_start, year_end + 1):
            for month in range(1, 13):
                first = f"{year}-{month:02d}-01"
                # calendar.monthrange is the authoritative answer for every year;
                # a hand-written day table got February wrong in non-leap years
                # and the API rejected the resulting 2021-02-29 with HTTP 400.
                last_day = calendar.monthrange(year, month)[1]
                last = f"{year}-{month:02d}-{last_day:02d}"
                if last < gte or first > lte:
                    continue
                payload = self._cached_json(
                    f"rules_{first}_{last}", self._rule_window(max(first, gte), min(last, lte), term)
                )
                results = payload.get("results") or []
                if (payload.get("count") or 0) > len(results):
                    raise FederalRegisterError(f"month window {first}..{last} still overflows")
                yield from results

    def documents_for_docket(self, docket_id: str) -> list[dict]:
        """Every document filed under one docket, any publication date."""
        params = [
            ("conditions[docket_id]", docket_id),
            ("per_page", "100"),
            ("page", "1"),
            ("order", "oldest"),
        ]
        params += [("fields[]", f) for f in INDEX_FIELDS]
        safe = docket_id.replace("/", "_")
        payload = self._cached_json(f"docket_{safe}", params)
        return payload.get("results") or []

    # ------------------------------------------------------------------ xml

    def prefetch_xml(self, wanted: list[tuple[str, str]], workers: int = 6) -> None:
        """Download the missing XML of many documents at once.

        A few thousand sequential round trips to a public API is 20 minutes of
        waiting; a small pool keeps it polite (six connections, the same
        per-request delay) and finishes in a couple of minutes. Already cached
        documents are not requested at all.
        """
        missing = [
            (number, url)
            for number, url in wanted
            if url and not (FR_XML_CACHE / f"{number}.xml").exists()
        ]
        if not missing or self.offline:
            return
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda item: self.document_xml(*item), missing))

    def document_xml(self, document_number: str, url: str) -> Path | None:
        """Return the cached XML path, downloading once if needed."""
        path = FR_XML_CACHE / f"{document_number}.xml"
        if path.exists() and path.stat().st_size > 0:
            self.stats.xml_cache_hits += 1
            return path
        if self.offline:
            return None
        try:
            response = self.session.get(url, timeout=180)
        except requests.RequestException as exc:
            self.stats.xml_failures.append(f"{document_number}: {exc}")
            return None
        if response.status_code != 200 or not response.content:
            self.stats.xml_failures.append(
                f"{document_number}: HTTP {response.status_code} for {url}"
            )
            return None
        path.write_bytes(response.content)
        self.stats.xml_downloads += 1
        time.sleep(self.sleep_seconds)
        return path
