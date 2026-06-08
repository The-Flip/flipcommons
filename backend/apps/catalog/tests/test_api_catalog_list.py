"""Tests for the shared paginated-listing core (``entity_list.py``) and the franchises
list endpoint: the ``_apply_list_q`` fold contract and the franchises ``GET /`` endpoint.
"""

from typing import cast

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection

from apps.catalog.api import routers
from apps.catalog.api._counts import bulk_title_counts_via_models
from apps.catalog.api._typing import HasTitleCount
from apps.catalog.api.constants import DEFAULT_PAGE_SIZE
from apps.catalog.api.entity_list import _apply_list_q
from apps.catalog.api.taxonomy import _flat_taxonomy_list_qs
from apps.catalog.models import (
    Cabinet,
    CorporateEntity,
    CreditRole,
    Franchise,
    GameFormat,
    MachineModel,
    Manufacturer,
    RewardType,
    Series,
    System,
    Tag,
    Theme,
    ThemeAlias,
    Title,
)
from apps.catalog.tests.conftest import SAMPLE_IMAGES, make_machine_model
from apps.core.entity_types import all_linkable_models
from apps.core.models import EntityStatus
from apps.media.models import EntityMedia, MediaAsset


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
class TestFlatTaxonomyCountAnnotationParity:
    """The flat-taxonomy ``title_count`` SQL annotation (``_flat_taxonomy_title_count``,
    via ``_flat_taxonomy_list_qs``) must equal the Python ``bulk_title_counts_via_models`` map
    it replaces — distinct active titles through active, non-variant models. Pins the
    conversion the 5 flat taxonomies copy, so a filter drift fails here, not in prod."""

    def test_annotation_matches_python_helper(self):
        # A dataset exercising every filter branch the two paths must agree on:
        # multi-model titles (dedup), variants (excluded), deleted models and
        # deleted titles (excluded), and a cabinet with zero qualifying titles.
        floor = Cabinet.objects.create(name="Floor", slug="floor", display_order=1)
        bartop = Cabinet.objects.create(name="Bartop", slug="bartop", display_order=2)
        empty = Cabinet.objects.create(name="Empty", slug="empty", display_order=3)

        t1 = Title.objects.create(name="Funhouse", slug="funhouse", status="active")
        t2 = Title.objects.create(name="Taxi", slug="taxi", status="active")
        gone = Title.objects.create(
            name="Gone", slug="gone", status=EntityStatus.DELETED
        )

        def mm(title, name, *, variant_of=None, status="active"):
            return MachineModel.objects.create(
                title=title,
                name=name,
                slug=name.lower().replace(" ", "-"),
                cabinet=floor,
                variant_of=variant_of,
                status=status,
            )

        # floor: two active non-variant models on the SAME title → counts once;
        # a second title → 2 distinct; a variant and a deleted model → ignored;
        # a model on a deleted title → ignored.
        primary = mm(t1, "Funhouse A")
        mm(t1, "Funhouse B")
        mm(t1, "Funhouse Variant", variant_of=primary)
        mm(t2, "Taxi")
        mm(t1, "Funhouse Dead", status=EntityStatus.DELETED)
        mm(gone, "Gone Model")
        # bartop: one active title.
        MachineModel.objects.create(
            title=t2, name="Taxi Bartop", slug="taxi-bartop", cabinet=bartop
        )

        pks = [floor.pk, bartop.pk, empty.pk]
        expected = bulk_title_counts_via_models(pks, "cabinet")
        annotated = {
            c.pk: cast(HasTitleCount, c).title_count
            for c in _flat_taxonomy_list_qs(Cabinet)
        }

        assert annotated[floor.pk] == expected[floor.pk] == 2
        assert annotated[bartop.pk] == expected[bartop.pk] == 1
        # The empty cabinet: helper omits zero-count pks; the annotation yields 0.
        assert annotated[empty.pk] == 0
        assert expected.get(empty.pk, 0) == 0

    def test_annotation_matches_python_helper_for_m2m_taxonomy(self):
        """Cabinet is a plain FK; tags reach MachineModel through an M2M-through table,
        where the join fans out and ``distinct=True`` is load-bearing. Pin parity on that
        different join shape too, since tags/reward-types copy the same annotation."""
        action = Tag.objects.create(name="Action", slug="action", display_order=1)
        empty = Tag.objects.create(name="Quiet", slug="quiet", display_order=2)

        t1 = Title.objects.create(name="Funhouse", slug="funhouse", status="active")
        t2 = Title.objects.create(name="Taxi", slug="taxi", status="active")

        def mm(title, name, *, variant_of=None, status="active"):
            return MachineModel.objects.create(
                title=title,
                name=name,
                slug=name.lower().replace(" ", "-"),
                variant_of=variant_of,
                status=status,
            )

        # Two active non-variant models on the SAME title both tagged → counts once;
        # a second title → 2 distinct. A variant and a deleted model are ignored.
        m_a = mm(t1, "Funhouse A")
        m_b = mm(t1, "Funhouse B")
        m_var = mm(t1, "Funhouse Variant", variant_of=m_a)
        m_t2 = mm(t2, "Taxi")
        m_dead = mm(t1, "Funhouse Dead", status=EntityStatus.DELETED)
        for m in (m_a, m_b, m_var, m_t2, m_dead):
            m.tags.add(action)

        pks = [action.pk, empty.pk]
        expected = bulk_title_counts_via_models(pks, "tags")
        annotated = {
            t.pk: cast(HasTitleCount, t).title_count
            for t in _flat_taxonomy_list_qs(Tag)
        }

        assert annotated[action.pk] == expected[action.pk] == 2
        assert annotated[empty.pk] == 0
        assert expected.get(empty.pk, 0) == 0


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
class TestThemeListEndpoint:
    """The themes ``GET /`` — the compute-sort-slice variation that does its own
    rollup→sort→slice (the ``-title_count`` sort is a hierarchical rollup, not a SQL
    column), reusing ``_apply_list_q`` for the fold."""

    def test_returns_items_count_shape(self, client):
        Theme.objects.create(name="Space", slug="space", status="active")
        body = client.get("/api/themes/").json()
        assert set(body) == {"items", "count"}
        assert body["count"] == 1
        assert [t["slug"] for t in body["items"]] == ["space"]

    def test_pages_disjoint_and_union_is_full_set(self, client):
        """All 60 share title_count 0 → ordered by (name, pk); the explicit ``pk``
        tiebreak in the in-memory sort keeps offset pages from overlapping."""
        Theme.objects.bulk_create(
            Theme(name=f"T{i:02d}", slug=f"t{i:02d}", status="active")
            for i in range(60)
        )
        page1 = [
            t["slug"] for t in client.get("/api/themes/", {"page": 1}).json()["items"]
        ]
        page2 = [
            t["slug"] for t in client.get("/api/themes/", {"page": 2}).json()["items"]
        ]
        assert len(page1) == DEFAULT_PAGE_SIZE
        assert len(page2) == 60 - DEFAULT_PAGE_SIZE
        assert set(page1).isdisjoint(page2)
        assert page1 + page2 == [f"t{i:02d}" for i in range(60)]

    def test_q_matches_alias(self, client):
        theme = Theme.objects.create(
            name="Outer Space", slug="outer-space", status="active"
        )
        ThemeAlias.objects.create(theme=theme, value="cosmos")
        Theme.objects.create(name="Medieval", slug="medieval", status="active")
        body = client.get("/api/themes/", {"q": "cosmos"}).json()
        assert [t["slug"] for t in body["items"]] == ["outer-space"]
        assert body["count"] == 1

    def test_search_result_count_reflects_full_descendant_rollup(self, client):
        """Searching a parent shows its **full** rollup count, including a child that
        doesn't match ``q`` — the rollup is computed over all active themes, ``q`` only
        selects which rows are returned."""
        parent = Theme.objects.create(
            name="Space Saga", slug="space-saga", status="active"
        )
        child = Theme.objects.create(name="Moon", slug="moon", status="active")
        child.parents.add(parent)
        title = Title.objects.create(name="Lunar", slug="lunar", status="active")
        MachineModel.objects.create(
            title=title, name="Lunar", slug="lunar", status="active"
        ).themes.add(child)

        body = client.get("/api/themes/", {"q": "saga"}).json()
        # Only the parent matches "saga"; its count still rolls up the child's title.
        assert [t["slug"] for t in body["items"]] == ["space-saga"]
        assert body["items"][0]["title_count"] == 1


