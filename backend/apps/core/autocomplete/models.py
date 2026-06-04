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

from typing import ClassVar, Self

from django.db import models

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
      override to add annotations a :meth:`autocomplete_sublabel` reads.
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
        still be autocompletable. Override to add the annotations a derived
        :meth:`autocomplete_sublabel` reads — the hook that keeps sublabels out
        of an N+1.
        """
        if issubclass(cls, LifecycleStatusModel):
            return cls.objects.active()
        return cls._default_manager.all()

    def autocomplete_sublabel(self) -> str | None:
        """Optional second line disambiguating same-labeled rows.

        Default ``None`` (no sublabel). Override to return a string — e.g. a
        title's "manufacturer · year" — typically reading an annotation set by
        :meth:`autocomplete_queryset`.
        """
        return None
