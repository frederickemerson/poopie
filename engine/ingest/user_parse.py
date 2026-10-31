"""Turn one uploaded file into paragraphs, or refuse it with a reason.

Everything here treats the upload as hostile input. The engine is a read-only
answer engine; an uploaded document is data and is never executed, never passed
to a shell, never written over an existing artifact, and never resolved against
the filesystem or the network while being parsed.

Four refusals, all structural rather than best-effort:

* **Size.** ``MAX_UPLOAD_BYTES`` is checked against the bytes actually read,
  not against a declared ``Content-Length``, which the client controls.
* **Type.** An allow-list of media types, resolved from the filename extension
  and the declared type and required to agree. There is no "sniff and hope"
  path: a type not on the list is refused, which is how PDF is refused today.
* **Encoding.** UTF-8, strictly. A file that does not decode is refused rather
  than repaired, because silently replacing undecodable bytes would put
  characters in a citation that are not in the user's document. A NUL byte
  means binary content wearing a text extension, and is refused.
* **XML shape.** Entity resolution, DTD loading and network access are all off,
  and a document carrying a DTD at all is refused. That rules out XXE file
  reads and the billion-laughs expansion by construction, rather than by
  bounding the damage afterwards.

Two deliberate non-features.

**No paragraph role is inferred.** Every paragraph of a user document gets role
``OTHER``. ``engine.ingest.roles`` classifies FAA AD headings, and a service
bulletin's "Applicability" section is not an AD's "(c) Applicability" -- giving
it that role would make the user's own heading look like the structure the
rules engine reads. The heading text is kept verbatim for display instead.

**No heading is invented.** Markdown ATX headings (``#``) are used because
Markdown's own syntax says they are headings. Plain text and XML are given no
headings at all: there is no authoritative markup there to read one from, and
guessing one from prose is exactly the thing this codebase does not do.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.ingest.roles import FALLBACK_ROLE  # noqa: E402

#: 2 MiB. Large enough for a CFR part or a service bulletin as text, small
#: enough that a single request cannot exhaust memory or the paragraph budget.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
#: Paragraph count and size caps. Both are about the index, not the file: every
#: paragraph becomes an FTS5 row and an embedding, and a 200,000-paragraph
#: upload would quietly dominate the corpus it was meant to supplement.
MAX_PARAGRAPHS = 2_000
MAX_PARAGRAPH_CHARS = 20_000
#: Metadata the uploader types. Capped and stripped of control characters at
#: the boundary, so no consumer has to wonder whether it was.
MAX_TITLE_CHARS = 200
MAX_AUTHORITY_CHARS = 120
MAX_FILENAME_CHARS = 120

#: The allow-list. The value is the extension the stored copy is given, which
#: is taken from here and never from the uploaded filename.
MEDIA_TYPES: dict[str, str] = {
    "text/plain": "txt",
    "text/markdown": "md",
    "text/xml": "xml",
    "application/xml": "xml",
}
#: Filename extension -> media type. Separate from MEDIA_TYPES so several
#: spellings can name one type without inventing a media type per extension.
EXTENSIONS: dict[str, str] = {
    "txt": "text/plain",
    "text": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "xml": "application/xml",
}
#: Extensions of types we can name but do not accept, mapped to the media type
#: whose reason to print. The browser does not reliably declare a media type
#: (and the upload form deliberately does not send one), so the extension has to
#: reach the same refusal the declared type would.
UNSUPPORTED_EXTENSIONS: dict[str, str] = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}
#: Types we can name but deliberately do not accept, with the reason. Listed so
#: the refusal says "not supported yet" instead of "unknown type", which is a
#: different and less useful statement.
UNSUPPORTED_TYPES: dict[str, str] = {
    "application/pdf": (
        "PDF is not supported. Extracting text from a PDF needs a layout "
        "engine, and a citation whose character offsets came from a guessed "
        "reading order is not a citation. Convert it to text or Markdown first."
    ),
    "application/msword": "Word documents are not supported; export to text or Markdown.",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "Word documents are not supported; export to text or Markdown."
    ),
}

#: Control characters that may not survive into a paragraph. Tab and newline are
#: kept; everything else in the C0/C1 ranges is removed, so no citation span can
#: contain a character a reader cannot see.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
#: A Markdown ATX heading: one to six '#', a space, the text.
_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
#: Blank-line paragraph break, after newline normalisation.
_BLANK_LINE = re.compile(r"\n\s*\n+")


class UploadRejected(ValueError):
    """An upload this module refuses, with a reason the uploader can act on."""


@dataclass(frozen=True)
class ParsedUserParagraph:
    """One paragraph of a user document, with offsets into its plain text."""

    label: str
    heading: str
    role: str
    text: str
    char_start: int
    char_end: int
    ordinal: int


@dataclass(frozen=True)
class ParsedUserDocument:
    """The whole parse: the text a citation resolves against, and its parts."""

    media_type: str
    plain_text: str
    paragraphs: list[ParsedUserParagraph]
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------- the boundary


def clean_line(value: str | None, *, limit: int, what: str, required: bool = True) -> str:
    """One line of uploader-typed metadata: stripped, capped, control-free."""
    text = _CONTROL.sub("", str(value or "")).replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if not text:
        if required:
            raise UploadRejected(f"{what} is required")
        return ""
    return text[:limit]


def safe_filename(value: str | None) -> str:
    """The uploaded filename, for display only.

    Reduced to its basename and stripped of anything that could make it look
    like a path. It is never used to build a path -- the stored copy is named
    from the document's own content hash -- so this is about what gets rendered,
    not about where a byte lands.
    """
    text = clean_line(value, limit=MAX_FILENAME_CHARS, what="filename", required=False)
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = text.lstrip(".").replace("\x00", "")
    return text[:MAX_FILENAME_CHARS] or "upload"


def resolve_media_type(filename: str | None, declared: str | None) -> str:
    """The media type this upload will be parsed as, or a refusal.

    The extension decides, because it is the half the user can see and check.
    A declared type is honoured only when it names the same type; a declared
    type that disagrees with the extension is refused rather than quietly
    preferred, since whichever one we picked would be the wrong one half the
    time.
    """
    declared_type = (declared or "").split(";", 1)[0].strip().lower() or None
    if declared_type in UNSUPPORTED_TYPES:
        raise UploadRejected(UNSUPPORTED_TYPES[declared_type])

    name = safe_filename(filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension in UNSUPPORTED_EXTENSIONS:
        raise UploadRejected(UNSUPPORTED_TYPES[UNSUPPORTED_EXTENSIONS[extension]])
    from_extension = EXTENSIONS.get(extension)

    if from_extension is None and declared_type is None:
        raise UploadRejected(
            f"cannot tell what kind of file {name!r} is. Supported extensions: "
            f"{', '.join(sorted(EXTENSIONS))}; supported media types: "
            f"{', '.join(sorted(MEDIA_TYPES))}."
        )
    if from_extension is None:
        if declared_type not in MEDIA_TYPES:
            raise UploadRejected(
                f"media type {declared_type!r} is not supported. Supported: "
                f"{', '.join(sorted(MEDIA_TYPES))}."
            )
        return declared_type
    if declared_type is not None and declared_type != from_extension:
        if declared_type not in MEDIA_TYPES:
            raise UploadRejected(
                f"media type {declared_type!r} is not supported. Supported: "
                f"{', '.join(sorted(MEDIA_TYPES))}."
            )
        raise UploadRejected(
            f"the filename {name!r} says {from_extension} but the declared media type "
            f"is {declared_type}. They have to agree; neither is guessed at."
        )
    return from_extension


def decode(raw: bytes) -> str:
    """UTF-8 text from the uploaded bytes, or a refusal. Never lossy."""
    if not isinstance(raw, (bytes, bytearray)):
        raise UploadRejected("the upload body is not bytes")
    if not raw:
        raise UploadRejected("the upload is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            f"the upload is {len(raw)} bytes; the limit is {MAX_UPLOAD_BYTES} "
            f"({MAX_UPLOAD_BYTES // 1024} KiB)"
        )
    if b"\x00" in raw:
        raise UploadRejected(
            "the upload contains NUL bytes, so it is not the text file its type "
            "claims. Binary formats are not accepted."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadRejected(
            f"the upload is not valid UTF-8 ({exc.reason} at byte {exc.start}). It is "
            f"refused rather than decoded with replacements, because a replacement "
            f"character would put text in a citation that is not in your document."
        ) from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ------------------------------------------------------------------ the parse


def parse(text: str, media_type: str) -> ParsedUserDocument:
    """Paragraphs and a plain text whose offsets they index into."""
    if media_type not in MEDIA_TYPES:
        raise UploadRejected(f"{media_type!r} is not a supported media type")
    notes: list[str] = []
    if media_type in ("text/xml", "application/xml"):
        blocks = _xml_blocks(text)
        notes.append(
            "XML markup carries no heading vocabulary this engine knows, so no "
            "heading was read from it."
        )
    elif media_type == "text/markdown":
        blocks = _markdown_blocks(text)
    else:
        blocks = [(heading, body) for heading, body in _plain_blocks(text)]
        notes.append("plain text carries no headings, so none were read.")

    if not blocks:
        raise UploadRejected("no text was found in the upload")
    if len(blocks) > MAX_PARAGRAPHS:
        raise UploadRejected(
            f"the upload parses into {len(blocks)} paragraphs; the limit is "
            f"{MAX_PARAGRAPHS}. Split it into separate documents."
        )

    notes.append(
        f"paragraph_role is {FALLBACK_ROLE} for every paragraph: a user document's "
        f"own structure is not an FAA AD's, and this engine does not relabel it as one."
    )

    paragraphs: list[ParsedUserParagraph] = []
    chunks: list[str] = []
    cursor = 0
    for ordinal, (heading, body) in enumerate(blocks):
        block = "\n".join([heading, body]).strip() if heading else body.strip()
        if len(block) > MAX_PARAGRAPH_CHARS:
            raise UploadRejected(
                f"paragraph {ordinal + 1} is {len(block)} characters; the limit is "
                f"{MAX_PARAGRAPH_CHARS}. Break up the long block."
            )
        start = cursor
        end = start + len(block)
        chunks.append(block)
        cursor = end + 2
        paragraphs.append(
            ParsedUserParagraph(
                label=f"p{ordinal + 1}",
                heading=heading,
                role=FALLBACK_ROLE,
                text=block,
                char_start=start,
                char_end=end,
                ordinal=ordinal,
            )
        )

    plain_text = "\n\n".join(chunks)
    _assert_offsets_round_trip(plain_text, paragraphs)
    return ParsedUserDocument(
        media_type=media_type,
        plain_text=plain_text,
        paragraphs=paragraphs,
        notes=notes,
    )


def _assert_offsets_round_trip(
    plain_text: str, paragraphs: list[ParsedUserParagraph]
) -> None:
    """``plain_text[start:end]`` must equal the paragraph text, exactly.

    The same assertion ``engine.ingest.ad_xml`` makes about an AD, for the same
    reason: an offset that is one character out corrupts every citation built on
    the document, silently and unrecoverably.
    """
    for paragraph in paragraphs:
        span = plain_text[paragraph.char_start : paragraph.char_end]
        if span != paragraph.text:
            raise UploadRejected(
                f"internal offset error on paragraph {paragraph.label}: "
                f"plain_text[{paragraph.char_start}:{paragraph.char_end}] does not "
                f"match its text, so its citations would not resolve"
            )


def _clean_block(text: str) -> str:
    """Control characters out, trailing space off each line, blank lines gone."""
    cleaned = _CONTROL.sub("", text)
    lines = [line.rstrip() for line in cleaned.split("\n")]
    return "\n".join(line for line in lines if line.strip()).strip()


def _plain_blocks(text: str) -> list[tuple[str, str]]:
    """Blank-line separated blocks, with no heading read from any of them."""
    out: list[tuple[str, str]] = []
    for raw in _BLANK_LINE.split(text):
        body = _clean_block(raw)
        if body:
            out.append(("", body))
    return out


def _markdown_blocks(text: str) -> list[tuple[str, str]]:
    """Blocks, with an ATX heading attached to the block it introduces.

    A heading with no body under it is kept as a block of its own rather than
    merged into the next one: it is a section title the user wrote, and a
    citation to it should say so.
    """
    out: list[tuple[str, str]] = []
    pending = ""
    for raw in _BLANK_LINE.split(text):
        block = _clean_block(raw)
        if not block:
            continue
        lines = block.split("\n")
        match = _ATX_HEADING.match(lines[0])
        if match:
            heading = _CONTROL.sub("", match.group(2)).strip()
            body = "\n".join(lines[1:]).strip()
            if body:
                out.append((heading, body))
                pending = ""
            else:
                if pending:
                    out.append((pending, ""))
                pending = heading
            continue
        out.append((pending, block))
        pending = ""
    if pending:
        out.append((pending, ""))
    return [(h, b) for h, b in out if (h or b)]


def _xml_blocks(text: str) -> list[tuple[str, str]]:
    """Text blocks from XML, parsed with entities, DTDs and the network off.

    One block per element that carries its own text, in document order. The
    element's direct text is used -- its own ``.text`` plus the ``.tail`` of each
    child -- so nesting does not duplicate a passage into both the parent and
    the child block.
    """
    from lxml import etree

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        recover=False,
    )
    try:
        tree = etree.fromstring(text.encode("utf-8"), parser).getroottree()
    except etree.XMLSyntaxError as exc:
        raise UploadRejected(f"the XML did not parse: {exc}") from exc

    info = tree.docinfo
    if info.internalDTD is not None or info.externalDTD is not None:
        raise UploadRejected(
            "this XML declares a DTD. DTDs are refused outright: they are how a "
            "document reads a local file through an external entity, and how a "
            "few hundred bytes expand into gigabytes. Remove the DOCTYPE."
        )

    out: list[tuple[str, str]] = []
    for element in tree.getroot().iter():
        if not isinstance(element.tag, str):  # comment or processing instruction
            continue
        runs = [element.text or ""] + [child.tail or "" for child in element]
        body = _clean_block(" ".join(run for run in runs if run.strip()))
        if body:
            out.append(("", body))
    return out