# The 12 catalog entities whose listing pages are SSR'd with a paginated ``GET /``
# returning the ``{items, count}`` page shape.
IN_SCOPE_PAGINATED = frozenset(
    {
        "cabinets",
        "corporate-entities",
        "credit-roles",
        "franchises",
        "game-formats",
        "gameplay-features",
        "people",
        "reward-types",
        "series",
        "systems",
        "tags",
        "themes",
    }
)

# ``titles``, ``manufacturers`` and ``models`` predate this work: bespoke faceted /
# search endpoints that share the ``{items, count}`` page shape but have no listing page
# of their own, so they are explicitly out of scope (see the plan's Non-goals).
PREEXISTING_FACETED = frozenset({"titles", "manufacturers", "models"})


def _mounts_paginated_list_root(router: object) -> bool:
    """True iff *router* mounts a ``GET /`` whose 200 response is an ``{items, count}``
    page wrapper — the shape ``createPaginatedLoader`` consumes."""
    path_op = getattr(router, "path_operations", {}).get("/")
    if path_op is None:
        return False
    for op in path_op.operations:
        if "GET" not in op.methods:
            continue
        wrapper = op.response_models.get(200)
        if wrapper is None:
            continue
        inner = wrapper.model_fields["response"].annotation
        if set(getattr(inner, "model_fields", {})) == {"items", "count"}:
            return True
    return False


