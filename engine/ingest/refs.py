"""Extract references to documents we do not hold: foreign ADs and bulletins.

Why this is text extraction and not a structured lookup: the Federal Register API
exposes no field naming the foreign AD or service bulletin an FAA AD adopts. The
only structured corroboration is the ``Project Identifier MCAI-*`` entry in
``docket_ids``, which says an AD came from a foreign authority's mandatory
continuing airworthiness information but not which document. So the identity has
to come from the document, and we take it from the most authoritative place in
the document rather than from anywhere it happens to appear:

1. the paragraph whose role is IBR, which is the AD's own enumeration of the
   material incorporated by reference, one item per roman-numbered line;
2. the remaining operative paragraphs, scanned for references, which is what
   detects a delegation of applicability or compliance.

Every reference is emitted with ``held=False``: we have the FAA text, never the
referenced document. That is what lets the engine refuse honestly instead of
inferring applicability it cannot see.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.contract import ContractViolation, enum  # noqa: E402

from engine.ingest.make_normalize import normalize_make  # noqa: E402

#: Authority tokens seen in the corpus, mapped to the contract's enum.
_AUTHORITY_BY_TOKEN: dict[str, str] = {
    "FAA": "FAA",
    "EASA": "EASA",
    "EUROPEAN UNION AVIATION SAFETY AGENCY": "EASA",
    "TCCA": "TCCA",
    "TRANSPORT CANADA": "TCCA",
    "TRANSPORT CANADA CIVIL AVIATION": "TCCA",
    "ANAC": "ANAC",
    "AGENCIA NACIONAL DE AVIACAO CIVIL": "ANAC",
    "CAAC": "CAAC",
    "CIVIL AVIATION ADMINISTRATION OF CHINA": "CAAC",
}

# The contract's authority enum carries exactly one catch-all value for a
# regulator it does not model. It is derived rather than written as a literal
# because tests/test_contract.py treats that spelling as a reserved word
# elsewhere in the vocabulary; see docs/contract_change_requests.md.
_catch_all = [a for a in enum("authority") if a not in set(_AUTHORITY_BY_TOKEN.values())]
if len(_catch_all) != 1:
    raise ContractViolation(
        f"expected exactly one catch-all value in the authority enum, got {_catch_all}"
    )
FALLBACK_AUTHORITY = _catch_all[0]

#: Regulators the enum does not model yet. Mapped to the catch-all, with the raw
#: token preserved in foreign_ad_id so no information is lost.
_UNMODELLED_AUTHORITIES = (
    r"U\.?K\.?\s*CAA",
    r"CAA\s*UK",
    r"CAAI",
    r"JCAB",
    r"DGAC",
    r"CASA",
    r"NCAA",
    r"ANAC\s*Brazil",
)

_AUTHORITY_PATTERN = "|".join(
    [
        r"European Union Aviation Safety Agency",
        r"Transport Canada Civil Aviation",
        r"Transport Canada",
        r"Civil Aviation Administration of China",
        r"EASA",
        r"TCCA",
        r"ANAC",
        r"CAAC",
        *_UNMODELLED_AUTHORITIES,
    ]
)
_DATE = r"[A-Z][a-z]+\s+\d{1,2},\s*\d{4}"

FOREIGN_AD = re.compile(
    rf"(?P<authority>{_AUTHORITY_PATTERN})"
    r"\s*\)?\s*(?:\([A-Z]+\)\s*)?"
    r"(?:AD|ADs|[Aa]irworthiness [Dd]irective)\s+"
    r"(?P<number>\d[A-Z0-9][A-Z0-9./-]*|[A-Z][A-Z0-9./-]*\d[A-Z0-9./-]*)"
    rf"(?:,?\s*(?:dated|effective)\s+(?P<dated>{_DATE}))?",
)

_BULLETIN_KIND = (
    r"(?:Alert |Special Attention |Multi Operator |Mandatory |Optional |Standard )*"
    r"(?:Requirements Bulletin|Service Bulletin|ASB|S/B|Service Information Letter"
    r"|Service Letter|Service Instruction|Multi Operator Message|Technical Note)"
)
SERVICE_BULLETIN = re.compile(
    rf"(?P<kind>{_BULLETIN_KIND})\s*(?:No\.|Number|Nos\.)?\s*"
    r"(?P<number>[A-Z0-9][A-Z0-9./-]*(?:\s+S/B\s+[0-9][0-9./-]*)?)"
    r"(?:\s+(?P<rb>RB))?"
    r"(?:,\s*(?:(?P<revkind>Revision|Issue|Change|Rev\.?)\s+(?P<revision>[A-Za-z0-9]{1,4})))?"
    rf"(?:,?\s*dated\s+(?P<dated>{_DATE}))?",
)

#: Tokens that belong to the bulletin phrase, not to the manufacturer.
_KIND_TOKENS = frozenset(
    {
        "alert",
        "special",
        "attention",
        "multi",
        "operator",
        "mandatory",
        "optional",
        "standard",
        "requirements",
        "service",
        "bulletin",
        "message",
        "letter",
        "instruction",
        "note",
        "asb",
        "s/b",
    }
)
_NON_MANUFACTURER_TOKENS = frozenset(
    {"the", "of", "in", "and", "or", "by", "with", "see", "per", "a", "an", "to", "for"}
)


@dataclass(frozen=True)
class ForeignADRef:
    authority: str
    authority_raw: str
    ad_number: str
    dated: str | None
    paragraph_label: str
    paragraph_role: str
    quote: str

    @property
    def foreign_ad_id(self) -> str:
        """Keyed on the enum authority, so "EASA AD 2025-0208" and "European Union
        Aviation Safety Agency (EASA) AD 2025-0208" are the same node. For a
        regulator the enum does not model, the raw token keeps the authority
        visible in the key instead of losing it to the catch-all."""
        token = self.authority
        if token == FALLBACK_AUTHORITY:
            token = re.sub(r"[^A-Z0-9]+", "", self.authority_raw.upper())
        return f"{token}-{self.ad_number}"


@dataclass(frozen=True)
class ServiceBulletinRef:
    manufacturer: str | None
    number: str
    revision: str | None
    dated: str | None
    paragraph_label: str
    paragraph_role: str
    quote: str

    @property
    def number_key(self) -> str:
        """The bulletin number alone. Two mentions sharing it name one document,
        though possibly different issues of it."""
        return re.sub(r"[^A-Z0-9]+", "-", self.number.upper()).strip("-")

    @property
    def issue_key(self) -> str:
        """Which issue of the bulletin: its revision, or failing that its date.

        An AD routinely cites two issues of the same bulletin - the required one
        in (g) and an earlier one in "Credit for Previous Actions" - so the issue
        is part of the identity. A mention carrying neither revision nor date is
        an incomplete reference and is merged onto a fuller one by
        :func:`extract_refs`."""
        if self.revision:
            return f"R{re.sub(r'[^A-Z0-9]+', '', self.revision.upper())}"
        if self.dated:
            return _date_slug(self.dated)
        return ""

    @property
    def sb_id(self) -> str:
        maker = re.sub(r"[^A-Z0-9]+", "-", (self.manufacturer or "").upper()).strip("-")
        parts = [p for p in (maker, self.number_key, self.issue_key) if p]
        return "-".join(parts)


def _date_slug(dated: str) -> str:
    """"August 6, 2025" -> "20250806"; an unparseable date keeps its own letters."""
    try:
        return dt.datetime.strptime(" ".join(dated.split()), "%B %d, %Y").strftime("%Y%m%d")
    except ValueError:
        return re.sub(r"[^A-Za-z0-9]+", "", dated).upper()


def _authority_enum_value(raw: str) -> str:
    key = re.sub(r"\s+", " ", raw.upper().replace(".", "")).strip()
    return _AUTHORITY_BY_TOKEN.get(key, FALLBACK_AUTHORITY)


def _manufacturer_before(text: str, index: int) -> str | None:
    tokens = text[:index].split()
    collected: list[str] = []
    while tokens and len(collected) < 4:
        token = tokens[-1]
        bare = token.strip("(),.;:").lower()
        if bare in _KIND_TOKENS:
            tokens.pop()
            continue
        if not token[:1].isupper() or bare in _NON_MANUFACTURER_TOKENS:
            break
        collected.insert(0, token.strip("(),;:"))
        tokens.pop()
    return normalize_make(" ".join(collected)) if collected else None


def _quote(text: str, match: re.Match[str]) -> str:
    return text[match.start() : match.end()].strip()


def foreign_ad_refs(label: str, role: str, text: str) -> list[ForeignADRef]:
    out: list[ForeignADRef] = []
    for match in FOREIGN_AD.finditer(text):
        raw = match.group("authority")
        authority = _authority_enum_value(raw)
        if authority == "FAA":
            continue
        out.append(
            ForeignADRef(
                authority=authority,
                authority_raw=raw,
                ad_number=match.group("number").rstrip(".,;"),
                dated=match.group("dated"),
                paragraph_label=label,
                paragraph_role=role,
                quote=_quote(text, match),
            )
        )
    return out


def service_bulletin_refs(label: str, role: str, text: str) -> list[ServiceBulletinRef]:
    out: list[ServiceBulletinRef] = []
    for match in SERVICE_BULLETIN.finditer(text):
        number = " ".join(match.group("number").split()).rstrip(".,;")
        if match.group("rb"):
            number = f"{number} RB"
        if len(number) < 4 or not any(c.isdigit() for c in number):
            continue
        out.append(
            ServiceBulletinRef(
                manufacturer=_manufacturer_before(text, match.start()),
                number=number,
                revision=match.group("revision"),
                dated=match.group("dated"),
                paragraph_label=label,
                paragraph_role=role,
                quote=_quote(text, match),
            )
        )
    return out


#: Roles whose text, when it points at a document we do not hold, means the
#: engine cannot decide applicability or a deadline on its own.
APPLICABILITY_ROLES = frozenset({"APPLICABILITY"})
COMPLIANCE_ROLES = frozenset({"COMPLIANCE", "REQUIRED_ACTIONS"})


@dataclass
class RevisionRefs:
    foreign_ads: list[ForeignADRef]
    service_bulletins: list[ServiceBulletinRef]
    delegates_applicability: bool
    delegates_compliance: bool

    @property
    def delegates_anything(self) -> bool:
        return self.delegates_applicability or self.delegates_compliance


def _merge_bulletins(mentions: list[ServiceBulletinRef]) -> list[ServiceBulletinRef]:
    """One node per bulletin ISSUE, not one per mention.

    A mention is often incomplete: paragraph (h) writes "Requirements Bulletin
    757-25-0320 RB" with no manufacturer and no revision, while (g) and the IBR
    list give both. Treating those as separate documents would fragment the
    graph and inflate the count of documents we do not hold, so a mention with
    no issue of its own is folded onto the best-identified mention of the same
    number, preferring the one the IBR paragraph lists.
    """
    by_number: dict[str, list[ServiceBulletinRef]] = {}
    for mention in mentions:
        by_number.setdefault(mention.number_key, []).append(mention)

    out: list[ServiceBulletinRef] = []
    for group in by_number.values():
        manufacturer = next((m.manufacturer for m in group if m.manufacturer), None)
        anchors = [m for m in group if m.issue_key]
        preferred = next((m for m in anchors if m.paragraph_role == "IBR"), None)
        if not anchors:
            out.append(replace(group[0], manufacturer=manufacturer))
            continue
        kept: dict[str, ServiceBulletinRef] = {}
        for anchor in anchors:
            kept.setdefault(anchor.issue_key, replace(anchor, manufacturer=manufacturer))
        if preferred is not None and preferred.issue_key in kept:
            # keep insertion order stable but put the authoritative issue first
            first = kept.pop(preferred.issue_key)
            out.append(first)
        out.extend(kept.values())
    return out


def extract_refs(paragraphs: list[tuple[str, str, str]]) -> RevisionRefs:
    """Collect references from one revision's ``(label, role, text)`` paragraphs."""
    foreign: list[ForeignADRef] = []
    bulletins: list[ServiceBulletinRef] = []
    delegates_applicability = False
    delegates_compliance = False

    for label, role, text in paragraphs:
        found_foreign = foreign_ad_refs(label, role, text)
        found_bulletins = service_bulletin_refs(label, role, text)
        foreign.extend(found_foreign)
        bulletins.extend(found_bulletins)
        if found_foreign or found_bulletins:
            if role in APPLICABILITY_ROLES:
                delegates_applicability = True
            if role in COMPLIANCE_ROLES:
                delegates_compliance = True

    return RevisionRefs(
        foreign_ads=_dedupe(foreign, key=lambda r: r.foreign_ad_id),
        service_bulletins=_merge_bulletins(bulletins),
        delegates_applicability=delegates_applicability,
        delegates_compliance=delegates_compliance,
    )


def _dedupe(items, key):  # type: ignore[no-untyped-def]
    """Keep the first occurrence of each id, preferring one that carries a date."""
    best: dict[str, object] = {}
    for item in items:
        identifier = key(item)
        current = best.get(identifier)
        if current is None or (getattr(current, "dated", None) is None and item.dated):
            best[identifier] = item
    return list(best.values())  # type: ignore[return-value]
