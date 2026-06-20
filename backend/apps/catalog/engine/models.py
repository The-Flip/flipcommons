"""Generic catalog-level model bases.

The one generic, domain-neutral Django model base the engine owns. Cross-layer
bases (``LinkableClaimModel``, ``LinkableLifecycleClaimModel``) live in
``provenance``; ``CatalogModel`` is the bundle the concrete *domain* models
inherit, so it stays in ``catalog/models/``. ``AliasModel`` is neither — it's
the materialized projection target of alias claims (a denormalized lookup
table, generic to any encyclopedia), so it lands here. Keep this a flat module,
not a package, until a second generic base actually joins it.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import models

__all__ = ["AliasModel"]


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
    """

    alias_claim_field: ClassVar[str]

    value = models.CharField(max_length=200)

    class Meta:
        abstract = True
        ordering = ["value"]

    def __init_subclass__(cls, **kwargs: object) -> None:
        # We can't gate on ``cls._meta.abstract`` here — Django's ModelBase
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
