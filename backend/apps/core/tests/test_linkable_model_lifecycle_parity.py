"""Parity test: every concrete ``LinkableModel`` carries the mixins the
default ``sitemap_queryset()`` depends on.

The default ``LinkableModel.sitemap_queryset()`` calls ``.active()`` (from
``LifecycleStatusModel``'s manager) and reads ``updated_at`` (from
``TimeStampedModel``). Today every concrete subclass inherits both via
``CatalogModel`` + ``TimeStampedModel``. This test makes the contract
explicit so a future non-lifecycle ``LinkableModel`` fails CI rather than
crashing at sitemap render — the failure message points at the override
escape hatch.

Mirrors the same ``apps.get_models()`` + ``issubclass`` walk used by
``apps/core/entity_types.py`` (the canonical example of the
``LinkableModel`` registry walk).
"""

from __future__ import annotations

from django.apps import apps

from apps.core.models import (
    LifecycleStatusModel,
    LinkableModel,
    TimeStampedModel,
)


def _concrete_linkable_models() -> list[type[LinkableModel]]:
    return [
        cls
        for cls in apps.get_models()
        if issubclass(cls, LinkableModel) and not cls._meta.abstract
    ]


def test_every_linkable_model_inherits_lifecycle_and_timestamps() -> None:
    """Every concrete ``LinkableModel`` is also a ``LifecycleStatusModel``
    and a ``TimeStampedModel``.

    The default ``sitemap_queryset()`` calls ``cls.objects.active()`` and
    annotates ``F("updated_at")`` — both rely on this inheritance. A future
    subclass that violates this MUST override ``sitemap_queryset()``;
    otherwise the sitemap render will crash at runtime.
    """
    offenders: list[str] = []
    for cls in _concrete_linkable_models():
        missing: list[str] = []
        if not issubclass(cls, LifecycleStatusModel):
            missing.append("LifecycleStatusModel")
        if not issubclass(cls, TimeStampedModel):
            missing.append("TimeStampedModel")
        if missing:
            offenders.append(f"{cls.__name__} missing: {', '.join(missing)}")

    assert not offenders, (
        "Concrete LinkableModel subclasses must inherit LifecycleStatusModel "
        "+ TimeStampedModel (the default `sitemap_queryset()` depends on "
        "both). Either inherit the mixins, or override `sitemap_queryset()` "
        "on the offending subclass:\n  " + "\n  ".join(offenders)
    )


def test_registry_walk_finds_expected_count() -> None:
    """Sanity check that the walk finds the catalog's concrete entities.

    Not a hard count assertion — adding/removing a ``LinkableModel`` should
    not require updating this test. We just assert ``> 0`` so a broken walk
    (e.g. ``apps.get_models()`` returning empty during ``check_apps_ready``
    issues) fails loudly instead of trivially passing.
    """
    found = _concrete_linkable_models()
    assert len(found) > 0
