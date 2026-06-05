"""Tests for MachineModel relationship editing via PATCH /api/models/{public_id}/claims/."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import (
    GameplayFeature,
    Person,
    RewardType,
    Tag,
    Theme,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.models import CitationSource
from apps.provenance.models import ChangeSet, Claim
from apps.provenance.test_factories import user_changeset

User = get_user_model()


def _only_changeset() -> ChangeSet:
    cs = ChangeSet.objects.first()
    assert cs is not None
    return cs


@pytest.fixture
def pm(db, _bootstrap_source):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    Claim.objects.assert_claim(pm, "name", "Medieval Madness", source=_bootstrap_source)
    return pm


@pytest.fixture
def themes(db):
    return [
        Theme.objects.create(name="Medieval", slug="medieval"),
        Theme.objects.create(name="Fantasy", slug="fantasy"),
        Theme.objects.create(name="Horror", slug="horror"),
    ]


@pytest.fixture
def tags(db):
    return [
        Tag.objects.create(name="Classic", slug="classic"),
        Tag.objects.create(name="Widebody", slug="widebody"),
    ]


@pytest.fixture
def reward_types(db):
    return [
        RewardType.objects.create(name="Multiball", slug="multiball"),
        RewardType.objects.create(name="Wizard Mode", slug="wizard-mode"),
    ]


@pytest.fixture
def gameplay_features(db):
    return [
        GameplayFeature.objects.create(name="Ramps", slug="ramps"),
        GameplayFeature.objects.create(name="Pop Bumpers", slug="pop-bumpers"),
        GameplayFeature.objects.create(name="Loops", slug="loops"),
    ]


@pytest.fixture
def people(db):
    return [
        Person.objects.create(name="Pat Lawlor", slug="pat-lawlor"),
        Person.objects.create(name="John Youssi", slug="john-youssi"),
        Person.objects.create(name="Greg Freres", slug="greg-freres"),
    ]


@pytest.fixture
def citation_source(db):
    return CitationSource.objects.create(name="Williams Flyer", source_type="web")


def _patch(client, slug, body):
    return client.patch(
        f"/api/models/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Simple M2M: themes, tags, reward_types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestM2MThemes:
    def test_add_themes(self, client, user, pm, themes):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"themes": ["medieval", "fantasy"]})
        assert resp.status_code == 200
        slugs = sorted(t["public_id"] for t in resp.json()["themes"])
        assert slugs == ["fantasy", "medieval"]

    def test_remove_themes(self, client, user, pm, themes):
        client.force_login(user)
        _patch(client, pm.slug, {"themes": ["medieval"]})
        resp = _patch(client, pm.slug, {"themes": []})
        assert resp.status_code == 200
        assert resp.json()["themes"] == []

    def test_replace_themes(self, client, user, pm, themes):
        client.force_login(user)
        _patch(client, pm.slug, {"themes": ["medieval"]})
        resp = _patch(client, pm.slug, {"themes": ["fantasy", "horror"]})
        assert resp.status_code == 200
        slugs = sorted(t["public_id"] for t in resp.json()["themes"])
        assert slugs == ["fantasy", "horror"]

    def test_null_leaves_unchanged(self, client, user, pm, themes):
        client.force_login(user)
        _patch(client, pm.slug, {"themes": ["medieval"]})
        # PATCH with only a scalar field, themes=null (omitted)
        resp = _patch(client, pm.slug, {"fields": {"year": 1998}})
        assert resp.status_code == 200
        assert len(resp.json()["themes"]) == 1
        assert resp.json()["themes"][0]["public_id"] == "medieval"


@pytest.mark.django_db
class TestM2MTags:
    def test_add_and_remove_tags(self, client, user, pm, tags):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"tags": ["classic", "widebody"]})
        assert resp.status_code == 200

        pm.refresh_from_db()
        assert set(pm.tags.values_list("slug", flat=True)) == {
            "classic",
            "widebody",
        }

        resp = _patch(client, pm.slug, {"tags": ["classic"]})
        assert resp.status_code == 200
        pm.refresh_from_db()
        assert set(pm.tags.values_list("slug", flat=True)) == {"classic"}


@pytest.mark.django_db
class TestM2MRewardTypes:
    def test_add_and_remove_reward_types(self, client, user, pm, reward_types):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"reward_types": ["multiball", "wizard-mode"]})
        assert resp.status_code == 200
        slugs = sorted(rt["public_id"] for rt in resp.json()["reward_types"])
        assert slugs == ["multiball", "wizard-mode"]

        resp = _patch(client, pm.slug, {"reward_types": []})
        assert resp.status_code == 200
        assert resp.json()["reward_types"] == []


# ---------------------------------------------------------------------------
# Gameplay features (with count)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGameplayFeatures:
    def test_add_with_count(self, client, user, pm, gameplay_features):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {"gameplay_features": [{"slug": "ramps", "count": 3}]},
        )
        assert resp.status_code == 200
        features = resp.json()["gameplay_features"]
        assert len(features) == 1
        assert features[0]["public_id"] == "ramps"
        assert features[0]["count"] == 3

    def test_add_without_count(self, client, user, pm, gameplay_features):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {"gameplay_features": [{"slug": "loops"}]},
        )
        assert resp.status_code == 200
        features = resp.json()["gameplay_features"]
        assert len(features) == 1
        assert features[0]["public_id"] == "loops"
        assert features[0]["count"] is None

    def test_update_count(self, client, user, pm, gameplay_features):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {"gameplay_features": [{"slug": "pop-bumpers", "count": 2}]},
        )
        resp = _patch(
            client,
            pm.slug,
            {"gameplay_features": [{"slug": "pop-bumpers", "count": 3}]},
        )
        assert resp.status_code == 200
        features = resp.json()["gameplay_features"]
        assert features[0]["count"] == 3

    def test_remove_feature(self, client, user, pm, gameplay_features):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {
                "gameplay_features": [
                    {"slug": "ramps", "count": 2},
                    {"slug": "loops"},
                ]
            },
        )
        resp = _patch(
            client,
            pm.slug,
            {"gameplay_features": [{"slug": "ramps", "count": 2}]},
        )
        assert resp.status_code == 200
        slugs = [f["public_id"] for f in resp.json()["gameplay_features"]]
        assert slugs == ["ramps"]


# ---------------------------------------------------------------------------
# Abbreviations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAbbreviations:
    def test_add_abbreviations(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"abbreviations": ["MM", "MMR"]})
        assert resp.status_code == 200
        assert sorted(resp.json()["abbreviations"]) == ["MM", "MMR"]

    def test_remove_abbreviations(self, client, user, pm):
        client.force_login(user)
        _patch(client, pm.slug, {"abbreviations": ["MM", "MMR"]})
        resp = _patch(client, pm.slug, {"abbreviations": ["MM"]})
        assert resp.status_code == 200
        assert resp.json()["abbreviations"] == ["MM"]

    def test_clear_abbreviations(self, client, user, pm):
        client.force_login(user)
        _patch(client, pm.slug, {"abbreviations": ["MM"]})
        resp = _patch(client, pm.slug, {"abbreviations": []})
        assert resp.status_code == 200
        assert resp.json()["abbreviations"] == []


# ---------------------------------------------------------------------------
# Combined edits
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCombinedEdits:
    def test_scalar_and_relationships_share_one_changeset(
        self, client, user, pm, themes, gameplay_features, people, credit_roles
    ):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "fields": {"year": 1998},
                "themes": ["medieval"],
                "gameplay_features": [{"slug": "ramps", "count": 2}],
                "credits": [{"person_slug": "pat-lawlor", "role": "design"}],
                "abbreviations": ["MM"],
                "note": "Full edit",
            },
        )
        assert resp.status_code == 200

        assert ChangeSet.objects.count() == 1
        cs = _only_changeset()
        assert cs.note == "Full edit"
        field_names = set(cs.claims.values_list("field_name", flat=True))
        assert "year" in field_names
        assert "theme" in field_names
        assert "gameplay_feature" in field_names
        assert "credit" in field_names
        assert "abbreviation" in field_names

    def test_citation_is_copied_to_each_created_claim(
        self,
        client,
        user,
        pm,
        themes,
        gameplay_features,
        people,
        credit_roles,
        citation_source,
    ):
        seed_claim = Claim.objects.assert_claim(
            pm,
            "description",
            "Template citation seed",
            user=user,
            changeset=user_changeset(user, note="seed"),
        )
        template_instance = citation_source.instances.create(
            claim=seed_claim,
            locator="p. 3",
        )

        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "fields": {"year": 1998},
                "themes": ["medieval"],
                "gameplay_features": [{"slug": "ramps", "count": 2}],
                "credits": [{"person_slug": "pat-lawlor", "role": "design"}],
                "abbreviations": ["MM"],
                "citation": {"citation_instance_id": template_instance.pk},
            },
        )
        assert resp.status_code == 200, resp.json()

        assert seed_claim.changeset_id is not None
        changeset = ChangeSet.objects.exclude(pk=seed_claim.changeset_id).get()
        claims = list(changeset.claims.order_by("pk"))
        assert claims
        for claim in claims:
            claim_citations = list(claim.citation_instances.all())
            assert len(claim_citations) == 1
            assert claim_citations[0].citation_source_id == citation_source.pk
            assert claim_citations[0].locator == "p. 3"

    def test_no_changes_returns_422(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredits:
    def test_add_credits(self, client, user, pm, people, credit_roles):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "credits": [
                    {"person_slug": "pat-lawlor", "role": "design"},
                    {"person_slug": "greg-freres", "role": "art"},
                ]
            },
        )
        assert resp.status_code == 200
        credits = resp.json()["credits"]
        assert len(credits) == 2
        persons = sorted(c["person"]["public_id"] for c in credits)
        assert persons == ["greg-freres", "pat-lawlor"]

    def test_remove_credit(self, client, user, pm, people, credit_roles):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {
                "credits": [
                    {"person_slug": "pat-lawlor", "role": "design"},
                    {"person_slug": "greg-freres", "role": "art"},
                ]
            },
        )
        resp = _patch(
            client,
            pm.slug,
            {"credits": [{"person_slug": "pat-lawlor", "role": "design"}]},
        )
        assert resp.status_code == 200
        assert len(resp.json()["credits"]) == 1

    def test_replace_credits(self, client, user, pm, people, credit_roles):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {"credits": [{"person_slug": "pat-lawlor", "role": "design"}]},
        )
        resp = _patch(
            client,
            pm.slug,
            {"credits": [{"person_slug": "john-youssi", "role": "software"}]},
        )
        assert resp.status_code == 200
        credits = resp.json()["credits"]
        assert len(credits) == 1
        assert credits[0]["person"]["public_id"] == "john-youssi"
        assert credits[0]["role"] == "software"

    def test_clear_credits(self, client, user, pm, people, credit_roles):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {"credits": [{"person_slug": "pat-lawlor", "role": "design"}]},
        )
        resp = _patch(client, pm.slug, {"credits": []})
        assert resp.status_code == 200
        assert resp.json()["credits"] == []

    def test_null_leaves_unchanged(self, client, user, pm, people, credit_roles):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {"credits": [{"person_slug": "pat-lawlor", "role": "design"}]},
        )
        # PATCH with only a scalar field, credits=null (omitted)
        resp = _patch(client, pm.slug, {"fields": {"year": 1998}})
        assert resp.status_code == 200
        assert len(resp.json()["credits"]) == 1

    def test_same_person_different_roles_allowed(
        self, client, user, pm, people, credit_roles
    ):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "credits": [
                    {"person_slug": "pat-lawlor", "role": "design"},
                    {"person_slug": "pat-lawlor", "role": "software"},
                ]
            },
        )
        assert resp.status_code == 200
        assert len(resp.json()["credits"]) == 2


# ---------------------------------------------------------------------------
# Edit options
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEditOptions:
    def test_includes_credit_roles(self, client, credit_roles):
        resp = client.get("/api/models/edit-options/")
        assert resp.status_code == 200
        data = resp.json()
        assert "credit_roles" in data
        # Verify shape: each item has slug + label
        assert all("slug" in r and "label" in r for r in data["credit_roles"])
        role_slugs = {r["slug"] for r in data["credit_roles"]}
        assert "design" in role_slugs


@pytest.mark.django_db
class TestHierarchyFKValidation:
    def test_self_referential_variant_of_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"fields": {"variant_of": pm.slug}})
        assert resp.status_code == 422

    def test_self_referential_converted_from_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"fields": {"converted_from": pm.slug}})
        assert resp.status_code == 422

    def test_self_referential_remake_of_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"fields": {"remake_of": pm.slug}})
        assert resp.status_code == 422

    def test_valid_hierarchy_fk_succeeds(self, client, user, pm):
        parent = make_machine_model(name="Star Trek", slug="star-trek", year=1991)
        client.force_login(user)
        resp = _patch(client, pm.slug, {"fields": {"variant_of": parent.slug}})
        assert resp.status_code == 200
        assert resp.json()["variant_of"]["public_id"] == "star-trek"
