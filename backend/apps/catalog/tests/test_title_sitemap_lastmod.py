"""Tests for ``Title.sitemap_queryset()``'s aggregated ``lastmod``.

``Title`` is the only catalog page whose primary content aggregates
another catalog entity (its Models). ``_sitemap_lastmod`` widens to
``max(Title.updated_at, max(machine_models.updated_at))`` so a Model edit
bumps the Title's detail-page freshness signal.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.catalog.models import MachineModel, Title


def _refresh_lastmod(title: Title):
    """Re-fetch the annotated ``_sitemap_lastmod`` for *title*."""
    refreshed = Title.sitemap_queryset().get(pk=title.pk)
    # ``_sitemap_lastmod`` is a queryset annotation, not a declared field.
    return refreshed._sitemap_lastmod  # type: ignore[attr-defined]


@pytest.mark.django_db
class TestTitleSitemapLastmod:
    def test_title_only_edit_uses_title_updated_at(self) -> None:
        """A Title with no Models — ``_sitemap_lastmod = Title.updated_at``
        via ``Coalesce(Max(...), updated_at)``."""
        title = Title.objects.create(name="Lonely", slug="lonely")

        lastmod = _refresh_lastmod(title)
        assert lastmod == title.updated_at

    def test_machine_model_edit_bumps_title_lastmod(self) -> None:
        """Editing a child MachineModel widens the Title's lastmod past
        the Title's own ``updated_at``."""
        title = Title.objects.create(name="Family", slug="family")
        mm = MachineModel.objects.create(title=title, name="Child", slug="family-child")

        # Force the Model to be strictly newer than the Title.
        newer = timezone.now() + timedelta(hours=1)
        MachineModel.objects.filter(pk=mm.pk).update(updated_at=newer)
        mm.refresh_from_db()

        title.refresh_from_db()
        lastmod = _refresh_lastmod(title)
        assert lastmod == mm.updated_at
        assert lastmod > title.updated_at

    def test_title_edit_newer_than_models_wins(self) -> None:
        """When the Title's own ``updated_at`` is newer than every Model's,
        the Title's value wins."""
        title = Title.objects.create(name="Boss", slug="boss")
        mm = MachineModel.objects.create(title=title, name="Old", slug="boss-old")

        # Push the Model into the past so the Title is strictly newer.
        older = timezone.now() - timedelta(hours=1)
        MachineModel.objects.filter(pk=mm.pk).update(updated_at=older)
        title.refresh_from_db()

        lastmod = _refresh_lastmod(title)
        assert lastmod == title.updated_at

    def test_picks_max_across_multiple_machine_models(self) -> None:
        """With several Models, the newest Model's timestamp wins."""
        title = Title.objects.create(name="Many", slug="many")
        m1 = MachineModel.objects.create(title=title, name="A", slug="many-a")
        m2 = MachineModel.objects.create(title=title, name="B", slug="many-b")

        t1 = timezone.now() + timedelta(hours=1)
        t2 = timezone.now() + timedelta(hours=2)  # newest
        MachineModel.objects.filter(pk=m1.pk).update(updated_at=t1)
        MachineModel.objects.filter(pk=m2.pk).update(updated_at=t2)

        lastmod = _refresh_lastmod(title)
        m2.refresh_from_db()
        assert lastmod == m2.updated_at

    def test_single_model_title_aggregates_model_edit(self) -> None:
        """The single-Model-Title case (collapsed UI) still aggregates the
        Model's edit timestamp — the Title page renders the Model's content
        so it needs the Model's freshness."""
        title = Title.objects.create(name="Solo", slug="solo")
        mm = MachineModel.objects.create(title=title, name="Solo", slug="solo-only")

        newer = timezone.now() + timedelta(hours=1)
        MachineModel.objects.filter(pk=mm.pk).update(updated_at=newer)
        mm.refresh_from_db()

        lastmod = _refresh_lastmod(title)
        assert lastmod == mm.updated_at

    def test_deleted_title_excluded(self) -> None:
        """Soft-deleted Titles are excluded by the default ``.active()``."""
        Title.objects.create(name="Gone", slug="gone", status="deleted")

        slugs = set(Title.sitemap_queryset().values_list("slug", flat=True))
        assert "gone" not in slugs

    def test_deleted_machine_model_bumps_title_lastmod(self) -> None:
        """Soft-deleting a child Model shrinks the Title's Model list,
        which IS a change to the Title's rendered content. The deletion
        time bumps the Title's ``lastmod`` by design — the ``Max(...)``
        aggregation deliberately spans every MachineModel, not just the
        active ones."""
        title = Title.objects.create(name="Before", slug="before")
        mm = MachineModel.objects.create(title=title, name="Old", slug="before-old")

        # Simulate the delete happening strictly after the Title's last edit.
        delete_time = timezone.now() + timedelta(hours=1)
        MachineModel.objects.filter(pk=mm.pk).update(
            status="deleted", updated_at=delete_time
        )
        mm.refresh_from_db()

        lastmod = _refresh_lastmod(title)
        assert lastmod == mm.updated_at
        assert lastmod > title.updated_at
