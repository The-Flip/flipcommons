"""Unit tests for the shared diacritic-folding primitives in ``apps.core.search``.

``fold`` is the Python-side accent-strip applied to the query term; the
``Unaccent`` transform (column side) is exercised end-to-end against Postgres by
the autocomplete and listing tests. Here we pin ``fold``'s pure contract.
"""

from __future__ import annotations

from apps.core.search import fold


def test_fold_strips_diacritics_and_lowercases() -> None:
    assert fold("Pokémon") == "pokemon"
    assert fold("MONTRÉAL") == "montreal"
    assert fold("São Paulo") == "sao paulo"
    # Punctuation is intentionally NOT folded (matches the listing's contract).
    assert fold("AC/DC") == "ac/dc"
