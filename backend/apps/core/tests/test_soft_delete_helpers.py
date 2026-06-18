"""Unit tests for the soft-delete walk's narrowing helpers.

The cascade/blocker algorithm itself is exercised end-to-end through the catalog
wrapper in ``apps/catalog/tests/test_soft_delete_walker.py`` (which now runs over
this module's ``soft_delete_walk``). These tests cover the two pure narrowing
helpers the walk hands to its callers — including the ``raise`` paths the
happy-path walker tests never hit.
"""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.catalog.models import Title
from apps.core.soft_delete import has_lifecycle, require_linkable


class TestHasLifecycle:
    def test_true_for_lifecycle_model(self) -> None:
        assert has_lifecycle(Title) is True

    def test_false_for_non_lifecycle_model(self) -> None:
        # ContentType is a plain Django model with no lifecycle status.
        assert has_lifecycle(ContentType) is False


class TestRequireLinkable:
    def test_returns_linkable_instance(self) -> None:
        title = Title()
        assert require_linkable(title) is title

    def test_raises_for_non_linkable(self) -> None:
        with pytest.raises(TypeError, match="not a LinkableModel"):
            require_linkable(ContentType())
