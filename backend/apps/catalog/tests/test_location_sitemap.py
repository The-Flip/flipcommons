"""Tests for ``Location.sitemap_queryset()`` — sitemap membership is narrowed
to locations with at least one manufacturer at or below them.

A location page's primary content is its aggregated manufacturer grid
(manufacturers propagate up the ancestor chain), so a zero-manufacturer
location renders an empty page that search engines cluster as duplicate
content. Such locations are excluded from the sitemap entirely.

Fixtures use Location + CorporateEntityLocation directly (bypassing claims)
for speed, mirroring ``test_api_locations.py``.
"""

import pytest

from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityLocation,
    Location,
    Manufacturer,
)
from apps.core.sitemap import all_sitemap_feeds

pytestmark = pytest.mark.django_db


def _make_location(location_path, name, parent=None):
    slug = location_path.rsplit("/", 1)[-1]
    return Location.objects.create(
        location_path=location_path,
        slug=slug,
        name=name,
        location_type="country" if parent is None else "city",
        parent=parent,
    )


def _make_mfr_at(name, slug, location, entity_status="active"):
    mfr = Manufacturer.objects.create(name=name, slug=slug)
    entity = CorporateEntity.objects.create(
        name=name, slug=slug, manufacturer=mfr, status=entity_status
    )
    CorporateEntityLocation.objects.create(corporate_entity=entity, location=location)
    return mfr


def _sitemap_paths() -> set[str]:
    return set(Location.sitemap_queryset().values_list("location_path", flat=True))


class TestLocationSitemapQueryset:
    def test_location_with_direct_manufacturer_included(self):
        usa = _make_location("usa", "USA")
        vt = _make_location("usa/vt", "Vermont", parent=usa)
        _make_mfr_at("Richard Mfg", "richard-mfg", vt)

        assert "usa/vt" in _sitemap_paths()

    def test_ancestors_of_manufacturer_bearing_location_included(self):
        """Manufacturers aggregate up the chain, so every ancestor page has
        content and stays in the sitemap."""
        usa = _make_location("usa", "USA")
        vt = _make_location("usa/vt", "Vermont", parent=usa)
        winooski = _make_location("usa/vt/winooski", "Winooski", parent=vt)
        _make_mfr_at("Richard Mfg", "richard-mfg", winooski)

        assert _sitemap_paths() == {"usa", "usa/vt", "usa/vt/winooski"}

    def test_zero_manufacturer_location_excluded(self):
        usa = _make_location("usa", "USA")
        il = _make_location("usa/il", "Illinois", parent=usa)
        chicago = _make_location("usa/il/chicago", "Chicago", parent=il)
        _make_mfr_at("Williams", "williams", chicago)
        _make_location("usa/hi", "Hawaii", parent=usa)

        paths = _sitemap_paths()
        assert "usa/hi" not in paths
        assert "usa/il" in paths

    def test_empty_branch_excluded_entirely(self):
        nl = _make_location("netherlands", "Netherlands")
        _make_location("netherlands/reuver", "Reuver", parent=nl)

        assert _sitemap_paths() == set()

    def test_shared_path_prefix_is_not_ancestry(self):
        """``nl`` must not inherit content from ``nl2`` just because
        ``"nl2".startswith("nl")`` — descendant matching requires a full
        path segment."""
        _make_location("nl", "Netherlands")
        nl2 = _make_location("nl2", "Not Netherlands")
        _make_mfr_at("Dutch Pinball", "dutch-pinball", nl2)

        assert _sitemap_paths() == {"nl2"}

    def test_soft_deleted_corporate_entity_does_not_count(self):
        usa = _make_location("usa", "USA")
        _make_mfr_at("Ghost Pinball", "ghost-pinball", usa, entity_status="deleted")

        assert _sitemap_paths() == set()

    def test_feed_drops_excluded_locations(self):
        """The exclusion flows through ``all_sitemap_feeds()`` — a
        zero-manufacturer location emits no URLs at all."""
        usa = _make_location("usa", "USA")
        vt = _make_location("usa/vt", "Vermont", parent=usa)
        _make_mfr_at("Richard Mfg", "richard-mfg", vt)
        _make_location("usa/hi", "Hawaii", parent=usa)

        feeds = {f.kind: f for f in all_sitemap_feeds()}
        slugs = {e.slug for e in feeds["location"].entries}
        assert slugs == {"usa", "usa/vt"}
