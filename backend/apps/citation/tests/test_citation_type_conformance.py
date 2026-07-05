"""The citation-type conformance harness.

The type axis's counterpart to ``tests/schemes/test_conformance.py``:
parametrized over the type registry, so **every registered citation type
passes through automatically** — a new type enrolls just by being
registered, and the coherence of the code its author wrote (the locator
grammar) is verified by the framework, not by hand-written per-type tests.
Type-specific grammar details (video's colon forms, the 100-hour cap) still
belong to the type's own tests; this harness checks only the contract
invariants shared code relies on.

Pure — no database.
"""

import inspect

import pytest

from apps.citation.citation_types import (
    CITATION_TYPE_SPECS,
    CitationTypeSpec,
    SchemeSpec,
    SourceType,
    citation_type_driver,
)

# Structured values every value-carrying grammar must round-trip: sub-minute,
# minutes, an exact hour and an hour-plus value.
SAMPLE_VALUES = (1, 95, 3600, 3723)


def test_citation_type_spec_record_carries_no_logic() -> None:
    """The type spec is a record: fields only, behavior lives elsewhere.

    A citation type is *allowed* real programming — in its module's functions
    and its ``LocatorContract`` callables — but the ``CitationTypeSpec``
    record the registry and codegen read stays pure field data, so nothing
    consumed as a fact is secretly computed. (Class-valued defaults like
    ``scheme_spec_type`` are data, hence the function/property check rather
    than a blanket callable check.)
    """
    offenders = [
        name
        for name, value in vars(CitationTypeSpec).items()
        if not name.startswith("__")
        and (inspect.isfunction(value) or isinstance(value, property))
    ]
    assert offenders == [], (
        f"CitationTypeSpec declares logic ({offenders}); the record stays fields-only"
    )


# Parametrized by SourceType member so test ids read as the type names.
@pytest.fixture(params=list(CITATION_TYPE_SPECS))
def spec(request: pytest.FixtureRequest) -> CitationTypeSpec:
    return CITATION_TYPE_SPECS[request.param]


class TestCitationTypeConformance:
    def test_locator_value_bridge_is_both_or_neither(self, spec):
        """``parse_value`` and ``format_value`` come as a pair.

        A parser without a formatter strands recognition hints (nothing can
        render them as locator text); a formatter without a parser mints
        locator text nothing can turn back into a value.
        """
        assert (spec.locator.parse_value is None) == (
            spec.locator.format_value is None
        ), f"{spec.source_type}: parse_value/format_value must come as a pair"

    def test_locator_kind_matches_the_value_bridge(self, spec):
        """``timestamp`` kinds carry a value bridge; ``freeform`` kinds don't.

        The kind drives the frontend input behavior, the bridge drives the
        deep-link/hint weaves — a type where they disagree validates one
        grammar client-side and runs another server-side.
        """
        has_bridge = spec.locator.parse_value is not None
        assert (spec.locator.kind == "timestamp") == has_bridge, (
            f"{spec.source_type}: kind {spec.locator.kind!r} disagrees with "
            f"the value bridge"
        )

    def test_value_grammar_round_trips(self, spec):
        """``parse_value(format_value(v))`` is identity for structured values.

        The weaves depend on it: a recognition hint is formatted to prefill
        the locator stage, and the stored text is parsed back for the deep
        link — a lossy grammar corrupts the cited moment.
        """
        parse, fmt = spec.locator.parse_value, spec.locator.format_value
        if parse is None or fmt is None:
            pytest.skip("type has no structured locator value")
        for value in SAMPLE_VALUES:
            assert parse(fmt(value)) == value

    def test_normalize_accepts_and_stabilizes_canonical_text(self, spec):
        """``normalize`` accepts the grammar's own canonical output, stably.

        Formatted values must survive the write-path validation unchanged —
        otherwise a prefilled hint fails the type's own validation on save.
        """
        fmt = spec.locator.format_value
        if fmt is None:
            pytest.skip("type has no structured locator value")
        for value in SAMPLE_VALUES:
            canonical = fmt(value)
            assert spec.locator.normalize(canonical) == canonical

    def test_grammar_types_declare_an_invalid_message(self, spec):
        """A type whose ``normalize`` can reject must tell contributors how."""
        if spec.locator.kind == "freeform":
            pytest.skip("freeform locators never reject")
        assert spec.locator.invalid_message.strip(), (
            f"{spec.source_type}: a rejecting grammar needs a contributor-facing "
            f"invalid_message"
        )

    def test_locator_placeholder_is_present(self, spec):
        assert spec.locator.placeholder.strip()

    def test_scheme_spec_type_is_a_scheme_contract(self, spec):
        """The composition contract's static face: a real ``SchemeSpec`` class."""
        assert issubclass(spec.scheme_spec_type, SchemeSpec)

    def test_type_driver_wraps_the_registered_spec(self, spec):
        """The framework driver resolves from a raw field value to this spec."""
        driver = citation_type_driver(str(spec.source_type))
        assert driver.spec is spec

    def test_driver_value_methods_are_total(self, spec):
        """Driver parse/format never raise on bridgeless types — they abstain."""
        driver = citation_type_driver(spec.source_type)
        if spec.locator.parse_value is None:
            assert driver.parse_locator_value("1:35") is None
            assert driver.format_locator_value(95) is None
        else:
            assert driver.parse_locator_value("not a value") is None
            formatted = driver.format_locator_value(95)
            assert formatted is not None
            assert driver.parse_locator_value(formatted) == 95


def test_every_source_type_has_a_driver() -> None:
    assert {spec.source_type for spec in CITATION_TYPE_SPECS.values()} == set(
        SourceType
    )
