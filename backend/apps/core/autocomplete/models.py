"""``AutocompletableModel`` — the abstract base a model inherits to be
searchable from autocomplete dropdowns.

A model inheriting this base is declaring "show this type in typeahead
controls." It carries the per-model search configuration the engine
(:mod:`apps.core.autocomplete.registry`) reads, and supplies the
``{value, label}`` an autocomplete row needs via
:class:`~apps.core.models.LabeledIdentityModel` (``value = public_id``,
``label = label``). ``sublabel`` is an optional per-model override.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, Self

from django.db import models
from django.db.models.expressions import Combinable

from apps.core.models import LabeledIdentityModel, LifecycleStatusModel


class AutocompletableModel(LabeledIdentityModel):
    """A :class:`LabeledIdentityModel` that opts into autocomplete dropdowns.

    Subclasses may override:

    - ``autocomplete_search_fields`` — **plain** field paths (not lookup
      expressions) ORed together by the engine, which appends the lookup
      (``__unaccent__icontains`` on Postgres, ``__icontains`` on SQLite).
      Direct (``name``) and relation (``aliases__value``) paths both work;
      the engine ``.distinct()``\\ s to absorb relation-join row multiplication.
    - ``autocomplete_ordering`` — ``order_by`` applied before the result cap.
    - ``autocomplete_select_related`` — joins to avoid per-row queries in the
      serializer.
    - :meth:`autocomplete_queryset` — the base queryset (default ``.active()``);
      override for a different base filter.
    - :meth:`autocomplete_annotations` — expressions the engine annotates on,
      feeding a derived :meth:`autocomplete_sublabel` without an N+1.
    - :meth:`autocomplete_sublabel` — optional disambiguating second line.
    """

    autocomplete_search_fields: ClassVar[tuple[str, ...]] = ("name",)
    autocomplete_ordering: ClassVar[tuple[str, ...]] = ("name",)
    autocomplete_select_related: ClassVar[tuple[str, ...]] = ()

    class Meta:
        abstract = True

    @classmethod
    def autocomplete_queryset(cls) -> models.QuerySet[Self]:
        """Base queryset autocomplete searches within.

        ``.active()`` rows for a :class:`LifecycleStatusModel` (excludes
        soft-deleted entities), else every row. Autocomplete *integrates* with
        the lifecycle concern but doesn't *require* it: this base stays off
        ``LifecycleStatusModel`` so a non-lifecycle entity (e.g. ``user``) can
        still be autocompletable. Override only for a different base filter;
        annotations go through :meth:`autocomplete_annotations`.
        """
        if issubclass(cls, LifecycleStatusModel):
            return cls.objects.active()
        return cls._default_manager.all()

    @classmethod
    def autocomplete_annotations(cls) -> Mapping[str, Combinable]:
        """Expressions the engine ``annotate()``\\ s onto the queryset before
        serializing, keyed by the attribute name :meth:`autocomplete_sublabel`
        reads off each row.

        Default: none. Override to feed a derived sublabel from the DB in one
        query (e.g. a title's first-model manufacturer/year via correlated
        subqueries) rather than a per-row fetch. Applied uniformly by the engine
        — the model declares the expressions, it doesn't splice them into its
        own queryset, so no annotated-row cast leaks into the model layer.
        """
        return {}

    def autocomplete_sublabel(self) -> str | None:
        """Optional second line disambiguating same-labeled rows.

        Default ``None`` (no sublabel). Override to return a string — e.g. a
        title's "manufacturer · year" — typically reading an annotation declared
        by :meth:`autocomplete_annotations`.
        """
        return None
