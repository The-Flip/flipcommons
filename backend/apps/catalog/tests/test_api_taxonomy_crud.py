"""End-to-end tests for the 8 simple-taxonomy entities' create/delete/restore.

Covers representative entity shapes: ``tag`` (parentless),
``technology-subgeneration`` (parented), ``technology-generation`` (parent
with active-children blocking), and ``reward-type`` (shared detail schema for
PATCH but shared ``TaxonomySchema`` on create).
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import (
    DisplaySubtype,
    DisplayType,
    Franchise,
    GameplayFeature,
    GameplayFeatureAlias,
    MachineModel,
    RewardType,
    RewardTypeAlias,
    Series,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    ThemeAlias,
    Title,
)
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, path: str, body: JsonBody):
    return client.post(path, data=json.dumps(body), content_type="application/json")


# ── Create: parentless (Tag) ────────────────────────────────────────


@pytest.mark.django_db
class TestTagCreate:
    def test_anonymous_rejected(self, client):
        resp = _post(client, "/api/tags/", {"name": "Widebody", "slug": "widebody"})
        assert resp.status_code in (401, 403)
        assert not Tag.objects.filter(slug="widebody").exists()

    def test_creates_tag_with_three_claims(self, client, user):
        client.force_login(user)
        resp = _post(client, "/api/tags/", {"name": "Widebody", "slug": "widebody"})
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "widebody"
        assert body["name"] == "Widebody"

        tag = Tag.objects.get(slug="widebody")
        assert tag.status == "active"

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"name", "slug", "status"}

    def test_duplicate_name_rejected(self, client, user):
        Tag.objects.create(name="Widebody", slug="widebody-existing", status="active")
        client.force_login(user)
        resp = _post(client, "/api/tags/", {"name": "Widebody", "slug": "widebody-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_invalid_slug_rejected(self, client, user):
        client.force_login(user)
        resp = _post(
            client, "/api/tags/", {"name": "Widebody", "slug": "Widebody_Case"}
        )
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]

    def test_duplicate_slug_rejected(self, client, user):
        # Reserve the slug via a soft-deleted row — the slug is still taken
        # at the DB level, and the pre-check must surface a field error
        # rather than letting the insert fail with an IntegrityError.
        Tag.objects.create(name="Existing", slug="widebody", status="deleted")
        client.force_login(user)
        resp = _post(client, "/api/tags/", {"name": "Widebody", "slug": "widebody"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]
        assert not Tag.objects.filter(slug="widebody", status="active").exists()

    def test_name_too_long_rejected(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/tags/",
            {"name": "x" * 201, "slug": "too-long"},
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]


# ── Create: rate limit ─────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateRateLimit:
    def test_non_staff_blocked_after_limit(self, client, user, settings):
        # Use whatever the shipped bucket is — just show enforcement bites.
        from apps.provenance.rate_limits import CREATE_RATE_LIMIT_SPEC

        client.force_login(user)
        limit = CREATE_RATE_LIMIT_SPEC.limit
        for i in range(limit):
            r = _post(client, "/api/tags/", {"name": f"Tag {i}", "slug": f"tag-{i}"})
            assert r.status_code == 201, r.content
        r = _post(client, "/api/tags/", {"name": "Tag over", "slug": "tag-over"})
        assert r.status_code == 429

    def test_staff_bypasses(self, client, staff):
        from apps.provenance.rate_limits import CREATE_RATE_LIMIT_SPEC

        client.force_login(staff)
        limit = CREATE_RATE_LIMIT_SPEC.limit
        for i in range(limit + 1):
            r = _post(client, "/api/tags/", {"name": f"Tag {i}", "slug": f"tag-{i}"})
            assert r.status_code == 201, r.content


# ── Create: parented (TechnologySubgeneration) ─────────────────────


@pytest.mark.django_db
class TestSubgenerationCreate:
    @pytest.fixture
    def parent(self, db):
        return TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", status="active"
        )

    def test_creates_subgen_under_active_parent(self, client, user, parent):
        client.force_login(user)
        resp = _post(
            client,
            f"/api/technology-generations/{parent.slug}/subgenerations/",
            {"name": "MPU", "slug": "mpu"},
        )
        assert resp.status_code == 201, resp.content

        sub = TechnologySubgeneration.objects.get(slug="mpu")
        assert sub.technology_generation_id == parent.pk

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        claims = {c.field_name: c.value for c in Claim.objects.filter(changeset=cs)}
        assert claims.keys() == {"name", "slug", "status", "technology_generation"}
        # FK claim stores the parent's slug string, not the PK.
        assert claims["technology_generation"] == parent.slug

    def test_unknown_parent_slug_returns_404(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/technology-generations/does-not-exist/subgenerations/",
            {"name": "MPU", "slug": "mpu"},
        )
        assert resp.status_code == 404

    def test_deleted_parent_returns_404(self, client, user, parent):
        parent.status = "deleted"
        parent.save(update_fields=["status"])
        client.force_login(user)
        resp = _post(
            client,
            f"/api/technology-generations/{parent.slug}/subgenerations/",
            {"name": "MPU", "slug": "mpu"},
        )
        assert resp.status_code == 404


# ── Create: reward-types shares the same shape ──────────────────────


@pytest.mark.django_db
class TestRewardTypeCreate:
    def test_creates_reward_type(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/reward-types/",
            {"name": "Extra Ball", "slug": "extra-ball"},
        )
        assert resp.status_code == 201, resp.content
        assert RewardType.objects.get(slug="extra-ball").status == "active"


# ── Delete ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestTagDelete:
    @pytest.fixture
    def tag(self, db):
        return Tag.objects.create(name="Widebody", slug="widebody", status="active")

    def test_preview_unblocked(self, client, user, tag):
        client.force_login(user)
        resp = client.get(f"/api/tags/{tag.slug}/delete-preview/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["slug"] == tag.slug
        assert body["blocked_by"] == []
        assert body["active_children_count"] == 0

    def test_delete_happy_path(self, client, user, tag):
        client.force_login(user)
        resp = _post(client, f"/api/tags/{tag.slug}/delete/", {})
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["affected_slugs"] == [tag.slug]

        tag.refresh_from_db()
        assert tag.status == "deleted"

        cs = ChangeSet.objects.get(pk=body["changeset_id"])
        assert cs.action == ChangeSetAction.DELETE


@pytest.mark.django_db
class TestTechGenDeleteBlockedByActiveChild:
    """Parents refuse to delete while they have active children.

    Response body must carry ``blocked_by: []`` (empty list, not missing) so
    the shared frontend classifier in delete-flow.ts treats the 422 as a
    ``blocked`` outcome rather than a generic form error.
    """

    @pytest.fixture
    def tech_gen(self, db):
        return TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", status="active"
        )

    @pytest.fixture
    def subgen(self, db, tech_gen):
        return TechnologySubgeneration.objects.create(
            name="MPU",
            slug="mpu",
            status="active",
            technology_generation=tech_gen,
        )

    def test_preview_surfaces_child_count(self, client, user, tech_gen, subgen):
        client.force_login(user)
        resp = client.get(
            f"/api/technology-generations/{tech_gen.slug}/delete-preview/"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["active_children_count"] == 1
        # Blocked → provenance count short-circuits to zero.
        assert body["changeset_count"] == 0

    def test_delete_blocked_with_structured_body(self, client, user, tech_gen, subgen):
        client.force_login(user)
        resp = _post(client, f"/api/technology-generations/{tech_gen.slug}/delete/", {})
        assert resp.status_code == 422
        body = resp.json()
        assert body["blocked_by"] == []
        assert body["active_children_count"] == 1

        tech_gen.refresh_from_db()
        assert tech_gen.status == "active"

    def test_delete_proceeds_after_child_deleted(self, client, user, tech_gen, subgen):
        subgen.status = "deleted"
        subgen.save(update_fields=["status"])
        client.force_login(user)
        resp = _post(client, f"/api/technology-generations/{tech_gen.slug}/delete/", {})
        assert resp.status_code == 200, resp.content


@pytest.mark.django_db
class TestTechGenDeleteBlockedByProtectReferrer:
    """PROTECT referrer (an active MachineModel pointing at the tech-gen)
    must block with ``blocked_by`` populated by the generic walker."""

    def test_delete_blocked_by_protect_referrer(self, client, user, db):
        tech_gen = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", status="active"
        )
        title = Title.objects.create(
            name="Addams Family", slug="addams-family", status="active"
        )
        MachineModel.objects.create(
            name="Addams Family",
            slug="addams-family",
            title=title,
            status="active",
            technology_generation=tech_gen,
        )

        client.force_login(user)
        resp = _post(client, f"/api/technology-generations/{tech_gen.slug}/delete/", {})
        assert resp.status_code == 422
        body = resp.json()
        assert len(body["blocked_by"]) >= 1
        assert body["active_children_count"] == 0


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestTagRestore:
    def test_restores_deleted_tag(self, client, user):
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="deleted")
        client.force_login(user)
        resp = _post(client, f"/api/tags/{tag.slug}/restore/", {})
        assert resp.status_code == 200, resp.content
        tag.refresh_from_db()
        assert tag.status == "active"

        cs = ChangeSet.objects.filter(user=user, action=ChangeSetAction.EDIT).latest(
            "pk"
        )
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"status"}

    def test_restore_rejects_active(self, client, user):
        Tag.objects.create(name="Widebody", slug="widebody", status="active")
        client.force_login(user)
        resp = _post(client, "/api/tags/widebody/restore/", {})
        assert resp.status_code == 422


@pytest.mark.django_db
class TestSubgenRestoreRequiresActiveParent:
    def test_blocked_when_parent_deleted(self, client, user, db):
        parent = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", status="deleted"
        )
        sub = TechnologySubgeneration.objects.create(
            name="MPU", slug="mpu", status="deleted", technology_generation=parent
        )
        client.force_login(user)
        resp = _post(client, f"/api/technology-subgenerations/{sub.slug}/restore/", {})
        assert resp.status_code == 422
        # Loose match — the exact wording can drift; the contract is that the
        # body surfaces the parent's name so the UI can prompt for that first.
        assert parent.name in resp.json()["detail"]

        sub.refresh_from_db()
        assert sub.status == "deleted"

    def test_succeeds_when_parent_active(self, client, user, db):
        parent = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", status="active"
        )
        sub = TechnologySubgeneration.objects.create(
            name="MPU", slug="mpu", status="deleted", technology_generation=parent
        )
        client.force_login(user)
        resp = _post(client, f"/api/technology-subgenerations/{sub.slug}/restore/", {})
        assert resp.status_code == 200, resp.content


# ── Display-subtype mirrors subgeneration ───────────────────────────


@pytest.mark.django_db
class TestDisplaySubtypeCreate:
    def test_nested_route_and_fk_claim(self, client, user, db):
        parent = DisplayType.objects.create(name="LCD", slug="lcd", status="active")
        client.force_login(user)
        resp = _post(
            client,
            f"/api/display-types/{parent.slug}/subtypes/",
            {"name": "HD LCD", "slug": "hd-lcd"},
        )
        assert resp.status_code == 201, resp.content
        assert DisplaySubtype.objects.get(slug="hd-lcd").display_type_id == parent.pk


@pytest.mark.django_db
class TestDisplaySubtypeRestoreRequiresActiveParent:
    """Symmetry with subgeneration — same code path, wired via a different
    ``parent_field`` kwarg on the registration. Covered so that a future
    edit to the display-subtype registration can't silently drop the
    deleted-parent check."""

    def test_blocked_when_parent_deleted(self, client, user, db):
        parent = DisplayType.objects.create(name="LCD", slug="lcd", status="deleted")
        sub = DisplaySubtype.objects.create(
            name="HD LCD", slug="hd-lcd", status="deleted", display_type=parent
        )
        client.force_login(user)
        resp = _post(client, f"/api/display-subtypes/{sub.slug}/restore/", {})
        assert resp.status_code == 422
        assert parent.name in resp.json()["detail"]

        sub.refresh_from_db()
        assert sub.status == "deleted"


# ── Delete-preview carries parent breadcrumb on parented entities ────


@pytest.mark.django_db
class TestParentedDeletePreviewBreadcrumb:
    """Preview must surface ``parent`` (Ref) for subgen and subtype so the
    delete confirmation UI can render the breadcrumb without a second
    round-trip. Parentless entities return null."""

    def test_subgeneration_preview_includes_parent(self, client, user, db):
        parent = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", status="active"
        )
        sub = TechnologySubgeneration.objects.create(
            name="MPU", slug="mpu", status="active", technology_generation=parent
        )
        client.force_login(user)
        resp = client.get(f"/api/technology-subgenerations/{sub.slug}/delete-preview/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent"] == {"name": parent.name, "public_id": parent.public_id}

    def test_parentless_preview_has_null_parent(self, client, user, db):
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="active")
        client.force_login(user)
        resp = client.get(f"/api/tags/{tag.slug}/delete-preview/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent"] is None


# ── Delete blocked by active M2M referrer ────────────────────────────


def _title_with_model(slug: str) -> tuple[Title, MachineModel]:
    title = Title.objects.create(name=slug.title(), slug=slug, status="active")
    mm = MachineModel.objects.create(
        name=slug.title(), slug=f"{slug}-pro", title=title, status="active"
    )
    return title, mm


@pytest.mark.django_db
class TestTagDeleteBlockedByActiveMachineModel:
    """Active MachineModel applying a Tag via ``MachineModelTag`` must block
    Tag delete. The through-table has no lifecycle of its own, so the
    walker reaches the referrer through ``soft_delete_usage_blockers``."""

    def test_preview_surfaces_blocker(self, client, user):
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="active")
        _, mm = _title_with_model("mm")
        mm.tags.add(tag)

        client.force_login(user)
        resp = client.get(f"/api/tags/{tag.slug}/delete-preview/")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["blocked_by"]) == 1
        assert body["blocked_by"][0]["entity_type"] == "model"
        assert body["changeset_count"] == 0  # short-circuited while blocked

    def test_delete_returns_422_blocked_body(self, client, user):
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="active")
        _, mm = _title_with_model("mm")
        mm.tags.add(tag)

        client.force_login(user)
        resp = _post(client, f"/api/tags/{tag.slug}/delete/", {})
        assert resp.status_code == 422
        body = resp.json()
        assert len(body["blocked_by"]) == 1
        tag.refresh_from_db()
        assert tag.status == "active"

    def test_delete_proceeds_when_referrer_soft_deleted(self, client, user):
        tag = Tag.objects.create(name="Widebody", slug="widebody", status="active")
        _, mm = _title_with_model("mm")
        mm.tags.add(tag)
        mm.status = "deleted"
        mm.save(update_fields=["status"])

        client.force_login(user)
        resp = _post(client, f"/api/tags/{tag.slug}/delete/", {})
        assert resp.status_code == 200, resp.content


@pytest.mark.django_db
class TestRewardTypeDeleteBlockedByActiveMachineModel:
    def test_delete_returns_422_blocked_body(self, client, user):
        rt = RewardType.objects.create(
            name="Extra Ball", slug="extra-ball", status="active"
        )
        _, mm = _title_with_model("mm")
        mm.reward_types.add(rt)

        client.force_login(user)
        resp = _post(client, f"/api/reward-types/{rt.slug}/delete/", {})
        assert resp.status_code == 422
        body = resp.json()
        assert len(body["blocked_by"]) == 1
        rt.refresh_from_db()
        assert rt.status == "active"


# ── Alias-collision on create ───────────────────────────────────────


@pytest.mark.django_db
class TestRewardTypeCreateAliasCollision:
    """Per RecordCreateDelete.md, aliases must count as results for duplicate
    prevention — the API must reject a create whose name collides with an
    existing alias, not just with another entity's canonical name."""

    def test_create_rejects_name_matching_existing_alias(self, client, user):
        existing = RewardType.objects.create(
            name="Extra Ball", slug="extra-ball", status="active"
        )
        RewardTypeAlias.objects.create(reward_type=existing, value="Shoot Again")

        client.force_login(user)
        resp = _post(
            client,
            "/api/reward-types/",
            {"name": "Shoot Again", "slug": "shoot-again"},
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]
        assert not RewardType.objects.filter(slug="shoot-again").exists()


