"""Diacritic-folding search primitives shared across apps.

The catalog listing pages tuned diacritic-insensitive matching once
(``apps.catalog.api._facet_helpers``); the autocomplete engine
(``apps.core.autocomplete``) needs the same behavior, so the reusable
primitives live here in ``core``:

- :func:`fold` — Python-side NFD accent-strip + lowercase, applied to the
  *query term*.
- :class:`Unaccent` — a registered ``__unaccent__`` transform applied to the
  *column*, so ``path__unaccent__icontains=fold(q)`` de-accents both sides on
  Postgres. Importing this module registers it on ``CharField`` / ``TextField``.

Both sides folded means ``q=pokemon`` matches ``Pokémon`` *and* ``q=pokémon``
matches ``Pokemon``. The transform emits ``UNACCENT(...)`` SQL, which only
exists on Postgres (the ``unaccent`` extension, enabled DB-wide); callers gate
on ``connection.vendor`` and fall back to plain ``icontains`` on SQLite, the
same dev/prod gap the listing pages have.
"""

from __future__ import annotations

import unicodedata

from django.db.models import CharField, TextField, Transform


def fold(text: str) -> str:
    """Diacritic-fold + lowercase a query term to match ``UNACCENT(field)``.

    NFD decomposition + stripping combining marks ≈ Postgres ``unaccent`` for
    Latin scripts; lowercasing pairs with the case-insensitive ``icontains``.
    """
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.lower()


class Unaccent(Transform):
    """Postgres ``unaccent(text)`` as a registered ``__unaccent__`` transform.

    Lets a lookup spell the column-side fold inline:
    ``name__unaccent__icontains=fold(q)``. Emits ``UNACCENT(...)`` SQL, so it
    must only reach the database on Postgres — callers branch on
    ``connection.vendor`` and never build an ``__unaccent__`` lookup on SQLite.
    """

    function = "UNACCENT"
    lookup_name = "unaccent"
    output_field = TextField()


# Register at import so ``path__unaccent__icontains`` resolves once this module
# loads — the engine triggers that by importing ``fold``. Covering both base
# text field types reaches ``CharField`` (most name columns) and ``TextField``.
CharField.register_lookup(Unaccent)
TextField.register_lookup(Unaccent)
