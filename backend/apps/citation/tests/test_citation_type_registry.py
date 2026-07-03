"""Tests for the citation-type/scheme registry (``apps.citation.citation_types``).

Pure data plus a coercing accessor and coherence assertions — no database.
The per-scheme behavioral contract is covered separately by
``test_scheme_conformance.py``.
"""

import pytest

from apps.citation.citation_types import (
    CITATION_TYPE_SPECS,
    SCHEME_SPECS,
    SourceType,
    citation_type_spec,
    identifier_key_choices,
    identifier_key_values,
    scheme_source_type_pairs,
)
from apps.citation.citation_types.registry import _assert_registry_coherent


class TestCitationTypeSpecs:
    @pytest.mark.parametrize(
        ("source_type", "flat", "abstract", "skips_locator"),
        [
            (SourceType.BOOK, False, False, False),
            (SourceType.MAGAZINE, False, True, False),
            (SourceType.WEB, True, True, True),
        ],
    )
    def test_traits_per_type(self, source_type, flat, abstract, skips_locator):
        spec = citation_type_spec(source_type)
        assert spec.flat_hierarchy is flat
        assert spec.parentless_abstract is abstract
        assert spec.child_skips_locator is skips_locator

    def test_accessor_coerces_a_raw_field_string(self):
        # A model's ``source_type`` CharField arrives as a plain ``str``.
        assert citation_type_spec("web") == CITATION_TYPE_SPECS[SourceType.WEB]

    def test_accessor_rejects_an_unknown_value(self):
        with pytest.raises(ValueError, match="not a valid SourceType"):
            citation_type_spec("podcast")

    def test_label_comes_from_the_choice(self):
        assert citation_type_spec("web").label == "Web"


class TestSchemeRegistry:
    def test_identifier_key_values_are_the_scheme_keys(self):
        assert identifier_key_values() == list(SCHEME_SPECS)

    def test_identifier_key_choices_pair_key_and_label(self):
        assert identifier_key_choices() == [
            (spec.key, spec.label) for spec in SCHEME_SPECS.values()
        ]

    def test_mapping_keys_match_spec_keys(self):
        for key, spec in SCHEME_SPECS.items():
            assert key == spec.key

    def test_scheme_source_type_pairs_bind_key_to_owning_type(self):
        assert scheme_source_type_pairs() == [
            ("ipdb", "web"),
            ("opdb", "web"),
            ("youtube", "video"),
        ]


class TestCoherenceHelper:
    def test_passes_on_the_real_registry(self):
        _assert_registry_coherent(CITATION_TYPE_SPECS, SCHEME_SPECS)  # does not raise

    def test_raises_on_a_missing_type(self):
        incomplete = {SourceType.BOOK: CITATION_TYPE_SPECS[SourceType.BOOK]}
        with pytest.raises(AssertionError, match="missing a type spec"):
            _assert_registry_coherent(incomplete, SCHEME_SPECS)
