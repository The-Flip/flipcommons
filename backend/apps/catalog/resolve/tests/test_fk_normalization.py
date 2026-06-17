"""Unit tests for the single FK-value normalization.

``normalize_fk_value`` is the one definition catalog's FK-*resolution* lookups
share (:func:`_resolve_fk_generic` at apply time, ``_lookup_pk`` at build time),
so a padded or non-string value can't normalize one way and look up another.
"""

from __future__ import annotations

from apps.catalog.resolve._helpers import normalize_fk_value


def test_trims_surrounding_whitespace():
    assert normalize_fk_value(" stern-pinball-inc ") == "stern-pinball-inc"


def test_casts_non_string_to_str():
    # YAML can parse a slug-like value as an int; resolution str-casts it.
    assert normalize_fk_value(1234) == "1234"


def test_falsy_and_blank_resolve_to_none():
    assert normalize_fk_value(None) is None
    assert normalize_fk_value("") is None
    assert normalize_fk_value("   ") is None
    assert normalize_fk_value(0) is None


def test_already_canonical_value_unchanged():
    assert normalize_fk_value("williams-electronics") == "williams-electronics"