class TestPaginatedListEndpointParity:
    """The endpoint inventory must stay in lockstep with the in-scope set: every
    in-scope entity mounts a paginated ``GET /``, and nothing outside the known set
    sprouts the page shape unnoticed. Catches 'added a listing page, forgot the
    endpoint' and the reverse, using the existing router registry."""

    def test_in_scope_set_matches_mounted_paginated_roots(self):
        mounted = {
            prefix.strip("/")
            for prefix, router in routers
            if _mounts_paginated_list_root(router)
        }
        assert mounted == IN_SCOPE_PAGINATED | PREEXISTING_FACETED

    def test_in_scope_plurals_are_real_registry_entities(self):
        """Each in-scope plural names a real ``LinkableModel`` (its
        ``entity_type_plural``) — so a typo or a removed entity fails here."""
        registry_plurals = {m.entity_type_plural for m in all_linkable_models()}
        assert registry_plurals >= IN_SCOPE_PAGINATED


# ---------------------------------------------------------------------------
# Generic pagination contract — one shape/count/ordering check per core-backed
# entity. franchises and themes carry their own deeper tests (above); this pins
# the remaining handlers that each pass their own ``ordering`` tuple + qs.
# ---------------------------------------------------------------------------


def _seed_taxonomy(model):
    """Bulk-create *n* active taxonomy rows with sortable, ``q``-addressable names."""

    def seed(n: int) -> None:
        model.objects.bulk_create(
            model(
                name=f"Zexel {i:03d}",
                slug=f"zexel-{i:03d}",
                display_order=i,
                status="active",
            )
            for i in range(n)
        )

    return seed


def _seed_series(n: int) -> None:
    Series.objects.bulk_create(
        Series(name=f"Zexel {i:03d}", slug=f"zexel-{i:03d}", status="active")
        for i in range(n)
    )


def _seed_corporate_entities(n: int) -> None:
    mfr = Manufacturer.objects.create(name="Acme", slug="acme")
    CorporateEntity.objects.bulk_create(
        CorporateEntity(
            name=f"Zexel {i:03d}",
            slug=f"zexel-{i:03d}",
            manufacturer=mfr,
            status="active",
        )
        for i in range(n)
    )


def _seed_systems(n: int) -> None:
    mfr = Manufacturer.objects.create(name="Acme", slug="acme")
    System.objects.bulk_create(
        System(
            name=f"Zexel {i:03d}",
            slug=f"zexel-{i:03d}",
            manufacturer=mfr,
            status="active",
        )
        for i in range(n)
    )


PAGINATION_SPECS = [
    pytest.param("/api/cabinets/", _seed_taxonomy(Cabinet), id="cabinets"),
    pytest.param("/api/tags/", _seed_taxonomy(Tag), id="tags"),
    pytest.param("/api/game-formats/", _seed_taxonomy(GameFormat), id="game-formats"),
    pytest.param("/api/reward-types/", _seed_taxonomy(RewardType), id="reward-types"),
    pytest.param("/api/credit-roles/", _seed_taxonomy(CreditRole), id="credit-roles"),
    pytest.param(
        "/api/corporate-entities/", _seed_corporate_entities, id="corporate-entities"
    ),
    pytest.param("/api/systems/", _seed_systems, id="systems"),
    pytest.param("/api/series/", _seed_series, id="series"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "seed"), PAGINATION_SPECS)