# ── Theme: create / delete / restore ────────────────────────────────


@pytest.mark.django_db
class TestThemeCreate:
    def test_creates_theme_with_three_claims(self, client, user):
        client.force_login(user)
        resp = _post(client, "/api/themes/", {"name": "Horror", "slug": "horror"})
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "horror"
        assert body["name"] == "Horror"

        theme = Theme.objects.get(slug="horror")
        assert theme.status == "active"

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"name", "slug", "status"}

    def test_duplicate_name_rejected(self, client, user):
        Theme.objects.create(name="Horror", slug="horror-existing", status="active")
        client.force_login(user)
        resp = _post(client, "/api/themes/", {"name": "Horror", "slug": "horror-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_alias_collision_rejected(self, client, user):
        existing = Theme.objects.create(name="Horror", slug="horror", status="active")
        ThemeAlias.objects.create(theme=existing, value="Scary")

        client.force_login(user)
        resp = _post(client, "/api/themes/", {"name": "Scary", "slug": "scary"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]
        assert not Theme.objects.filter(slug="scary").exists()


@pytest.mark.django_db
class TestThemeDelete:
    def test_delete_happy_path(self, client, user):
        theme = Theme.objects.create(name="Horror", slug="horror", status="active")
        client.force_login(user)
        resp = _post(client, f"/api/themes/{theme.slug}/delete/", {})
        assert resp.status_code == 200, resp.content
        theme.refresh_from_db()
        assert theme.status == "deleted"

    def test_delete_blocked_by_active_machine_model(self, client, user):
        theme = Theme.objects.create(name="Horror", slug="horror", status="active")
        _, mm = _title_with_model("mm")
        mm.themes.add(theme)

        client.force_login(user)
        resp = _post(client, f"/api/themes/{theme.slug}/delete/", {})
        assert resp.status_code == 422
        assert len(resp.json()["blocked_by"]) == 1
        theme.refresh_from_db()
        assert theme.status == "active"

    def test_delete_blocked_by_active_child(self, client, user):
        parent = Theme.objects.create(name="Horror", slug="horror", status="active")
        child = Theme.objects.create(name="Slasher", slug="slasher", status="active")
        child.parents.add(parent)

        client.force_login(user)
        resp = _post(client, f"/api/themes/{parent.slug}/delete/", {})
        assert resp.status_code == 422
        assert any(b["slug"] == "slasher" for b in resp.json()["blocked_by"])
        parent.refresh_from_db()
        assert parent.status == "active"


@pytest.mark.django_db
class TestThemeRestore:
    def test_restore_happy_path(self, client, user):
        theme = Theme.objects.create(name="Horror", slug="horror", status="deleted")
        client.force_login(user)
        resp = _post(client, f"/api/themes/{theme.slug}/restore/", {})
        assert resp.status_code == 200, resp.content
        theme.refresh_from_db()
        assert theme.status == "active"


# ── GameplayFeature: create / delete / restore ──────────────────────


@pytest.mark.django_db
class TestGameplayFeatureCreate:
    def test_creates_feature_with_three_claims(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/gameplay-features/",
            {"name": "Multiball", "slug": "multiball"},
        )
        assert resp.status_code == 201, resp.content
        feature = GameplayFeature.objects.get(slug="multiball")
        assert feature.status == "active"

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"name", "slug", "status"}

    def test_alias_collision_rejected(self, client, user):
        existing = GameplayFeature.objects.create(
            name="Multiball", slug="multiball", status="active"
        )
        GameplayFeatureAlias.objects.create(feature=existing, value="Multi Ball")

        client.force_login(user)
        resp = _post(
            client,
            "/api/gameplay-features/",
            {"name": "Multi Ball", "slug": "multi-ball"},
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]


@pytest.mark.django_db
class TestGameplayFeatureDelete:
    def test_delete_blocked_by_active_machine_model(self, client, user):
        feature = GameplayFeature.objects.create(
            name="Multiball", slug="multiball", status="active"
        )
        _, mm = _title_with_model("mm")
        mm.gameplay_features.add(feature)

        client.force_login(user)
        resp = _post(client, f"/api/gameplay-features/{feature.slug}/delete/", {})
        assert resp.status_code == 422
        assert len(resp.json()["blocked_by"]) == 1

    def test_delete_happy_path(self, client, user):
        feature = GameplayFeature.objects.create(
            name="Multiball", slug="multiball", status="active"
        )
        client.force_login(user)
        resp = _post(client, f"/api/gameplay-features/{feature.slug}/delete/", {})
        assert resp.status_code == 200, resp.content
        feature.refresh_from_db()
        assert feature.status == "deleted"


@pytest.mark.django_db
class TestGameplayFeatureRestore:
    def test_restore_happy_path(self, client, user):
        feature = GameplayFeature.objects.create(
            name="Multiball", slug="multiball", status="deleted"
        )
        client.force_login(user)
        resp = _post(client, f"/api/gameplay-features/{feature.slug}/restore/", {})
        assert resp.status_code == 200, resp.content
        feature.refresh_from_db()
        assert feature.status == "active"


# ── Series: create / delete / restore ───────────────────────────────


@pytest.mark.django_db
class TestSeriesCreate:
    def test_creates_series_with_three_claims(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/series/",
            {"name": "Eight Ball", "slug": "eight-ball"},
        )
        assert resp.status_code == 201, resp.content
        series = Series.objects.get(slug="eight-ball")
        assert series.status == "active"

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"name", "slug", "status"}

    def test_duplicate_name_rejected(self, client, user):
        Series.objects.create(name="Eight Ball", slug="eight-ball", status="active")
        client.force_login(user)
        resp = _post(
            client, "/api/series/", {"name": "Eight Ball", "slug": "eight-ball-2"}
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_duplicate_slug_rejected(self, client, user):
        Series.objects.create(name="Existing", slug="eight-ball", status="deleted")
        client.force_login(user)
        resp = _post(
            client, "/api/series/", {"name": "Eight Ball", "slug": "eight-ball"}
        )
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


@pytest.mark.django_db
class TestSeriesDelete:
    def test_delete_happy_path(self, client, user):
        series = Series.objects.create(
            name="Eight Ball", slug="eight-ball", status="active"
        )
        client.force_login(user)
        resp = _post(client, f"/api/series/{series.slug}/delete/", {})
        assert resp.status_code == 200, resp.content
        series.refresh_from_db()
        assert series.status == "deleted"

    def test_delete_blocked_by_active_title(self, client, user):
        series = Series.objects.create(
            name="Eight Ball", slug="eight-ball", status="active"
        )
        Title.objects.create(
            name="Eight Ball", slug="eight-ball-title", status="active", series=series
        )

        client.force_login(user)
        resp = _post(client, f"/api/series/{series.slug}/delete/", {})
        assert resp.status_code == 422
        assert len(resp.json()["blocked_by"]) == 1
        series.refresh_from_db()
        assert series.status == "active"

    def test_delete_proceeds_when_referring_title_soft_deleted(self, client, user):
        series = Series.objects.create(
            name="Eight Ball", slug="eight-ball", status="active"
        )
        Title.objects.create(
            name="Eight Ball",
            slug="eight-ball-title",
            status="deleted",
            series=series,
        )

        client.force_login(user)
        resp = _post(client, f"/api/series/{series.slug}/delete/", {})
        assert resp.status_code == 200, resp.content
        series.refresh_from_db()
        assert series.status == "deleted"

    def test_preview_counts_create_changeset(self, client, user):
        """A freshly-created Series carries a CREATE ChangeSet, which the
        preview must surface so the UI's impact summary isn't silently zero."""
        client.force_login(user)
        create_resp = _post(
            client, "/api/series/", {"name": "Eight Ball", "slug": "eight-ball"}
        )
        assert create_resp.status_code == 201

        preview = client.get("/api/series/eight-ball/delete-preview/")
        assert preview.status_code == 200
        assert preview.json()["changeset_count"] == 1


@pytest.mark.django_db
class TestSeriesRestore:
    def test_restore_happy_path(self, client, user):
        series = Series.objects.create(
            name="Eight Ball", slug="eight-ball", status="deleted"
        )
        client.force_login(user)
        resp = _post(client, f"/api/series/{series.slug}/restore/", {})
        assert resp.status_code == 200, resp.content
        series.refresh_from_db()
        assert series.status == "active"

        # Restore returns the full detail shape, not a minimal status echo.
        body = resp.json()
        assert body["slug"] == "eight-ball"
        assert "titles" in body
        assert "credits" in body

    def test_restore_rejects_active(self, client, user):
        series = Series.objects.create(
            name="Eight Ball", slug="eight-ball", status="active"
        )
        client.force_login(user)
        resp = _post(client, f"/api/series/{series.slug}/restore/", {})
        assert resp.status_code == 422


# ── Franchise: create / delete / restore ────────────────────────────


@pytest.mark.django_db
class TestFranchiseCreate:
    def test_creates_franchise_with_three_claims(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/franchises/",
            {"name": "Indiana Jones", "slug": "indiana-jones"},
        )
        assert resp.status_code == 201, resp.content
        fr = Franchise.objects.get(slug="indiana-jones")
        assert fr.status == "active"

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"name", "slug", "status"}

    def test_duplicate_name_rejected(self, client, user):
        Franchise.objects.create(
            name="Indiana Jones", slug="indiana-jones", status="active"
        )
        client.force_login(user)
        resp = _post(
            client,
            "/api/franchises/",
            {"name": "Indiana Jones", "slug": "indiana-jones-2"},
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]


@pytest.mark.django_db
class TestFranchiseDelete:
    def test_delete_happy_path(self, client, user):
        fr = Franchise.objects.create(
            name="Indiana Jones", slug="indiana-jones", status="active"
        )
        client.force_login(user)
        resp = _post(client, f"/api/franchises/{fr.slug}/delete/", {})
        assert resp.status_code == 200, resp.content
        fr.refresh_from_db()
        assert fr.status == "deleted"

    def test_delete_blocked_by_active_title(self, client, user):
        fr = Franchise.objects.create(
            name="Indiana Jones", slug="indiana-jones", status="active"
        )
        Title.objects.create(
            name="Indiana Jones",
            slug="indy-title",
            status="active",
            franchise=fr,
        )

        client.force_login(user)
        resp = _post(client, f"/api/franchises/{fr.slug}/delete/", {})
        assert resp.status_code == 422
        assert len(resp.json()["blocked_by"]) == 1
        fr.refresh_from_db()
        assert fr.status == "active"

    def test_preview_surfaces_blocker_slug(self, client, user):
        fr = Franchise.objects.create(
            name="Indiana Jones", slug="indiana-jones", status="active"
        )
        Title.objects.create(
            name="Indiana Jones",
            slug="indy-title",
            status="active",
            franchise=fr,
        )

        client.force_login(user)
        resp = client.get(f"/api/franchises/{fr.slug}/delete-preview/")
        assert resp.status_code == 200
        body = resp.json()
        assert any(b["slug"] == "indy-title" for b in body["blocked_by"])


@pytest.mark.django_db
class TestFranchiseRestore:
    def test_restore_happy_path(self, client, user):
        fr = Franchise.objects.create(
            name="Indiana Jones", slug="indiana-jones", status="deleted"
        )
        client.force_login(user)
        resp = _post(client, f"/api/franchises/{fr.slug}/restore/", {})
        assert resp.status_code == 200, resp.content
        fr.refresh_from_db()
        assert fr.status == "active"

        # Restore returns the full detail shape, not a minimal status echo.
        body = resp.json()
        assert body["slug"] == "indiana-jones"
        assert "titles" in body


# The franchise list endpoint (paginated ``GET /`` + full ``GET /all/``) is covered by
# ``test_api_catalog_list.py``.
