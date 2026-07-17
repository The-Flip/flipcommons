"""Unit tests for FK-value handling at both boundaries.

``normalize_fk_value`` canonicalizes *authored* public_id references (patch
YAML, API payloads) before they resolve to PKs via ``resolve_fk_target_pk``.
``_resolve_fk_generic`` is the apply-time side: it reads the integer PK a
persisted claim value carries and never sees public_id strings.
"""

from __future__ import annotations

from apps.catalog.models import MachineModel
from apps.catalog.resolve._helpers import _resolve_fk_generic
from apps.provenance.claims import normalize_fk_value


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


class TestResolveFkGenericValueShape:
    """Apply-time PK handling, exercised via the prefetched-lookup path (no DB)."""

    def test_clear_sentinels_resolve_to_none(self):
        assert (
            _resolve_fk_generic(MachineModel, "display_type", None, lookup={}) is None
        )
        assert _resolve_fk_generic(MachineModel, "display_type", "", lookup={}) is None

    def test_non_int_value_resolves_to_none(self):
        # Pre-migration slug strings (or bools) never resolve — the write
        # paths enforce int PKs, so this only guards legacy/buggy data.
        assert (
            _resolve_fk_generic(MachineModel, "display_type", "dot-matrix", lookup={})
            is None
        )
        assert (
            _resolve_fk_generic(MachineModel, "display_type", True, lookup={}) is None
        )

    def test_missing_target_resolves_to_none(self):
        assert _resolve_fk_generic(MachineModel, "display_type", 42, lookup={}) is None
