"""Shared plumbing for the paginated catalog listing endpoints.

Two typed helpers behind every in-scope ``GET /api/{entity}/`` list handler:

- :func:`paginated_list_response` — the slice-before-counting core: apply the ``q``
  fold, count the filtered set, order by a total ordering, slice one page at SQL, run
  an optional batched thumbnail provider over just that page, and return a typed
  :class:`ListPage`. The handler wraps that in its own hand-declared
  ``{Entity}ListSchema``.
- :func:`_apply_list_q` — the model-driven ``q`` fold: name (+ aliases where the
  entity has an ``AliasModel``), diacritic-insensitive on Postgres, ``icontains`` on
  SQLite (the documented dev/CI gap).

No per-entity branching and nothing on the model: each handler stays a thin, fully
typed call into these two functions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple, cast

from django.db import connection
from django.db.models import F, Model, OuterRef, Q, QuerySet
from django.db.models.expressions import BaseExpression
from django.db.models.functions import Lower

from apps.core.search import fold as _fold

from ...aliases import alias_type_for
from ...query.constants import DEFAULT_PAGE_SIZE
from ...query.facet_helpers import _fold_exists, _Unaccent

# Maps one page's primary keys → their thumbnail URLs, batched (run once per page, never
# per row). Implemented by the entities that carry thumbnails (people, series).
type ThumbnailProvider = Callable[[Sequence[int]], Mapping[int, str | None]]

# Serializes one sliced row to its list-item schema. The second arg is the row's
# thumbnail URL (``None`` when the handler passes no ``ThumbnailProvider``); entities
# with no thumbnail ignore it.
type RowSerializer[ModelT: Model, ItemSchemaT] = Callable[
    [ModelT, str | None], ItemSchemaT
]


class ListPage[ItemSchemaT](NamedTuple):
    """One serialized page plus the filtered-set total.

    ``total`` is the **pagination total** (the full filtered-set size, page-invariant),
    which ``createPaginatedLoader`` reads to derive ``has_more``; it is never the page
    length. (Named ``total`` rather than ``count`` to avoid shadowing ``tuple.count``.)
    Internal return container — the handler coerces it into its own ``{Entity}ListSchema``
    OpenAPI component, so ``ListPage`` itself is never a wire type.
    """

    items: list[ItemSchemaT]
    total: int


def _apply_list_q[ModelT: Model](qs: QuerySet[ModelT], q: str) -> QuerySet[ModelT]:
    """Narrow *qs* to rows whose ``name`` (or alias, where the entity has one) matches *q*.

    Postgres folds diacritics — ``LOWER(UNACCENT(name))`` contains the folded term, so
    ``q=pokemon`` matches ``Pokémon``. SQLite (dev/CI) uses plain ``icontains`` — no
    folding, the documented backend gap. The fold is
    punctuation-sensitive, also by design. Empty/whitespace *q* is a no-op.

    Alias matching reuses the manufacturers' ``Exists``-fold shape so the alias join
    can't leak duplicate rows into a count.
    """
    q = q.strip()
    if not q:
        return qs
    folded = _fold(q)

    # Build the fold annotations + match predicate together. The `cast` at the end
    # repairs the `ModelT` that django-stubs drops through `.annotate()` (it widens the
    # self type to the base `Model`); the annotations are real and the runtime row type
    # is unchanged.
    annotations: dict[str, BaseExpression] = {}
    if connection.vendor == "postgresql":
        annotations["_q_name"] = Lower(_Unaccent(F("name")))
        predicate = Q(_q_name__contains=folded)
    else:
        predicate = Q(name__icontains=q)

    alias = alias_type_for(qs.model)
    if alias is not None:
        annotations["_q_alias"] = _fold_exists(
            alias.alias_model._default_manager.filter(
                **{alias.fk_name: OuterRef("pk")}
            ),
            "value",
            q,
            folded,
        )
        predicate |= Q(_q_alias=True)

    return cast("QuerySet[ModelT]", qs.annotate(**annotations).filter(predicate))


def paginated_list_response[ModelT: Model, ItemSchemaT](
    qs: QuerySet[ModelT],
    *,
    q: str,
    ordering: tuple[str, ...],
    page: int,
    serialize_row: RowSerializer[ModelT, ItemSchemaT],
    thumbnail_provider: ThumbnailProvider | None = None,
) -> ListPage[ItemSchemaT]:
    """One ordered, ``q``-filtered page of *qs* plus the filtered-set total.

    Counts the filtered set **before** slicing, then slices a single page at SQL
    (LIMIT/OFFSET, never ``list(qs)`` over the whole table). *ordering* must be a **total
    order** (append ``pk`` after the entity's natural sort) so offset pages don't overlap
    or drop rows.
    """
    qs = _apply_list_q(qs, q)
    total = qs.count()
    start = (max(page, 1) - 1) * DEFAULT_PAGE_SIZE
    rows = list(qs.order_by(*ordering)[start : start + DEFAULT_PAGE_SIZE])
    thumbnails = thumbnail_provider([r.pk for r in rows]) if thumbnail_provider else {}
    items = [serialize_row(row, thumbnails.get(row.pk)) for row in rows]
    return ListPage(items=items, total=total)
