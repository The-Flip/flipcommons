"""Coverage for newer PATCH claims endpoints added after the initial edit work."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from apps.catalog.models import (
    Cabinet,
    Credit,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    Franchise,
    GameFormat,
    Manufacturer,
    Person,
    ProductionStatus,
    RewardType,
    Series,
    System,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.test_factories import make_citation_source
from apps.core.types import JsonBody
from apps.provenance.attribution import actor_user
from apps.provenance.models import ChangeSet, Source
from apps.provenance.test_factories import (
    make_claim,
    make_ingest_source,
)

User = get_user_model()


@pytest.fixture
def citation_source(db):
    return make_citation_source(
        name="Replay Flyer",
        source_type="book",
        author="Staff",
        year=1980,
    )


def _patch(client, path: str, body: JsonBody):
    return client.patch(
        path,
        data=json.dumps(body),
        content_type="application/json",
    )


def _get_bootstrap_source():
    """Get or create a low-priority source for bootstrap name claims."""
    src, _ = Source.objects.get_or_create(
        slug="bootstrap",
        defaults={"name": "Bootstrap", "source_type": "editorial", "priority": 1},
    )
    return src


def _assert_name_claim(entity):
    """Assert a bootstrap name claim for entities with non-unique name fields."""
    make_claim(entity, "name", entity.name, ingest_source=_get_bootstrap_source())
    return entity


def _create_franchise():
    return Franchise.objects.create(name="Star Trek", slug="star-trek")


def _create_series():
    return _assert_name_claim(
        Series.objects.create(name="Eight Ball", slug="eight-ball")
    )


def _create_conflicting_franchise():
    return Franchise.objects.create(name="Star Trek Legacy", slug="star-trek-legacy")


def _create_conflicting_series():
    return _assert_name_claim(
        Series.objects.create(name="Eight Ball Classics", slug="eight-ball-classics")
    )


def _create_system():
    mfr, _ = Manufacturer.objects.get_or_create(
        slug="williams", defaults={"name": "Williams"}
    )
    return System.objects.create(name="WPC-95", slug="wpc-95", manufacturer=mfr)


def _create_technology_generation():
    return TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")


def _create_technology_subgeneration():
    gen = TechnologyGeneration.objects.create(
        name="Electromechanical", slug="electromechanical"
    )
    return _assert_name_claim(
        TechnologySubgeneration.objects.create(
            name="Late EM",
            slug="late-em",
            technology_generation=gen,
        )
    )


def _create_display_type():
    return DisplayType.objects.create(name="DMD", slug="dmd")


def _create_display_subtype():
    display_type = DisplayType.objects.create(name="LCD", slug="lcd")
    return _assert_name_claim(
        DisplaySubtype.objects.create(
            name="HD LCD",
            slug="hd-lcd",
            display_type=display_type,
        )
    )


def _create_cabinet():
    return Cabinet.objects.create(name="Widebody", slug="widebody")


def _create_game_format():
    return GameFormat.objects.create(name="Pinball", slug="pinball")


def _create_reward_type():
    return RewardType.objects.create(name="Replay", slug="replay")


def _create_tag():
    return Tag.objects.create(name="Prototype", slug="prototype")


def _create_production_status():
    return ProductionStatus.objects.create(name="Unreleased", slug="unreleased")


def _create_credit_role():
    # Use a non-canonical name/slug so the test doesn't collide with the
    # credit-roles fixture that autouses canonical roles in conftest.
    return CreditRole.objects.create(name="Test Role", slug="test-role")


def _create_conflicting_credit_role():
    return CreditRole.objects.create(name="Other Role", slug="other-role")


PATCH_CASES = [
    pytest.param(
        "/api/franchises/{slug}/claims/",
        _create_franchise,
        "description",
        "Updated franchise copy",
        "franchises",
        id="franchise",
    ),
    pytest.param(
        "/api/series/{slug}/claims/",
        _create_series,
        "description",
        "Updated series copy",
        "series",
        id="series",
    ),
    pytest.param(
        "/api/systems/{slug}/claims/",
        _create_system,
        "description",
        "Updated system copy",
        "systems",
        id="system",
    ),
    pytest.param(
        "/api/technology-generations/{slug}/claims/",
        _create_technology_generation,
        "description",
        "Updated technology generation copy",
        "technology-generations",
        id="technology-generation",
    ),
    pytest.param(
        "/api/technology-subgenerations/{slug}/claims/",
        _create_technology_subgeneration,
        "description",
        "Updated technology subgeneration copy",
        "technology-subgenerations",
        id="technology-subgeneration",
    ),
    pytest.param(
        "/api/display-types/{slug}/claims/",
        _create_display_type,
        "description",
        "Updated display type copy",
        "display-types",
        id="display-type",
    ),
    pytest.param(
        "/api/display-subtypes/{slug}/claims/",
        _create_display_subtype,
        "description",
        "Updated display subtype copy",
        "display-subtypes",
        id="display-subtype",
    ),
    pytest.param(
        "/api/cabinets/{slug}/claims/",
        _create_cabinet,
        "description",
        "Updated cabinet copy",
        "cabinets",
        id="cabinet",
    ),
    pytest.param(
        "/api/game-formats/{slug}/claims/",
        _create_game_format,
        "description",
        "Updated game format copy",
        "game-formats",
        id="game-format",
    ),
    pytest.param(
        "/api/reward-types/{slug}/claims/",
        _create_reward_type,
        "description",
        "Updated reward type copy",
        "reward-types",
        id="reward-type",
    ),
    pytest.param(
        "/api/tags/{slug}/claims/",
        _create_tag,
        "description",
        "Updated tag copy",
        "tags",
        id="tag",
    ),
    pytest.param(
        "/api/production-statuses/{slug}/claims/",
        _create_production_status,
        "description",
        "Updated production status copy",
        "production-statuses",
        id="production-status",
    ),
    pytest.param(
        "/api/credit-roles/{slug}/claims/",
        _create_credit_role,
        "description",
        "Updated credit role copy",
        "credit-roles",
        id="credit-role",
    ),
]

SLUG_EDIT_CASES = [
    pytest.param(
        "/api/franchises/{slug}/claims/",
        _create_franchise,
        _create_conflicting_franchise,
        "star-trek-remastered",
        "/api/pages/franchise/{slug}",
        id="franchise",
    ),
    pytest.param(
        "/api/series/{slug}/claims/",
        _create_series,
        _create_conflicting_series,
        "eight-ball-classics",
        "/api/pages/series/{slug}",
        id="series",
    ),
    pytest.param(
        "/api/credit-roles/{slug}/claims/",
        _create_credit_role,
        _create_conflicting_credit_role,
        "test-role-renamed",
        "/api/pages/credit-role/{slug}",
        id="credit-role",
    ),
]


@pytest.mark.django_db
class TestAdditionalPatchClaimEndpoints:
    @pytest.mark.parametrize(
        ("path_template", "factory", "field_name", "field_value", "resource_name"),
        PATCH_CASES,
    )
    def test_anonymous_gets_401(
        self, client, path_template, factory, field_name, field_value, resource_name
    ):
        entity = factory()
        resp = _patch(
            client,
            path_template.format(slug=entity.slug),
            {"fields": {field_name: field_value}},
        )
        assert resp.status_code in (401, 403), resource_name

    def test_empty_fields_returns_422(self, client, user):
        entity = _create_franchise()
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/franchises/{entity.slug}/claims/",
            {"fields": {}},
        )
        assert resp.status_code == 422

    def test_unknown_field_returns_422(self, client, user):
        entity = _create_reward_type()
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/reward-types/{entity.slug}/claims/",
            {"fields": {"nonexistent_field": "bad"}},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        ("path_template", "factory", "field_name", "field_value", "resource_name"),
        PATCH_CASES,
    )
    def test_creates_claim_changeset(
        self,
        client,
        user,
        path_template,
        factory,
        field_name,
        field_value,
        resource_name,
    ):
        entity = factory()
        client.force_login(user)

        resp = _patch(
            client,
            path_template.format(slug=entity.slug),
            {"fields": {field_name: field_value}},
        )

        assert resp.status_code == 200, resource_name
        data = resp.json()
        assert data["description"]["text"] == field_value

        entity.refresh_from_db()
        assert entity.description == field_value

        claim = entity.claims.get(
            actor=user.actor, field_name=field_name, is_active=True
        )
        assert claim.value == field_value

        # Some factories assert a seed (ingest) name claim, so filter to the
        # user's changeset rather than assuming it's the only row.
        assert ChangeSet.objects.filter(actor=user.actor).count() == 1
        changeset = ChangeSet.objects.get(actor=user.actor)
        assert actor_user(changeset.actor) == user
        assert changeset.claims.count() == 1

    @pytest.mark.parametrize(
        ("path_template", "factory", "_conflict_factory", "new_slug", "page_template"),
        SLUG_EDIT_CASES,
    )
    def test_slug_can_be_changed(
        self,
        client,
        user,
        path_template,
        factory,
        _conflict_factory,
        new_slug,
        page_template,
    ):
        entity = factory()
        old_slug = entity.slug
        client.force_login(user)

        resp = _patch(
            client,
            path_template.format(slug=old_slug),
            {"fields": {"slug": new_slug}},
        )

        assert resp.status_code == 200
        assert resp.json()["slug"] == new_slug

        entity.refresh_from_db()
        assert entity.slug == new_slug
        assert client.get(page_template.format(slug=new_slug)).status_code == 200
        assert client.get(page_template.format(slug=old_slug)).status_code == 404

    @pytest.mark.parametrize(
        ("path_template", "factory", "conflict_factory", "_new_slug", "_page_template"),
        SLUG_EDIT_CASES,
    )
    def test_duplicate_slug_returns_422(
        self,
        client,
        user,
        path_template,
        factory,
        conflict_factory,
        _new_slug,
        _page_template,
    ):
        entity = factory()
        conflict = conflict_factory()
        client.force_login(user)

        resp = _patch(
            client,
            path_template.format(slug=entity.slug),
            {"fields": {"slug": conflict.slug}},
        )

        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()


@pytest.mark.django_db
class TestPatchSeriesResponseShape:
    def test_patch_response_stays_slim_and_preserves_credits(
        self, client, user, williams_entity, credit_roles
    ):
        series = Series.objects.create(name="Eight Ball", slug="eight-ball")
        _assert_name_claim(series)
        title = Title.objects.create(name="Eight Ball Deluxe", slug="eight-ball-deluxe")
        title.series_id = series.pk
        title.save(update_fields=["series"])
        make_machine_model(
            name="Eight Ball Deluxe",
            slug="eight-ball-deluxe",
            title=title,
            corporate_entity=williams_entity,
            production_year=1981,
        )
        person = Person.objects.create(name="George Christian", slug="george-christian")
        role = CreditRole.objects.get(slug="design")
        Credit.objects.create(series=series, person=person, role=role)

        client.force_login(user)
        resp = _patch(
            client,
            f"/api/series/{series.slug}/claims/",
            {"fields": {"description": "Updated series copy"}},
        )

        assert resp.status_code == 200
        data = resp.json()
        # The page/edit-response split: no embedded game list on a save.
        assert "titles" not in data
        assert "games" not in data
        assert data["credits"] == [
            {
                "person": {"name": person.name, "public_id": person.public_id},
                "role": role.slug,
                "role_display": role.name,
                "role_sort_order": role.display_order,
            }
        ]


@pytest.mark.django_db
class TestPatchSystemResponseShape:
    def test_patch_response_stays_slim_and_preserves_siblings(
        self, client, user, manufacturer, williams_entity, solid_state
    ):
        source = make_ingest_source(
            name="Test", slug="test", source_type="editorial", priority=100
        )
        system = System.objects.create(
            name="WPC-95", slug="wpc-95", manufacturer=manufacturer
        )
        sibling = System.objects.create(
            name="System 11", slug="system-11", manufacturer=manufacturer
        )
        # Manufacturer is now claim-controlled on System — assert claims so
        # resolution preserves the FK when description is PATCHed.
        make_claim(system, "manufacturer", manufacturer.pk, ingest_source=source)
        make_claim(sibling, "manufacturer", manufacturer.pk, ingest_source=source)
        title = Title.objects.create(name="Medieval Madness", slug="medieval-madness")
        make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness",
            title=title,
            system=system,
            corporate_entity=williams_entity,
            technology_generation=solid_state,
            production_year=1997,
        )

        client.force_login(user)
        resp = _patch(
            client,
            f"/api/systems/{system.slug}/claims/",
            {"fields": {"description": "Updated system copy"}},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["manufacturer"] == {
            "name": manufacturer.name,
            "public_id": manufacturer.public_id,
        }
        # The page/edit-response split: no embedded game list on a save.
        assert "titles" not in data
        assert "games" not in data
        assert data["sibling_systems"] == [
            {"name": sibling.name, "public_id": sibling.public_id}
        ]


@pytest.mark.django_db
class TestPatchRewardTypeResponseShape:
    def test_patch_response_stays_slim(
        self, client, user, williams_entity, solid_state
    ):
        reward_type = RewardType.objects.create(name="Replay", slug="replay")
        title = Title.objects.create(name="Firepower", slug="firepower")
        model = make_machine_model(
            name="Firepower",
            slug="firepower",
            title=title,
            corporate_entity=williams_entity,
            technology_generation=solid_state,
            production_year=1980,
        )
        model.reward_types.add(reward_type)

        client.force_login(user)
        resp = _patch(
            client,
            f"/api/reward-types/{reward_type.slug}/claims/",
            {"fields": {"description": "Updated reward type copy"}},
        )

        assert resp.status_code == 200
        data = resp.json()
        # The page/edit-response split: no embedded game list on a save.
        assert "machines" not in data
        assert "games" not in data
        assert data["name"] == "Replay"

    def test_patch_can_attach_edit_citation_to_reward_type_claim(
        self, client, user, citation_source
    ):
        reward_type = RewardType.objects.create(name="Replay", slug="replay")

        client.force_login(user)
        resp = _patch(
            client,
            f"/api/reward-types/{reward_type.slug}/claims/",
            {
                "fields": {"description": "Updated reward type copy"},
                "citations": [
                    {"citation_source_id": citation_source.pk, "locator": "p. 2"}
                ],
            },
        )

        assert resp.status_code == 200

        created_claim = reward_type.claims.get(
            actor=user.actor,
            field_name="description",
            value="Updated reward type copy",
            is_active=True,
        )
        attached = created_claim.citation_instances.get()
        assert attached.citation_source == citation_source
        assert attached.locator == "p. 2"


UNIQUE_NAME_CASES = [
    pytest.param(
        "/api/franchises/{slug}/claims/",
        _create_franchise,
        "Indiana Jones",
        id="franchise",
    ),
    pytest.param(
        "/api/systems/{slug}/claims/",
        _create_system,
        "System 11",
        id="system",
    ),
    pytest.param(
        "/api/technology-generations/{slug}/claims/",
        _create_technology_generation,
        "Electromechanical",
        id="technology-generation",
    ),
    pytest.param(
        "/api/display-types/{slug}/claims/",
        _create_display_type,
        "LCD",
        id="display-type",
    ),
    pytest.param(
        "/api/cabinets/{slug}/claims/",
        _create_cabinet,
        "Standard",
        id="cabinet",
    ),
    pytest.param(
        "/api/game-formats/{slug}/claims/",
        _create_game_format,
        "Shuffle Alley",
        id="game-format",
    ),
    pytest.param(
        "/api/reward-types/{slug}/claims/",
        _create_reward_type,
        "Extra Ball",
        id="reward-type",
    ),
    pytest.param("/api/tags/{slug}/claims/", _create_tag, "Widebody", id="tag"),
]


@pytest.mark.django_db
class TestUniqueNameValidation:
    @pytest.mark.parametrize(
        ("path_template", "factory", "other_name"), UNIQUE_NAME_CASES
    )
    def test_duplicate_name_returns_422(
        self, client, user, path_template, factory, other_name
    ):
        entity = factory()
        extra_kwargs = {}
        if isinstance(entity, System):
            extra_kwargs["manufacturer"] = entity.manufacturer
        entity.__class__.objects.create(
            name=other_name, slug=slugify(other_name), **extra_kwargs
        )

        client.force_login(user)
        resp = _patch(
            client,
            path_template.format(slug=entity.slug),
            {"fields": {"name": other_name}},
        )

        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()
        assert ChangeSet.objects.count() == 0


DISPLAY_ORDER_CASES = [
    pytest.param(
        "/api/technology-generations/{slug}/claims/",
        _create_technology_generation,
        id="technology-generation",
    ),
    pytest.param(
        "/api/technology-subgenerations/{slug}/claims/",
        _create_technology_subgeneration,
        id="technology-subgeneration",
    ),
    pytest.param(
        "/api/display-types/{slug}/claims/",
        _create_display_type,
        id="display-type",
    ),
    pytest.param(
        "/api/display-subtypes/{slug}/claims/",
        _create_display_subtype,
        id="display-subtype",
    ),
    pytest.param("/api/cabinets/{slug}/claims/", _create_cabinet, id="cabinet"),
    pytest.param(
        "/api/game-formats/{slug}/claims/",
        _create_game_format,
        id="game-format",
    ),
    pytest.param(
        "/api/reward-types/{slug}/claims/",
        _create_reward_type,
        id="reward-type",
    ),
    pytest.param("/api/tags/{slug}/claims/", _create_tag, id="tag"),
]


@pytest.mark.django_db
class TestTaxonomyDisplayOrderEditing:
    @pytest.mark.parametrize(("path_template", "factory"), DISPLAY_ORDER_CASES)
    def test_display_order_edit_persists_and_returns_integer(
        self, client, user, path_template, factory
    ):
        entity = factory()

        client.force_login(user)
        resp = _patch(
            client,
            path_template.format(slug=entity.slug),
            {"fields": {"display_order": 7}},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["display_order"] == 7

        entity.refresh_from_db()
        assert entity.display_order == 7
        claim = entity.claims.get(
            actor=user.actor, field_name="display_order", is_active=True
        )
        assert claim.value == 7