class TestPaginatedListContract:
    """The shared contract across every core-backed entity: the ``{items, count}``
    shape, a page-invariant ``count`` total, disjoint offset pages (the per-entity
    ``ordering`` tuple is a total order), and server-side ``q``."""

    def test_shape_count_invariant_and_pages_disjoint(self, client, path, seed):
        seed(60)
        page1 = client.get(path, {"page": 1}).json()
        page2 = client.get(path, {"page": 2}).json()
        assert set(page1) == {"items", "count"}
        assert page1["count"] == page2["count"] >= 60
        assert len(page1["items"]) == DEFAULT_PAGE_SIZE
        slugs1 = {r["slug"] for r in page1["items"]}
        slugs2 = {r["slug"] for r in page2["items"]}
        assert slugs1.isdisjoint(slugs2)

    def test_q_filters_server_side(self, client, path, seed):
        seed(3)
        body = client.get(path, {"q": "zexel 001"}).json()
        assert body["count"] == 1
        assert [r["slug"] for r in body["items"]] == ["zexel-001"]


@pytest.mark.django_db
class TestSystemsManufacturerFilter:
    """The systems-only ``manufacturer`` slug filter — the server-side replacement for
    the page's old client ``<select>`` — narrows by manufacturer and composes with ``q``."""

    def _seed(self):
        williams = Manufacturer.objects.create(name="Williams", slug="williams")
        bally = Manufacturer.objects.create(name="Bally", slug="bally")
        System.objects.create(
            name="WPC", slug="wpc", manufacturer=williams, status="active"
        )
        System.objects.create(
            name="WPC-95", slug="wpc-95", manufacturer=williams, status="active"
        )
        System.objects.create(
            name="MPU-200", slug="mpu-200", manufacturer=bally, status="active"
        )

    def test_filters_by_manufacturer_slug(self, client):
        self._seed()
        body = client.get("/api/systems/", {"manufacturer": "williams"}).json()
        assert body["count"] == 2
        assert {s["slug"] for s in body["items"]} == {"wpc", "wpc-95"}

    def test_filter_composes_with_q(self, client):
        self._seed()
        body = client.get(
            "/api/systems/", {"manufacturer": "williams", "q": "95"}
        ).json()
        assert [s["slug"] for s in body["items"]] == ["wpc-95"]

    def test_unknown_manufacturer_yields_empty(self, client):
        self._seed()
        body = client.get("/api/systems/", {"manufacturer": "stern"}).json()
        assert body["count"] == 0
        assert body["items"] == []


@pytest.mark.django_db
class TestSeriesListThumbnail:
    """The paginated series row carries the batched ``_series_thumbnails`` image — the
    earliest-year model image among the series' titles — or ``None`` when there's none."""

    def test_row_carries_model_image(self, client):
        series = Series.objects.create(name="Saga", slug="saga", status="active")
        title = Title.objects.create(
            name="Saga I", slug="saga-i", status="active", series=series
        )
        make_machine_model(
            title=title,
            name="Saga I",
            slug="saga-i-m",
            year=1990,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        body = client.get("/api/series/").json()
        row = next(r for r in body["items"] if r["slug"] == "saga")
        assert row["title_count"] == 1
        assert row["thumbnail_url"] is not None

    def test_row_without_image_has_no_thumbnail(self, client):
        series = Series.objects.create(name="Plain", slug="plain", status="active")
        title = Title.objects.create(
            name="Plain I", slug="plain-i", status="active", series=series
        )
        make_machine_model(title=title, name="Plain I", slug="plain-i-m")
        body = client.get("/api/series/").json()
        row = next(r for r in body["items"] if r["slug"] == "plain")
        assert row["thumbnail_url"] is None

    def test_thumbnail_skips_imageless_earlier_model(self, client, user):
        """Regression: the earliest-year model may carry no image while a later one does
        (here via uploaded media on an ``extra_data``-empty model). The thumbnail must be
        the first **image-bearing** model in year order, not just the earliest model."""
        series = Series.objects.create(name="Saga", slug="saga", status="active")
        early = Title.objects.create(
            name="Saga 0", slug="saga-0", status="active", series=series
        )
        late = Title.objects.create(
            name="Saga 1", slug="saga-1", status="active", series=series
        )
        # Earliest model (1980), no image at all.
        make_machine_model(title=early, name="Saga 0", slug="saga-0-m", year=1980)
        # Later model (1990), image only via uploaded primary media — empty extra_data.
        late_model = make_machine_model(
            title=late, name="Saga 1", slug="saga-1-m", year=1990
        )
        asset = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="bg.jpg",
            mime_type="image/jpeg",
            byte_size=1024,
            width=800,
            height=600,
            uploaded_by=user,
        )
        EntityMedia.objects.create(
            content_type=ContentType.objects.get_for_model(MachineModel),
            object_id=late_model.pk,
            asset=asset,
            category="backglass",
            is_primary=True,
        )
        body = client.get("/api/series/").json()
        row = next(r for r in body["items"] if r["slug"] == "saga")
        assert row["thumbnail_url"] is not None
