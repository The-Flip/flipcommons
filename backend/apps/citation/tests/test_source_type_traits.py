"""Tests for the source-type trait table (``apps.citation.source_type_traits``).

Pure data plus a coercing accessor — no database.
"""

import pytest

from apps.citation.source_type_traits import (
    SOURCE_TYPE_TRAITS,
    SourceType,
    _assert_exhaustive_traits,
    source_type_traits,
)


class TestSourceTypeTraits:
    @pytest.mark.parametrize(
        ("source_type", "flat", "abstract", "skips_locator"),
        [
            (SourceType.BOOK, False, False, False),
            (SourceType.MAGAZINE, False, True, False),
            (SourceType.WEB, True, True, True),
        ],
    )
    def test_traits_per_type(self, source_type, flat, abstract, skips_locator):
        traits = source_type_traits(source_type)
        assert traits.flat_hierarchy is flat
        assert traits.parentless_abstract is abstract
        assert traits.child_skips_locator is skips_locator

    def test_accessor_coerces_a_raw_field_string(self):
        # A model's ``source_type`` CharField arrives as a plain ``str``.
        assert source_type_traits("web") == SOURCE_TYPE_TRAITS[SourceType.WEB]

    def test_accessor_rejects_an_unknown_value(self):
        with pytest.raises(ValueError, match="not a valid SourceType"):
            source_type_traits("podcast")


class TestExhaustivenessHelper:
    def test_passes_on_the_complete_registry(self):
        _assert_exhaustive_traits(SOURCE_TYPE_TRAITS)  # does not raise

    def test_raises_on_a_missing_type(self):
        incomplete = {SourceType.BOOK: SOURCE_TYPE_TRAITS[SourceType.BOOK]}
        with pytest.raises(AssertionError, match="missing a trait row"):
            _assert_exhaustive_traits(incomplete)
