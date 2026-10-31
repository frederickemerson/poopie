"""Read the AD NPRM spreadsheet (proposed rules).

Verified quirks of the real file (431 data rows, 22 columns, one sheet), each of
which is handled explicitly below:

* all three date columns are TEXT in %m/%d/%Y and parse 431/431;
* 323 distinct dockets, 99 of which appear on more than one row. Those are
  re-notices and supplemental NPRMs, not duplicates, so one node is emitted per
  ROW and the identity is docket + Federal Register citation, which is unique
  across all 431 rows;
* 4 rows carry no comments-due date;
* AC Reference, AIR Policy Reference and Additional Reference are 100% empty and
  are not read;
* ``Make`` is not normalized ("Boeing" vs "The Boeing Company"), so both the
  normalized and the raw value are carried out of here;
* ``Docket Number`` is not uniformly FAA-YYYY-NNNN: 60 of the 323 values are
  legacy directorate dockets or carry a re-notice suffix, and one cell names two
  dockets. :func:`normalize_sheet_docket` owns that.

The challenge organizers' re-publication of the same 431 rows
(``data/reference/challenge-4-ad-index.xlsx``) is read by
:mod:`engine.ingest.nprm_index_xlsx`, which reuses :func:`clean_cell`,
:func:`parse_date`, :func:`page_range` and :class:`NPRMRow` from here rather
than re-implementing them. That module's docstring records which of the quirks
above still hold in the new file and which the organizers fixed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from engine.ingest.docket_ids import normalize_sheet_docket
from engine.ingest.make_normalize import normalize_make

DATE_FORMAT = "%m/%d/%Y"

#: Columns read by name, so a reordered export does not silently shift values.
_REQUIRED_COLUMNS = (
    "Docket Number",
    "Subject Heading",
    "Issue Date",
    "AD Number",
    "Citation Publish Date",
    "Comments Due Date",
    "Make",
    "Model",
    "Product Type",
    "Link for Submitting Public Comment",
    "Citation",
    "Page Number",
    "Summary",
)
#: Present in the file but empty in every row; recorded here so the omission is
#: deliberate rather than an oversight.
EMPTY_COLUMNS = ("AC Reference", "AIR Policy Reference", "Additional Reference")


class SpreadsheetError(RuntimeError):
    """The spreadsheet is not the shape this module was verified against."""


@dataclass
class NPRMRow:
    row_number: int
    docket_ids: list[str]
    docket_raw: str
    subject_heading: str | None
    issue_date: dt.date | None
    ad_number: str | None
    publish_date: dt.date | None
    comments_due_date: dt.date | None
    make: str | None
    make_raw: str | None
    model_text: str | None
    product_type: str | None
    comment_url: str | None
    citation: str | None
    page_range: str | None
    summary: str | None

    @property
    def docket_id(self) -> str | None:
        return self.docket_ids[0] if self.docket_ids else None


@dataclass
class SpreadsheetLoad:
    rows: list[NPRMRow]
    date_parse_failures: list[str] = field(default_factory=list)
    rows_without_docket: list[int] = field(default_factory=list)
    rows_with_multiple_dockets: list[int] = field(default_factory=list)


def parse_date(
    raw: object,
    where: str,
    failures: list[str],
    formats: tuple[str, ...] = (DATE_FORMAT,),
) -> dt.date | None:
    """Parse a date cell. ``formats`` is tried in order; nothing is guessed.

    ``formats`` exists because the two spreadsheets that carry these 431 rows
    store the same dates differently: the FAA export uses %m/%d/%Y and the
    challenge index uses ISO. A failure is appended to ``failures`` and never
    swallowed.
    """
    if raw in (None, ""):
        return None
    if isinstance(raw, dt.datetime):
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    text = str(raw).strip()
    last: ValueError | None = None
    for fmt in formats:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError as exc:
            last = exc
    failures.append(f"{where}: {raw!r} ({last})")
    return None


def clean_cell(value: object) -> str | None:
    """Collapse whitespace; an empty or blank cell becomes None, never ""."""
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    return text or None


def page_range(value: object) -> str | None:
    """The page range as the sheet displays it, without its wrapper."""
    text = clean_cell(value)
    if not text:
        return None
    return text.removeprefix("(Pages ").removeprefix("(Page ").removesuffix(")").strip()


def load_nprm_rows(path: Path) -> SpreadsheetLoad:
    """Parse every data row. Nothing is skipped and no date failure is swallowed."""
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = workbook.worksheets[0]
    raw_rows = list(sheet.iter_rows(values_only=True))
    workbook.close()
    if not raw_rows:
        raise SpreadsheetError(f"{path} has no rows")

    header = [clean_cell(h) for h in raw_rows[0]]
    missing = [c for c in _REQUIRED_COLUMNS if c not in header]
    if missing:
        raise SpreadsheetError(f"{path} is missing expected columns {missing}")
    index = {name: position for position, name in enumerate(header) if name}

    load = SpreadsheetLoad(rows=[])
    for offset, raw in enumerate(raw_rows[1:], start=2):
        if not any(cell not in (None, "") for cell in raw):
            continue

        def cell(name: str, raw=raw) -> object:
            return raw[index[name]]

        dockets, docket_raw = normalize_sheet_docket(str(cell("Docket Number") or ""))
        if not dockets:
            load.rows_without_docket.append(offset)
        if len(dockets) > 1:
            load.rows_with_multiple_dockets.append(offset)
        make_raw = clean_cell(cell("Make"))
        load.rows.append(
            NPRMRow(
                row_number=offset,
                docket_ids=dockets,
                docket_raw=docket_raw,
                subject_heading=clean_cell(cell("Subject Heading")),
                issue_date=parse_date(cell("Issue Date"), f"row {offset} Issue Date", load.date_parse_failures),
                ad_number=clean_cell(cell("AD Number")),
                publish_date=parse_date(
                    cell("Citation Publish Date"),
                    f"row {offset} Citation Publish Date",
                    load.date_parse_failures,
                ),
                comments_due_date=parse_date(
                    cell("Comments Due Date"),
                    f"row {offset} Comments Due Date",
                    load.date_parse_failures,
                ),
                make=normalize_make(make_raw),
                make_raw=make_raw,
                model_text=clean_cell(cell("Model")),
                product_type=clean_cell(cell("Product Type")),
                comment_url=clean_cell(cell("Link for Submitting Public Comment")),
                citation=clean_cell(cell("Citation")),
                page_range=page_range(cell("Page Number")),
                summary=clean_cell(cell("Summary")),
            )
        )
    return load


def nprm_id_for(row: NPRMRow, taken: set[str]) -> str:
    """Stable id from docket + publication date, which is unique across the file.

    A collision would mean two rows share a docket and a publication date; the
    suffix keeps the id unique and the report records it rather than letting one
    row overwrite the other.
    """
    stem = row.docket_id or f"ROW{row.row_number}"
    date_part = row.publish_date.isoformat() if row.publish_date else f"row{row.row_number}"
    candidate = f"{stem}@{date_part}"
    if candidate not in taken:
        return candidate
    suffix = 2
    while f"{candidate}~{suffix}" in taken:
        suffix += 1
    return f"{candidate}~{suffix}"
