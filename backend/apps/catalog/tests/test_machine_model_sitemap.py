"""Tests for ``MachineModel.sitemap_queryset()`` and its single-Model-Title
exclusion.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import MachineModel, Title


def _sitemap_slugs() -> set[str]:
    return set(MachineModel.sitemap_queryset().values_list("slug", flat=True))


@pytest.mark.django_db
class TestSitemapQueryset:
    def test_title_with_two_active_models_includes_both(self) -> None:
        """Two active Models: neither collapses, both detail pages are
        canonical and both belong in the sitemap."""
        title = Title.objects.create(name="Twin", slug="twin")
        MachineModel.objects.create(title=title, name="A", slug="twin-a")
        MachineModel.objects.create(title=title, name="B", slug="twin-b")

        assert {"twin-a", "twin-b"} <= _sitemap_slugs()

    def test_title_with_one_active_model_excludes_it(self) -> None:
        title = Title.objects.create(name="Only", slug="only")
        MachineModel.objects.create(title=title, name="Only", slug="only-one")

        assert "only-one" not in _sitemap_slugs()

    def test_title_with_one_active_and_one_deleted_excludes_active(self) -> None:
        """A deleted sibling doesn't keep the surviving Model's detail URL
        canonical — the single active sibling collapses the UI, and the
        deleted one is out on its own account."""
        title = Title.objects.create(name="Solo", slug="solo")
        MachineModel.objects.create(title=title, name="Live", slug="solo-live")
        MachineModel.objects.create(
            title=title, name="Gone", slug="solo-gone", status="deleted"
        )

        slugs = _sitemap_slugs()
        assert "solo-live" not in slugs
        assert "solo-gone" not in slugs

    def test_original_with_active_variant_keeps_both(self) -> None:
        """The collapse rule is one Model *and no variants*. A variant is an
        active row under the same Title, so it counts as a sibling and both
        detail pages stay canonical."""
        title = Title.objects.create(name="Dressed", slug="dressed")
        original = MachineModel.objects.create(
            title=title, name="Dressed", slug="dressed-pro"
        )
        MachineModel.objects.create(
            title=title, name="Dressed LE", slug="dressed-le", variant_of=original
        )

        assert {"dressed-pro", "dressed-le"} <= _sitemap_slugs()

    def test_deleted_model_not_in_sitemap(self) -> None:
        """Soft-deleted Models are excluded by the default ``.active()``
        filter, independent of the sibling count."""
        title = Title.objects.create(name="Mix", slug="mix")
        MachineModel.objects.create(title=title, name="Live", slug="mix-live")
        MachineModel.objects.create(title=title, name="Also", slug="mix-also")
        MachineModel.objects.create(
            title=title, name="Dead", slug="mix-dead", status="deleted"
        )

        slugs = _sitemap_slugs()
        assert {"mix-live", "mix-also"} <= slugs
        assert "mix-dead" not in slugs
