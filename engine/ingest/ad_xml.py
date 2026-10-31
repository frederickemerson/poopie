"""Parse one Federal Register AD document XML into labelled paragraphs.

The tree is walked with lxml; the markup is never regex-matched. Two real
structures exist in the corpus and both are handled, chosen by what the document
itself contains rather than by its date:

``labelled_headings`` (the modern form, ~2010 onward)
    ``<HD SOURCE="HD1">(c) Applicability</HD>`` followed by ``<P>`` blocks. The
    label is in the heading. Note the operative block is *not* always inside
    ``REGTEXT/EXTRACT``: in 2023-04860 and 2024-03080 the EXTRACT hangs off
    SUPLINF, and in 2026-02095 the headings are not inside an EXTRACT at all.
    So the section boundaries come from the labelled headings themselves and the
    parent of the first one bounds the block.

``inline_labels`` (the legacy form, e.g. 04-6499 from 2004)
    ``<HD SOURCE="HD1">Effective Date</HD>`` carries only the topic and the label
    opens the paragraph text: ``<P>(g) This amendment becomes effective ...</P>``.

``Paragraph.label`` is the document's own letter without its parentheses ("c"),
which is what ``engine/retrieval`` and ``web/lib/citation.ts`` build citation ids
from: ``{revision_id}#{label}@{char_start}-{char_end}``.

``plain_text`` is assembled from the paragraph texts, so ``char_start``/
``char_end`` are exact by construction; :func:`assert_offsets_round_trip` proves
it for every paragraph before anything is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from engine.ingest.roles import role_for_heading

#: Elements that carry text we must keep. NOTE/SIG/GPOTABLE are containers whose
#: text-bearing children are listed here, so nothing is counted twice. AMDPAR is
#: excluded on purpose: it is the amendatory instruction, not AD text.
_BLOCK_TAGS = frozenset({"P", "HD", "FP", "GPOTABLE"})

_LABELLED_HEADING = re.compile(r"^\s*\(\s*([A-Za-z0-9]{1,3})\s*\)\s*(.*)$", re.DOTALL)
_INLINE_LABEL = re.compile(r"^\s*\(([a-z])\)\s")
_AD_NUMBER_HEADER = re.compile(r"^\s*(\d{2,4}-\d{2}-\d{2})\s*(R\d+)?\s*(.*)$", re.DOTALL)
_PRODUCT_WORDS = (
    "Airplanes",
    "Helicopters",
    "Engines",
    "Propellers",
    "Gliders",
    "Balloons",
    "Airships",
    "Aircraft",
)


@dataclass(frozen=True)
class ParsedParagraph:
    label: str
    heading: str
    role: str
    text: str
    char_start: int
    char_end: int
    ordinal: int


@dataclass
class ParsedAD:
    document_number: str
    structure: str
    plain_text: str
    paragraphs: list[ParsedParagraph] = field(default_factory=list)
    header_line: str | None = None
    ad_number_in_text: str | None = None
    manufacturer_raw: str | None = None
    subject: str | None = None
    product_word: str | None = None
    notes: list[str] = field(default_factory=list)


def _text_of(element: etree._Element) -> str:
    """Canonical text of one block element: all descendant text, whitespace collapsed."""
    return " ".join("".join(element.itertext()).split())


def _blocks(root: etree._Element) -> list[etree._Element]:
    return [el for el in root.iter() if isinstance(el.tag, str) and el.tag in _BLOCK_TAGS]


def _is_labelled_heading(element: etree._Element) -> re.Match[str] | None:
    if element.tag != "HD" or element.get("SOURCE") != "HD1":
        return None
    return _LABELLED_HEADING.match(_text_of(element))


def _within(element: etree._Element, container: etree._Element) -> bool:
    node: etree._Element | None = element
    while node is not None:
        if node is container:
            return True
        node = node.getparent()
    return False


def _header_from_fp(root: etree._Element) -> tuple[str | None, str | None, str | None]:
    """Read the AD's own citation line, e.g. '2026-21-12 The Boeing Company: ...'.

    The manufacturer here is the designation the AD itself uses, which is the
    closest thing the document has to a structured make field.
    """
    for fp in root.iter("FP"):
        text = _text_of(fp)
        match = _AD_NUMBER_HEADER.match(text)
        if not match:
            continue
        remainder = match.group(3)
        manufacturer = remainder.split(":", 1)[0].strip(" .,;") or None
        return text, match.group(1), manufacturer
    return None, None, None


def _subject_and_product(root: etree._Element) -> tuple[str | None, str | None]:
    subject = root.findtext(".//PREAMB/SUBJECT")
    if subject is None:
        return None, None
    subject = " ".join(subject.split())
    for word in _PRODUCT_WORDS:
        if subject.endswith(word):
            return subject, word
    return subject, None


def _sections_from_headings(blocks: list[etree._Element]) -> list[tuple[str, str, list[str]]]:
    starts = [(i, m) for i, el in enumerate(blocks) if (m := _is_labelled_heading(el))]
    if len(starts) < 3:
        return []
    container = blocks[starts[0][0]].getparent()
    sections: list[tuple[str, str, list[str]]] = []
    for position, (index, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(blocks)
        body: list[str] = []
        for el in blocks[index + 1 : end]:
            if container is not None and not _within(el, container):
                continue
            text = _text_of(el)
            if text:
                body.append(text)
        sections.append((match.group(1), " ".join(match.group(2).split()), body))
    return sections


def _sections_from_inline_labels(root: etree._Element) -> list[tuple[str, str, list[str]]]:
    """Legacy form: the label opens the paragraph and the heading sits above it."""
    extract = None
    for candidate in root.iter("EXTRACT"):
        if any(_INLINE_LABEL.match(_text_of(p)) for p in candidate.iter("P")):
            extract = candidate
            break
    if extract is None:
        return []

    sections: list[tuple[str, str, list[str]]] = []
    heading = ""
    expected = "a"
    for el in _blocks(extract):
        text = _text_of(el)
        if not text:
            continue
        if el.tag == "HD":
            heading = text
            continue
        match = _INLINE_LABEL.match(text)
        # Only the next letter in sequence opens a section; this keeps roman
        # sub-items such as "(i)" inside their parent paragraph.
        if match and match.group(1) == expected:
            sections.append((match.group(1), heading, [text]))
            expected = chr(ord(expected) + 1)
        elif sections:
            sections[-1][2].append(text)
    return sections


def _assemble(
    document_number: str,
    header_line: str | None,
    sections: list[tuple[str, str, list[str]]],
) -> tuple[str, list[ParsedParagraph], list[str]]:
    notes: list[str] = []
    chunks: list[str] = []
    cursor = 0
    if header_line:
        chunks.append(header_line)
        cursor = len(header_line) + 2

    paragraphs: list[ParsedParagraph] = []
    used: dict[str, int] = {}
    for ordinal, (label, heading, body) in enumerate(sections):
        text = "\n".join([heading] + body) if heading else "\n".join(body)
        text = text.strip()
        if not text:
            text = heading.strip() or label
        seen = used.get(label, 0) + 1
        used[label] = seen
        unique = label if seen == 1 else f"{label}~{seen}"
        if seen > 1:
            notes.append(f"duplicate paragraph label {label} in {document_number}; kept as {unique}")
        start = cursor
        end = start + len(text)
        chunks.append(text)
        cursor = end + 2
        paragraphs.append(
            ParsedParagraph(
                label=unique,
                heading=heading,
                role=role_for_heading(heading),
                text=text,
                char_start=start,
                char_end=end,
                ordinal=ordinal,
            )
        )
    return "\n\n".join(chunks), paragraphs, notes


def assert_offsets_round_trip(parsed: ParsedAD) -> None:
    """plain_text[char_start:char_end] must equal the paragraph text, exactly.

    A silent offset error would corrupt every citation built on this revision, so
    this is an assertion and not a warning.
    """
    for paragraph in parsed.paragraphs:
        span = parsed.plain_text[paragraph.char_start : paragraph.char_end]
        if span != paragraph.text:
            raise ValueError(
                f"{parsed.document_number} paragraph {paragraph.label}: "
                f"plain_text[{paragraph.char_start}:{paragraph.char_end}] does not match its text"
            )


def parse_ad_xml(source: Path | bytes, document_number: str) -> ParsedAD:
    """Parse one AD document. Never raises on a document it cannot section."""
    if isinstance(source, Path):
        tree = etree.parse(str(source))
        root = tree.getroot()
    else:
        root = etree.fromstring(source)

    header_line, ad_number, manufacturer = _header_from_fp(root)
    subject, product_word = _subject_and_product(root)

    blocks = _blocks(root)
    sections = _sections_from_headings(blocks)
    structure = "labelled_headings"
    if not sections:
        sections = _sections_from_inline_labels(root)
        structure = "inline_labels" if sections else "none"

    plain_text, paragraphs, notes = _assemble(document_number, header_line, sections)
    parsed = ParsedAD(
        document_number=document_number,
        structure=structure,
        plain_text=plain_text,
        paragraphs=paragraphs,
        header_line=header_line,
        ad_number_in_text=ad_number,
        manufacturer_raw=manufacturer,
        subject=subject,
        product_word=product_word,
        notes=notes,
    )
    assert_offsets_round_trip(parsed)
    return parsed
