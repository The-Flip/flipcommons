"""The description tier for global search (``GET /api/pages/search``).

Global search ranks results in two tiers: name/alias matches first, then rows
matched only by their long-form ``description``. The description tier is added
**here, in the section builders only** — deliberately kept out of the shared
``q`` predicate that the listing pages and the record-creation ``query_count``
gate reuse, so searching a description can never make the "create this record?"
prompt disappear.

The tier is model-driven: ``description`` comes from the shared
:class:`DescribedModel` mixin, so :func:`tiered_search_rows` gates on
``issubclass(model, DescribedModel)`` — any describable entity in global search
gets it automatically, a non-describable one is skipped.

Lives in the catalog API layer (not next to the ``fold`` primitives in
``apps.core.search``) because the capability check imports ``DescribedModel``,
and ``apps.core.search`` is a core-only leaf that must not import
``apps.core.models`` (enforced by import-linter).
"""

from __future__ import annotations

from typing import NamedTuple

from django.db import connection
from django.db.models import Model, Q, QuerySet

from apps.core.models.mixins import DescribedModel
from apps.core.search import fold


def description_match_q(q: str) -> Q:
    """Folded substring predicate on :attr:`DescribedModel.description`.

    Postgres de-accents both sides (``UNACCENT(description) ILIKE unaccented``,
    mirroring the autocomplete engine); SQLite (dev/CI) falls back to plain
    ``icontains`` — the same dev/prod gap as the rest of search. Matches the raw
    markdown source of the ``MarkdownField``, not the rendered HTML.
    """
    if connection.vendor == "postgresql":
        return Q(description__unaccent__icontains=fold(q))
    return Q(description__icontains=q)


class TieredRows[ModelT: Model](NamedTuple):
    """One search section's merged rows plus whether more matches exist.

    ``rows`` is name/alias matches first, then description-only matches — the
    ranking the global search page renders. ``has_more`` reports "> limit"
    across **both** tiers combined.
    """

    rows: list[ModelT]
    has_more: bool


def tiered_search_rows[ModelT: Model](
    primary: QuerySet[ModelT],
    ordered_base: QuerySet[ModelT],
    q: str,
    *,
    limit: int = 10,
) -> TieredRows[ModelT]:
    """Merge a name/alias tier and a description tier into one capped section.

    *primary* is the entity's existing ``q``-filtered, ordered queryset (the
    name/alias/etc. matches). *ordered_base* is that **same** base and ordering
    with **no** ``q`` filter — the description tier is ``ordered_base`` narrowed
    by :func:`description_match_q` and de-duplicated against *primary*, so both
    tiers share the entity's canonical sort, annotations and prefetch.

    Fetches ``limit + 1`` to report *has_more* without a second ``count()``. The
    description tier runs only when the model is a :class:`DescribedModel`
    (a base-class capability check — any describable entity in global search
    gets it automatically, a non-describable one is skipped), and only when the
    name tier hasn't already filled the section.
    """
    primary_rows = list(primary[: limit + 1])
    if len(primary_rows) > limit:
        return TieredRows(primary_rows[:limit], has_more=True)
    if not issubclass(ordered_base.model, DescribedModel):
        return TieredRows(primary_rows, has_more=False)
    seen = [row.pk for row in primary_rows]
    fill = limit + 1 - len(primary_rows)
    description_rows = list(
        ordered_base.filter(description_match_q(q)).exclude(pk__in=seen)[:fill]
    )
    rows = primary_rows + description_rows
    return TieredRows(rows[:limit], has_more=len(rows) > limit)
