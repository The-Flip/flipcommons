"""Tests for the shared paginated-listing core (``entity_list.py``) and the franchises
list endpoints: the ``_apply_list_q`` fold contract and the franchises ``GET /`` /
``GET /all/`` endpoints.
"""

import pytest
from django.db import connection

from apps.catalog.api.entity_list import _apply_list_q
from apps.catalog.models import Franchise, Theme, ThemeAlias, Title


@pytest.mark.django_db
class TestApplyListQ:
    """The model-driven ``q`` fold: name (+ alias where the entity has one),
    diacritic-insensitive on Postgres, ``icontains`` on SQLite."""

    def test_blank_q_is_noop(self):
        Franchise.objects.create(name="Alpha", slug="alpha", status="active")
        assert _apply_list_q(Franchise.objects.active(), "   ").count() == 1

    def test_name_substring_match_case_insensitive(self):
        Franchise.objects.create(name="Indiana Jones", slug="ij", status="active")
        Franchise.objects.create(name="Star Wars", slug="sw", status="active")
        result = _apply_list_q(Franchise.objects.active(), "INDIANA")
        assert {f.slug for f in result} == {"ij"}

    def test_diacritic_fold_is_backend_specific(self):
        """Postgres folds ``Café`` → matches ``q=cafe``; SQLite (dev/CI) does not. A
        documented backend gap, not a user-facing regression (prod is Postgres)."""
        Franchise.objects.create(name="Café Royale", slug="cafe", status="active")
        result = _apply_list_q(Franchise.objects.active(), "cafe")
        if connection.vendor == "postgresql":
            assert {f.slug for f in result} == {"cafe"}
        else:
            assert set(result) == set()

    def test_alias_match_for_entity_with_aliases(self):
        """Themes have a ``ThemeAlias``, so ``q`` matches an alias value even when the
        name doesn't — discovered model-side, no per-entity alias list."""
        theme = Theme.objects.create(
            name="Outer Space", slug="outer-space", status="active"
        )
        ThemeAlias.objects.create(theme=theme, value="cosmos")
        result = _apply_list_q(Theme.objects.active(), "cosmos")
        assert {t.slug for t in result} == {"outer-space"}

    def test_alias_fold_uses_exists_not_join(self):
        """Multiple matching aliases must not duplicate the parent row — the ``Exists``
        subquery shape (vs a multi-valued join) is what prevents the count leak."""
        theme = Theme.objects.create(name="Space", slug="space", status="active")
        ThemeAlias.objects.create(theme=theme, value="spacey")
        ThemeAlias.objects.create(theme=theme, value="spaceship")
        result = list(_apply_list_q(Theme.objects.active(), "space"))
        assert len(result) == 1

    def test_entity_without_aliases_searches_name_only(self):
        """Franchise has no ``AliasModel`` — name-only search, no crash on the absent
        alias branch."""
        Franchise.objects.create(name="Zelda", slug="zelda", status="active")
        result = _apply_list_q(Franchise.objects.active(), "zelda")
        assert {f.slug for f in result} == {"zelda"}


@pytest.mark.django_db
class TestFranchiseListEndpoint:
    """The franchises ``GET /`` paginated endpoint — the pristine pattern the other 11
    entities copy."""

    def test_returns_items_count_shape(self, client):
        Franchise.objects.create(name="Indiana Jones", slug="ij", status="active")
        resp = client.get("/api/franchises/")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"items", "count"}
        assert body["count"] == 1
        assert [f["slug"] for f in body["items"]] == ["ij"]

    def test_count_is_total_and_page_invariant(self, client):
        Franchise.objects.bulk_create(
            Franchise(name=f"F{i:02d}", slug=f"f{i:02d}", status="active")
            for i in range(60)
        )
        page1 = client.get("/api/franchises/", {"page": 1}).json()
        page2 = client.get("/api/franchises/", {"page": 2}).json()
        assert page1["count"] == page2["count"] == 60
        assert len(page1["items"]) == 50
        assert len(page2["items"]) == 10

    def test_pages_are_disjoint_and_union_is_full_set_in_order(self, client):
        """Exercises the ``pk`` tiebreak: all 60 share title_count 0, so a missing
        tiebreak would let rows repeat or drop across the page boundary."""
        Franchise.objects.bulk_create(
            Franchise(name=f"F{i:02d}", slug=f"f{i:02d}", status="active")
            for i in range(60)
        )
        page1 = [
            f["slug"]
            for f in client.get("/api/franchises/", {"page": 1}).json()["items"]
        ]
        page2 = [
            f["slug"]
            for f in client.get("/api/franchises/", {"page": 2}).json()["items"]
        ]
        assert set(page1).isdisjoint(page2)
        # title_count all 0 → ordered by name (zero-padded → lexical == numeric).
        assert page1 + page2 == [f"f{i:02d}" for i in range(60)]

    def test_orders_by_title_count_desc(self, client):
        popular = Franchise.objects.create(
            name="Popular", slug="popular", status="active"
        )
        Franchise.objects.create(name="Empty", slug="empty", status="active")
        Title.objects.create(name="T1", slug="t1", status="active", franchise=popular)
        Title.objects.create(name="T2", slug="t2", status="active", franchise=popular)
        body = client.get("/api/franchises/").json()
        assert [f["slug"] for f in body["items"]] == ["popular", "empty"]
        assert body["items"][0]["title_count"] == 2

    def test_q_filters_server_side(self, client):
        Franchise.objects.create(name="Indiana Jones", slug="ij", status="active")
        Franchise.objects.create(name="Star Wars", slug="sw", status="active")
        body = client.get("/api/franchises/", {"q": "star"}).json()
        assert [f["slug"] for f in body["items"]] == ["sw"]
        assert body["count"] == 1

    def test_excludes_deleted(self, client):
        Franchise.objects.create(name="Live", slug="live", status="active")
        Franchise.objects.create(name="Gone", slug="gone", status="deleted")
        body = client.get("/api/franchises/").json()
        assert [f["slug"] for f in body["items"]] == ["live"]
        assert body["count"] == 1


@pytest.mark.django_db
class TestFranchiseAllEndpoint:
    """``GET /all/`` — the full (unpaginated) list the editor option-pickers consume."""

    def test_returns_bare_list_of_all_franchises(self, client):
        Franchise.objects.bulk_create(
            Franchise(name=f"F{i:02d}", slug=f"f{i:02d}", status="active")
            for i in range(60)
        )
        resp = client.get("/api/franchises/all/")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 60
