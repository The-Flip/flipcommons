"""CatalogModel abstract base for catalog entities.

``AliasModel`` — the one generic, domain-neutral catalog model base — lives in
``catalog.engine.models`` and is re-exported here so concrete alias models keep
their single ``from .base import AliasModel`` import site. The
``catalog.models -> catalog.engine`` edge is the sanctioned downward direction
(domain → engine).
"""

from __future__ import annotations

from typing import ClassVar, Self

from apps.core.models import (
    DescribedModel,
    LifecycleManager,
    SitemappedModel,
)
from apps.provenance.models import LinkableLifecycleClaimModel

from ..engine.models import AliasModel

__all__ = ["AliasModel", "CatalogModel"]


class CatalogModel(DescribedModel, SitemappedModel, LinkableLifecycleClaimModel):
    """Abstract marker for top-level catalog entities.

    Used to distinguish catalog-specific code paths (e.g. data-patch ingest,
    soft-delete wire format), as well as define the capabilies that all catalog
    models must have.

    The lifecycle + claim leaves come from ``LinkableLifecycleClaimModel``
    (``LifecycleStatusModel`` + ``LinkableClaimModel``); the bundle is
    ``DescribedModel`` + ``SitemappedModel`` on top. Inserting the combined ABC
    is MRO-preserving — it declares no fields, manager or constraints — so the
    field layout, default manager and migration state are unchanged.

    Each concrete subclass must still carry its own ``status_valid()`` constraint
    in ``Meta`` because Django does not inherit abstract-parent constraints when
    a concrete model defines its own ``Meta``.
    """

    # Redeclared from ``LifecycleStatusModel`` so ``Self`` rebinds at the
    # catalog level — mypy walks the TypeVar bound, not the concrete class,
    # so without this ``model_cls.objects.active()`` (where
    # ``model_cls: type[ModelT: CatalogModel]``) types as
    # ``LifecycleManager[LifecycleStatusModel]`` rather than
    # ``LifecycleManager[ModelT]``.
    # See LifecycleStatusModel.objects for why pyright is ignored here.
    objects: ClassVar[LifecycleManager[Self]] = LifecycleManager()  # pyright: ignore[reportInvalidTypeForm]

    class Meta:
        abstract = True
