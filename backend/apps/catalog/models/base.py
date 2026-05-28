"""CatalogModel and AliasModel abstract bases for catalog entities."""

from __future__ import annotations

from typing import ClassVar, Self

from django.db import models

from apps.core.models import (
    DescribedModel,
    LifecycleManager,
    LifecycleStatusModel,
    LinkableModel,
)
from apps.provenance.models import ClaimControlledModel

__all__ = ["AliasModel", "CatalogModel"]


class AliasModel(models.Model):
    """Abstract base for alias lookup models.

    Alias values are stored and compared in lowercase (matching the
    UniqueConstraint(Lower("value")) that every subclass must define).
    Claims live on the *parent* object, not on the alias row itself.

    Subclasses must add:
    - A ForeignKey to the parent model (named after the parent, related_name="aliases")
    - A UniqueConstraint on Lower("value") with a table-specific name
    - ``alias_claim_field``: the claim namespace on the parent that carries
      alias values (e.g. ``"theme_alias"``). Enforced at class creation
      via ``__init_subclass__``; read by ``discover_alias_types``.

    ``AliasModel`` does not bundle ``TimeStampedModel``. Row-level
    timestamps are an independent choice per subclass — the meaningful
    "when was this asserted" lives on the originating claim, not on the
    alias row. Existing concrete aliases all inherit ``TimeStampedModel``
    by convention, but a future alias subclass could opt out.
    """

    alias_claim_field: ClassVar[str]

    value = models.CharField(max_length=200)

    class Meta:
        abstract = True
        ordering = ["value"]

    def __init_subclass__(cls, **kwargs: object) -> None:
        # NB: we can't gate on ``cls._meta.abstract`` here — Django's ModelBase
        # runs ``__init_subclass__`` with ``abstract`` still inherited as True
        # from the parent, then rewrites it to False for concrete subclasses
        # later. So this check runs for every AliasModel subclass, concrete or
        # not. That's fine: any abstract intermediate can just declare
        # ``alias_claim_field`` for its concrete descendants to inherit.
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "alias_claim_field", None):
            raise TypeError(
                f"{cls.__name__} must declare a non-empty `alias_claim_field` "
                'class attr (e.g. `alias_claim_field = "theme_alias"`)'
            )

    def __str__(self) -> str:
        return self.value


class CatalogModel(
    DescribedModel, LinkableModel, LifecycleStatusModel, ClaimControlledModel
):
    """Abstract marker for top-level catalog entities.

    Combines a long-form ``description`` (``DescribedModel``),
    URL-addressability (``LinkableModel``), claim-controlled lifecycle
    status (``LifecycleStatusModel``), and claim-driven display fields
    (``ClaimControlledModel``). Used to distinguish catalog-specific code
    paths (e.g. ``ingest_pindata``, soft-delete wire format) that must not
    widen to other ``LinkableModel`` subclasses.

    Concrete subclasses inherit all four capabilities transitively and do
    not relist them in their own bases. Each concrete subclass must still
    carry its own ``status_valid()`` constraint in ``Meta`` because Django
    does not inherit abstract-parent constraints when a concrete model
    defines its own ``Meta``.
    """

    # Redeclared from ``LifecycleStatusModel`` so ``Self`` rebinds at the
    # catalog level — mypy walks the TypeVar bound, not the concrete class,
    # so without this ``model_cls.objects.active()`` (where
    # ``model_cls: type[ModelT: CatalogModel]``) types as
    # ``LifecycleManager[LifecycleStatusModel]`` rather than
    # ``LifecycleManager[ModelT]``.
    # See LifecycleStatusModel.objects for why pyright is ignored here.
    objects: ClassVar[LifecycleManager[Self]] = LifecycleManager()  # pyright: ignore[reportInvalidTypeForm]

    # Soft-delete walker policy — see apps/catalog/api/soft_delete.py.
    # Concrete subclasses override these frozensets when they need to
    # cascade deletion to dependent entities or block deletion when M2M /
    # self-ref usage exists. Empty defaults keep the walker generic.
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset()
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset()

    class Meta:
        abstract = True
