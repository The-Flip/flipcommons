"""Tests for media helpers: all_media(), displayed_primary_media(), displayed_primary_asset_ids()."""

from __future__ import annotations

import pytest

from apps.catalog.tests.conftest import make_machine_model
from apps.media.helpers import (
    all_media,
    displayed_primary_asset_ids,
    displayed_primary_media,
)
from apps.media.models import EntityMedia

pytestmark = pytest.mark.django_db


def _row(asset_id: int, *, category: str | None, is_primary: bool):
    """An unsaved EntityMedia carrying just the fields the selector reads."""
    return EntityMedia(
        asset_id=asset_id,
        category=category,
        is_primary=is_primary,
    )


class TestDisplayedPrimaryAssetIds:
    def test_single_claimed_primary_wins(self):
        rows = [
            _row(1, category="backglass", is_primary=False),
            _row(2, category="backglass", is_primary=True),
        ]
        assert displayed_primary_asset_ids(rows) == {2}

    def test_auto_promotes_earliest_when_none_claimed(self):
        rows = [
            _row(1, category="backglass", is_primary=False),
            _row(2, category="backglass", is_primary=False),
        ]
        assert displayed_primary_asset_ids(rows) == {1}

    def test_two_claimed_primaries_earliest_wins(self):
        rows = [
            _row(1, category="backglass", is_primary=True),
            _row(2, category="backglass", is_primary=True),
        ]
        assert displayed_primary_asset_ids(rows) == {1}

    def test_per_category_independent(self):
        rows = [
            _row(1, category="backglass", is_primary=False),
            _row(2, category="playfield", is_primary=True),
        ]
        assert displayed_primary_asset_ids(rows) == {1, 2}

    def test_uncategorized_is_its_own_group(self):
        rows = [
            _row(1, category=None, is_primary=False),
            _row(2, category="backglass", is_primary=False),
        ]
        assert displayed_primary_asset_ids(rows) == {1, 2}

    def test_lowest_asset_id_wins(self):
        rows = [
            _row(5, category="backglass", is_primary=True),
            _row(3, category="backglass", is_primary=True),
        ]
        assert displayed_primary_asset_ids(rows) == {3}

    def test_empty_input(self):
        assert displayed_primary_asset_ids([]) == set()


class TestAllMedia:
    def test_returns_list_when_prefetched(self):
        pm = make_machine_model(name="X", slug="x")
        # simulate media_prefetch() attaching the attr — it lives on
        # prefetched querysets, not on bare model instances, so we don't
        # type it at the class level. setattr (vs direct attribute
        # assignment) silences mypy's attr-defined error.
        setattr(pm, "all_media", [])  # noqa: B010 — mypy attr-defined workaround

        assert all_media(pm) == []

    def test_raises_when_not_prefetched(self):
        pm = make_machine_model(name="X", slug="x")

        with pytest.raises(AssertionError, match="media_prefetch"):
            all_media(pm)


class TestDisplayedPrimaryMedia:
    def test_returns_displayed_subset_from_all_media(self):
        pm = make_machine_model(name="X", slug="x")
        rows = [
            _row(1, category="backglass", is_primary=False),
            _row(2, category="backglass", is_primary=True),
        ]
        setattr(pm, "all_media", rows)  # noqa: B010 — mypy attr-defined workaround

        assert [em.asset_id for em in displayed_primary_media(pm)] == [2]

    def test_raises_when_not_prefetched(self):
        pm = make_machine_model(name="X", slug="x")

        with pytest.raises(AssertionError, match="media_prefetch"):
            displayed_primary_media(pm)
