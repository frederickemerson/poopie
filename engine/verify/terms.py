"""Content-term extraction and overlap, the verifier's support test.

The verifier has to answer one question per sentence: *is this sentence's content
actually present in the paragraph it cites?* The method is deliberately dumb and
fully inspectable -- no model, no embedding, no similarity score whose value
nobody can explain in a review.

Three decisions, each with a reason:

1. **Content terms, not all tokens.** Function words carry no claim, and keeping
   them inflates overlap towards 1.0 for any fluent sentence, which is exactly
   the failure a support test must not have. The stopword list is standard
   English function words only; no AD-domain words are removed, because removing
   domain words would be tuning the test to the corpus.

2. **A deterministic suffix stripper, applied to both sides.** "requires" must
   match "required" or every faithful paraphrase gets dropped. The stripper is a
   fixed rule list, applied identically to the sentence and to the cited span,
   so it cannot favour either. It is not a real stemmer and does not try to be.

3. **Digit-bearing terms are required, not averaged.** A deadline, a serial
   range, a part number or a model suffix is the content most likely to be
   hallucinated and the most dangerous when it is. ``numeric_support`` therefore
   demands that *every* digit-bearing term in the sentence appear in the cited
   span. A sentence inventing "within 14 months" over a paragraph that says
   "within 10 months" fails outright and no overlap score can rescue it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[0-9a-z][0-9a-z./\-]*", re.IGNORECASE)
_HAS_DIGIT = re.compile(r"\d")

#: Standard English function words. Nothing domain-specific is listed here on
#: purpose: a stopword list tuned to AD prose would be tuning the support test.
STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be because
    been before being below between both but by can cannot could did do does doing
    down during each few for from further had has have having he her here hers him his
    how i if in into is it its itself just me more most must my no nor not of off on
    once only or other our out over own same she should so some such than that the
    their them then there these they this those through to too under until up very was
    we were what when where which while who whom why will with would you your""".split()
)

#: Ordered suffix rules. Longest first so "ations" is tried before "s".
_SUFFIXES: tuple[tuple[str, int], ...] = (
    ("ations", 6),
    ("ition", 5),
    ("ments", 5),
    ("ingly", 5),
    ("ation", 5),
    ("ement", 5),
    ("ness", 4),
    ("ings", 4),
    ("able", 4),
    ("ible", 4),
    ("ment", 4),
    ("ies", 3),
    ("ing", 3),
    ("ers", 3),
    ("ed", 2),
    ("es", 2),
    ("er", 2),
    ("ly", 2),
    ("s", 1),
)
#: Below this length a stem is not shortened further; "does" must not become "do".
_MIN_STEM = 4


def stem(token: str) -> str:
    """Strip one known suffix, if the remainder is still a plausible stem.

    Deterministic and symmetric: the same token always yields the same stem, and
    both sides of a comparison go through this function.
    """
    if _HAS_DIGIT.search(token):
        return token
    for suffix, length in _SUFFIXES:
        if token.endswith(suffix) and len(token) - length >= _MIN_STEM:
            return token[: -length]
    return token


def content_terms(text: str, *, use_stem: bool = True) -> set[str]:
    """Stemmed content terms of a span: no function words, no bare punctuation."""
    out: set[str] = set()
    for match in _TOKEN.finditer(text):
        token = match.group(0).strip("./-").casefold()
        if not token or token in STOPWORDS:
            continue
        if len(token) < 2 and not _HAS_DIGIT.search(token):
            continue
        out.add(stem(token) if use_stem else token)
    return out


def numeric_terms(text: str) -> set[str]:
    """Digit-bearing content terms: dates, deadlines, models, serials, part numbers."""
    return {t for t in content_terms(text, use_stem=False) if _HAS_DIGIT.search(t)}


@dataclass(frozen=True)
class Overlap:
    """Why a sentence passed or failed, in numbers a reviewer can re-derive."""

    coverage: float
    sentence_terms: int
    matched_terms: int
    missing_terms: tuple[str, ...]
    missing_numeric: tuple[str, ...]

    @property
    def numeric_support(self) -> bool:
        return not self.missing_numeric


def overlap(sentence: str, cited: str) -> Overlap:
    """Fraction of the sentence's content terms present in the cited span.

    A sentence with no content terms at all ("It does." or a bare connective)
    has coverage 0.0, not 1.0: an empty claim is not a supported claim, and
    treating it as supported would let filler through unchecked.
    """
    sent = content_terms(sentence)
    src = content_terms(cited)
    if not sent:
        return Overlap(0.0, 0, 0, (), ())
    matched = sent & src
    missing = sent - src
    missing_numeric = tuple(
        sorted(numeric_terms(sentence) - numeric_terms(cited))
    )
    return Overlap(
        coverage=len(matched) / len(sent),
        sentence_terms=len(sent),
        matched_terms=len(matched),
        missing_terms=tuple(sorted(missing)),
        missing_numeric=missing_numeric,
    )
