"""Parity test: every concrete ``SitemappedModel`` carries the mixins the
default ``sitemap_queryset()`` depends on.

The default ``SitemappedModel.sitemap_queryset()`` calls ``.active()`` (from
``LifecycleStatusModel``'s manager) and annotates ``lastmod_expression()``,
whose default reads ``updated_at`` (from ``TimeStampedModel``, via the
``LastUpdatedModel`` default). Today every concrete subclass inherits both
via ``CatalogModel`` + ``TimeStampedModel``. This test makes the contract
explicit so a future ``SitemappedModel`` without the mixins fails CI rather
than crashing at sitemap render — the failure message points at the override
escape hatch.

Mirrors the same ``apps.get_models()`` + ``issubclass`` walk used by
``apps/core/entity_types.py`` (the canonical example of the registry walk).
"""

from __future__ import annotations

from django.apps import apps

from apps.core.models import (
    LifecycleStatusModel,
    SitemappedModel,
    TimeStampedModel,
)


def _concrete_sitemapped_models() -> list[type[SitemappedModel]]:
    return [
        cls
        for cls in apps.get_models()
        if issubclass(cls, SitemappedModel) and not cls._meta.abstract
    ]


def test_every_sitemapped_model_inherits_lifecycle_and_timestamps() -> None:
    """Every concrete ``SitemappedModel`` is also a ``LifecycleStatusModel``
    and a ``TimeStampedModel``.

    The default ``sitemap_queryset()`` calls ``cls.objects.active()`` and
    annotates ``lastmod_expression()`` (``F("updated_at")``) — both rely on
    this inheritance. A future subclass that violates this MUST override
    ``sitemap_queryset()`` (and ``lastmod_expression()``); otherwise the
    sitemap render will crash at runtime.
    """
    offenders: list[str] = []
    for cls in _concrete_sitemapped_models():
        missing: list[str] = []
        if not issubclass(cls, LifecycleStatusModel):
            missing.append("LifecycleStatusModel")
        if not issubclass(cls, TimeStampedModel):
            missing.append("TimeStampedModel")
        if missing:
            offenders.append(f"{cls.__name__} missing: {', '.join(missing)}")

    assert not offenders, (
        "Concrete SitemappedModel subclasses must inherit LifecycleStatusModel "
        "+ TimeStampedModel (the default `sitemap_queryset()` depends on "
        "both). Either inherit the mixins, or override `sitemap_queryset()` "
        "on the offending subclass:\n  " + "\n  ".join(offenders)
    )


def test_registry_walk_finds_expected_count() -> None:
    """Sanity check that the walk finds the catalog's concrete entities.

    Not a hard count assertion — adding/removing a ``SitemappedModel`` should
    not require updating this test. We just assert ``> 0`` so a broken walk
    (e.g. ``apps.get_models()`` returning empty during ``check_apps_ready``
    issues) fails loudly instead of trivially passing.
    """
    found = _concrete_sitemapped_models()
    assert len(found) > 0
