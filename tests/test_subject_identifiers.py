"""The question's own subject is not a claim about the paragraph it cites.

An answer to "does AD 2021-09-01 apply to N694AV?" has to name the AD and the
tail number, and neither can ever appear in the cited span: the AD number is the
document's identity rather than its body text, and a tail number lives in the
operator's fleet record and appears in no directive ever written. Requiring them
verbatim made every sentence that stated what the user asked about unverifiable
by construction, so the engine refused questions it had in fact decided.

The exemption is deliberately narrow, and these tests pin both halves of it:
identifiers the *question* resolved are exempt; every other digit-bearing term,
including a serial number -- which is an applicability fact the cited paragraph
really does have to carry -- is still required verbatim.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api.answer import resolve_quotes  # noqa: E402
from engine.retrieval.entities import Entities  # noqa: E402
from engine.verify.terms import subject_terms  # noqa: E402
from engine.verify.verifier import DROP_COVERAGE, DROP_NUMERIC, verify  # noqa: E402


@dataclass
class FakeHit:
    paragraph_id: str
    text: str
    char_start: int
    char_end: int
    ad_number: str = "2021-09-01"
    label: str = "c"
    role: str = "APPLICABILITY"
    heading: str = "Applicability"


PARA = (
    "This AD applies to all Airbus SAS Model A320-214 airplanes, serial numbers "
    "0981 through 1380 inclusive."
)
QUOTE = "This AD applies to all Airbus SAS Model A320-214 airplanes"

#: What the entity pass resolves from "Does AD 2021-09-01 apply to N694AV?"
ASKED = Entities(ad_numbers=["2021-09-01"], tail_numbers=["N694AV"])


def _hit(text: str = PARA, *, base: int = 500) -> FakeHit:
    return FakeHit(
        paragraph_id="2021-09-01#c", text=text, char_start=base, char_end=base + len(text)
    )


def _verdicts(sentence: str, *, subject=frozenset(), quote: str = QUOTE, para: str = PARA):
    h = _hit(para)
    sentences, unresolved = resolve_quotes(
        [{"text": sentence, "quotes": [{"paragraph_number": 1, "quote": quote}]}], [h]
    )
    assert not unresolved, f"the quote itself must be real: {unresolved}"
    return verify(sentences, {h.paragraph_id: h}, subject=subject).verdicts[0]


# ------------------------------------------- the subject is exempt, and only it


def test_naming_the_asked_ad_and_tail_number_no_longer_fails_the_numeric_gate():
    # Arrange: every claim in this sentence is in the quote except the two
    # identifiers, which name what was asked rather than what the span says.
    sentence = "AD 2021-09-01 applies to N694AV, an Airbus SAS Model A320-214 airplane."

    # Act
    verdict = _verdicts(sentence, subject=subject_terms(ASKED))

    # Assert
    assert verdict.kept, f"{verdict.reason}: {verdict.detail}"


def test_the_same_sentence_is_dropped_when_the_subject_is_not_supplied():
    """Pins that the exemption is what lets it through, not a looser threshold."""
    sentence = "AD 2021-09-01 applies to N694AV, an Airbus SAS Model A320-214 airplane."

    verdict = _verdicts(sentence)

    assert not verdict.kept
    assert verdict.reason == DROP_NUMERIC
    assert "2021-09-01" in verdict.detail and "n694av" in verdict.detail


def test_a_fabricated_model_suffix_is_still_dropped_with_the_subject_exempt():
    sentence = "AD 2021-09-01 applies to N694AV, an Airbus SAS Model A320-999 airplane."

    verdict = _verdicts(sentence, subject=subject_terms(ASKED))

    assert not verdict.kept
    assert verdict.reason == DROP_NUMERIC
    assert "a320-999" in verdict.detail


def test_a_serial_number_the_question_named_is_still_required_in_the_span():
    """Serials are applicability facts, not identity, so they are not exempt.

    The question may well name MSN 1224, but a sentence asserting that serial is
    making a claim the cited paragraph has to carry -- the range here is 0981
    through 1380, and "1224" appears nowhere in the span.
    """
    asked = Entities(ad_numbers=["2021-09-01"], serial_numbers=["1224"])
    sentence = "AD 2021-09-01 applies to Airbus SAS Model A320-214 serial number 1224."

    verdict = _verdicts(sentence, subject=subject_terms(asked))

    assert not verdict.kept
    assert verdict.reason == DROP_NUMERIC
    assert "1224" in verdict.detail


def test_a_sentence_that_is_only_its_subject_identifiers_claims_nothing():
    """The empty-claim rule survives: nothing left after the exemption is 0.0."""
    verdict = _verdicts("2021-09-01, N694AV.", subject=subject_terms(ASKED))

    assert not verdict.kept
    assert verdict.reason == DROP_COVERAGE


# --------------------------------------------------- what subject_terms reads


def test_subject_terms_reads_only_identity_kinds_and_only_digit_bearing_tokens():
    asked = Entities(
        ad_numbers=["2021-09-01"],
        docket_ids=["FAA-2026-11814"],
        amendments=["39-21558"],
        tail_numbers=["N694AV"],
        serial_numbers=["1224"],
        models=["A320-214"],
        manufacturers=["Airbus SAS"],
    )

    terms = subject_terms(asked)

    assert terms == {"2021-09-01", "faa-2026-11814", "39-21558", "n694av"}


def test_subject_terms_of_an_empty_entity_pass_exempts_nothing():
    assert subject_terms(Entities()) == frozenset()


# ------------------------------------------- the exemption cuts both ways


def test_an_identifier_present_in_the_span_stops_inflating_coverage():
    """Removing the subject from *both* sides of the ratio is the whole point.

    AD prose does sometimes print its own number, and when it does, the old
    scoring counted that as a matched content term -- free coverage on a term
    that was never a claim. A sentence whose support came mostly from its own
    identifier was not well supported, and now reads that way: the exemption
    makes the test stricter here, which is the same principle that makes it
    looser when the identifier is absent, not an exception to it.
    """
    span = "This AD 2021-09-01 requires a records check."
    sentence = "AD 2021-09-01 requires a borescope inspection of the turbine disc."

    lenient = _verdicts(sentence, quote=span, para=span)
    exempt = _verdicts(sentence, subject=subject_terms(ASKED), quote=span, para=span)

    assert lenient.coverage > exempt.coverage
    assert exempt.reason == DROP_COVERAGE
