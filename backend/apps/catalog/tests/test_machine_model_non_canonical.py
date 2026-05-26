"""Tests for ``MachineModel.non_canonical_detail_slugs()``.

The single-Model-Title rule (docs/SingleModelTitles.md): a MachineModel's
``/models/<slug>`` detail URL is non-canonical when its parent Title has
exactly one *active* MachineModel. The Model's ``/edit-history`` and
``/sources`` URLs remain canonical (they list the Model's own history and
sources, not the Title's), so the Model still appears in
``MachineModel.sitemap_queryset()`` — only the detail URL is suppressed.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import MachineModel, Title


@pytest.mark.django_db
class TestNonCanonicalDetailSlugs:
    def test_title_with_two_active_models_excludes_both(self) -> None:
        """When a Title has two active Models, neither has a non-canonical
        detail URL — both ``/models/<slug>`` pages are canonical."""
        title = Title.objects.create(name="Twin", slug="twin")
        MachineModel.objects.create(title=title, name="A", slug="twin-a")
        MachineModel.objects.create(title=title, name="B", slug="twin-b")

        result = set(MachineModel.non_canonical_detail_slugs())
        assert "twin-a" not in result
        assert "twin-b" not in result

    def test_title_with_one_active_and_one_deleted_includes_active(self) -> None:
        """A deleted sibling doesn't keep the surviving Model's detail URL
        canonical — the single-active-sibling collapses the UI."""
        title = Title.objects.create(name="Solo", slug="solo")
        MachineModel.objects.create(title=title, name="Live", slug="solo-live")
        MachineModel.objects.create(
            title=title, name="Gone", slug="solo-gone", status="deleted"
        )

        result = set(MachineModel.non_canonical_detail_slugs())
        assert "solo-live" in result
        assert "solo-gone" not in result  # deleted: not active

    def test_title_with_one_active_model_includes_it(self) -> None:
        title = Title.objects.create(name="Only", slug="only")
        MachineModel.objects.create(title=title, name="Only", slug="only-one")

        result = set(MachineModel.non_canonical_detail_slugs())
        assert "only-one" in result

    def test_excluded_slug_still_appears_in_sitemap_queryset(self) -> None:
        """The non-canonical detail Model still appears in
        ``sitemap_queryset()`` so its ``/edit-history`` and ``/sources``
        feed entries are emitted."""
        title = Title.objects.create(name="Only", slug="only-2")
        MachineModel.objects.create(title=title, name="Only", slug="only-two-one")

        non_canonical = set(MachineModel.non_canonical_detail_slugs())
        sitemap_slugs = set(
            MachineModel.sitemap_queryset().values_list("slug", flat=True)
        )
        assert "only-two-one" in non_canonical
        assert "only-two-one" in sitemap_slugs

    def test_deleted_model_not_in_sitemap(self) -> None:
        """Soft-deleted Models are excluded from ``sitemap_queryset`` by the
        default ``.active()`` filter."""
        title = Title.objects.create(name="Mix", slug="mix")
        MachineModel.objects.create(title=title, name="Live", slug="mix-live")
        MachineModel.objects.create(
            title=title, name="Dead", slug="mix-dead", status="deleted"
        )

        sitemap_slugs = set(
            MachineModel.sitemap_queryset().values_list("slug", flat=True)
        )
        assert "mix-live" in sitemap_slugs
        assert "mix-dead" not in sitemap_slugs
