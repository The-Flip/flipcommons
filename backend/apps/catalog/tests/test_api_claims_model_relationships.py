"""Tests for MachineModel relationship editing via PATCH /api/models/{public_id}/claims/."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import (
    GameplayFeature,
    MachineModel,
    ModelAbbreviation,
    ModelRelationship,
    Person,
    RewardType,
    Tag,
    Theme,
    Title,
    TitleAbbreviation,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.test_factories import make_citation_source
from apps.provenance.models import ChangeSet
from apps.provenance.test_factories import make_claim

User = get_user_model()


def _only_user_changeset(user) -> ChangeSet:
    """The sole user-authored changeset (fixture seed claims are ingest)."""
    return ChangeSet.objects.get(actor=user.actor)


@pytest.fixture
def pm(db, bootstrap_source):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    make_claim(pm, "name", "Medieval Madness", ingest_source=bootstrap_source)
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
    return make_citation_source(name="Williams Flyer", source_type="web")


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

    def test_title_overlap_unchanged_save_writes_no_claims(self, client, user, pm):
        """The editor displays the deduped set, so saving it unchanged must diff
        against the *deduped* current state — not the raw materialized rows — or
        it emits a spurious ``exists=false`` removal for each Title-owned
        abbreviation."""
        title = Title.objects.create(name="Medieval Madness", slug="mm-title")
        pm.title = title
        pm.save()
        TitleAbbreviation.objects.create(title=title, value="MM")
        ModelAbbreviation.objects.create(machine_model=pm, value="MM")
        ModelAbbreviation.objects.create(machine_model=pm, value="TS4LE")

        client.force_login(user)
        # The editor showed ["TS4LE"] (MM hidden); re-saving it is a no-op.
        resp = _patch(client, pm.slug, {"abbreviations": ["TS4LE"]})
        assert resp.status_code == 422  # "No changes provided."
        assert ChangeSet.objects.filter(actor=user.actor).count() == 0


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

        # The pm fixture asserts a seed (ingest) name claim, so filter to the
        # user's changeset rather than assuming it's the only row.
        assert ChangeSet.objects.filter(actor=user.actor).count() == 1
        cs = _only_user_changeset(user)
        assert cs.note == "Full edit"
        field_names = set(cs.claims.values_list("field_name", flat=True))
        assert "year" in field_names
        assert "theme" in field_names
        assert "gameplay_feature" in field_names
        assert "credit" in field_names
        assert "abbreviation" in field_names

    def test_one_shared_citation_reaches_each_created_claim(
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
                "citations": [
                    {"citation_source_id": citation_source.pk, "locator": "p. 3"}
                ],
            },
        )
        assert resp.status_code == 200, resp.json()

        # Restrict to the editing user's changeset (the pm fixture's seed name
        # claim is ingest).
        changeset = ChangeSet.objects.filter(actor=user.actor).get()
        claims = list(changeset.claims.order_by("pk"))
        assert claims
        instances = set()
        for claim in claims:
            claim_citations = list(claim.citation_instances.all())
            assert len(claim_citations) == 1
            assert claim_citations[0].citation_source_id == citation_source.pk
            assert claim_citations[0].locator == "p. 3"
            instances.add(claim_citations[0].pk)
        # The whole save shares ONE instance — evidence is not cloned per claim.
        assert len(instances) == 1

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

    def test_retired_lineage_fk_rejected(self, client, user, pm):
        # The legacy lineage FKs are gone from the model, so the editable-field
        # surface (model-driven) rejects them like any unknown field — a guard
        # against accidental resurrection.
        client.force_login(user)
        resp = _patch(client, pm.slug, {"fields": {"bootleg_of": pm.slug}})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Relationship edges (model_relationship — the target-XOR namespace)
# ---------------------------------------------------------------------------


@pytest.fixture
def rock(db, bootstrap_source):
    target = make_machine_model(name="Rock", slug="rock", year=1985)
    make_claim(target, "name", "Rock", ingest_source=bootstrap_source)
    return target


def _relationships(resp) -> list[dict[str, Any]]:
    # Any: raw JSON payload rows — the assertions themselves pin the shapes.
    body: dict[str, list[dict[str, Any]]] = resp.json()
    return body["relationships"]


@pytest.mark.django_db
class TestRelationshipEdges:
    def test_add_machine_target_edge(self, client, user, pm, rock):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "copy",
                        "license_status": "unlicensed",
                        "target_slug": "rock",
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.json()
        (edge,) = _relationships(resp)
        assert edge["relationship_type"] == "copy"
        assert edge["license_status"] == "unlicensed"
        assert edge["target_machine"]["public_id"] == "rock"
        assert edge["target_label"] == ""

    def test_add_label_target_edge(self, client, user, pm):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "conversion_kit",
                        "target_label": "several Gottlieb EM models",
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.json()
        (edge,) = _relationships(resp)
        assert edge["relationship_type"] == "conversion_kit"
        assert edge["license_status"] == "unknown"  # schema default
        assert edge["target_machine"] is None
        assert edge["target_label"] == "several Gottlieb EM models"

    def test_retheme_label_target_rejected(self, client, user, pm):
        """retheme requires a machine target, so a label rung is a row error —
        the planner mirror of the derived DB CHECK."""
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {"relationship_type": "retheme", "target_label": "an unknown donor"}
                ]
            },
        )
        assert resp.status_code == 422, resp.json()

    def test_retheme_machine_target_accepted(self, client, user, pm, rock):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {"relationship_type": "retheme", "target_slug": "rock"}
                ]
            },
        )
        assert resp.status_code == 200, resp.json()
        (edge,) = _relationships(resp)
        assert edge["relationship_type"] == "retheme"
        assert edge["target_machine"]["public_id"] == "rock"
        assert edge["target_label"] == ""

    def test_payload_change_supersedes_in_place(self, client, user, pm, rock):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {"relationship_type": "conversion", "target_slug": "rock"}
                ]
            },
        )
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "conversion_kit",
                        "license_status": "licensed",
                        "target_slug": "rock",
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.json()
        (edge,) = _relationships(resp)
        assert edge["relationship_type"] == "conversion_kit"
        assert edge["license_status"] == "licensed"

    def test_remove_edge(self, client, user, pm, rock):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {"relationships": [{"relationship_type": "copy", "target_slug": "rock"}]},
        )
        resp = _patch(client, pm.slug, {"relationships": []})
        assert resp.status_code == 200, resp.json()
        assert _relationships(resp) == []

    def test_label_reword_supersedes_in_place(self, client, user, pm):
        """A reworded label is a payload correction on the model's single
        label slot: same claim_key, same materialized row pk — the citation
        history stays attached to the edge instead of stranding on a
        tombstoned one."""
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "conversion",
                        "target_label": "an unknown Gottlieb game",
                    }
                ]
            },
        )
        original = ModelRelationship.objects.get(machine_model=pm)

        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "conversion",
                        "target_label": "an unidentified 1960s Gottlieb",
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.json()
        (edge,) = _relationships(resp)
        assert edge["target_label"] == "an unidentified 1960s Gottlieb"

        row = ModelRelationship.objects.get(machine_model=pm)
        assert row.pk == original.pk

        # One superseding assert, no tombstone: the reword is a correction,
        # not a remove+add.
        latest = ChangeSet.objects.filter(actor=user.actor).order_by("-pk").first()
        assert latest is not None
        (claim,) = list(latest.claims.all())
        assert claim.field_name == "model_relationship"
        assert claim.value["exists"] is True

    def test_second_label_row_rejected(self, client, user, pm):
        """A model holds one label slot — two describe-it rows collide on the
        same claim identity."""
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "copy",
                        "target_label": "an unknown design",
                    },
                    {
                        "relationship_type": "conversion",
                        "target_label": "whatever cabinets were available",
                    },
                ]
            },
        )
        assert resp.status_code == 422
        errors = resp.json()["detail"]["field_errors"]
        assert any("one text-description" in msg for msg in errors.values())

    def test_removed_label_edge_history_shows_current_wording(self, client, user, pm):
        """A removed label edge stays legible: the tombstone's own value is
        identity-only (no wording), so the history's old→new derivation
        surfaces the *chronologically prior* claim's wording under the same
        claim_key. Single-actor (as here), that is the current wording even
        after a reword-then-remove-by-old-wording; for the priority-inverted
        case where chronology and resolution diverge, see
        ``test_removed_label_history_is_chronological_not_resolved``."""
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "conversion",
                        "target_label": "an unknown Gottlieb game",
                    }
                ]
            },
        )
        _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "conversion",
                        "target_label": "an unidentified 1960s Gottlieb",
                    }
                ]
            },
        )
        resp = _patch(client, pm.slug, {"relationships": []})
        assert resp.status_code == 200, resp.json()

        history = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert history.status_code == 200
        newest = history.json()[0]
        (change,) = newest["changes"]
        assert change["field_name"] == "model_relationship"
        assert change["new_value"]["raw"]["exists"] is False
        assert "target_label" not in change["new_value"]["raw"]
        assert (
            change["old_value"]["raw"]["target_label"]
            == "an unidentified 1960s Gottlieb"
        )

    def test_removed_label_history_is_chronological_not_resolved(
        self, client, user, pm
    ):
        """``old_value`` is the *chronologically* prior claim under the key,
        not the pre-change resolved winner — the same edit-log semantics every
        field has, now load-bearing for label removals since the tombstone
        itself carries no wording. The two sources are priority-inverted so
        the chronological prior (the low-priority, newer wording) and the
        resolution winner (the high-priority, older wording) genuinely differ:
        a resolution-based history would show the other value."""
        from apps.catalog.resolve import resolve_relationship
        from apps.provenance.claims import build_relationship_claim
        from apps.provenance.test_factories import make_ingest_source

        high = make_ingest_source(
            name="Editorial", source_type="editorial", priority=100
        )
        low = make_ingest_source(name="IPDB", source_type="database", priority=10)

        def mint_label(source, wording):
            claim_key, value = build_relationship_claim(
                "model_relationship",
                {
                    "target_machine": None,
                    "target_label": wording,
                    "relationship_type": "conversion",
                    "license_status": "unknown",
                },
            )
            make_claim(
                pm,
                "model_relationship",
                value,
                ingest_source=source,
                claim_key=claim_key,
            )

        mint_label(high, "the winning wording")
        mint_label(low, "the newer but losing wording")
        resolve_relationship(MachineModel, "model_relationship", subject_ids={pm.pk})

        # Pre-removal, resolution materializes the high-priority wording —
        # the chronological prior is a resolution *loser*.
        edge = ModelRelationship.objects.get(machine_model=pm)
        assert edge.target_label == "the winning wording"

        client.force_login(user)
        resp = _patch(client, pm.slug, {"relationships": []})
        assert resp.status_code == 200, resp.json()

        history = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        newest = history.json()[0]
        (change,) = newest["changes"]
        assert change["new_value"]["raw"]["exists"] is False
        # Chronology over resolution: the low-priority claim is newer, so it —
        # not the materialized winner — is the removal's old value.
        assert (
            change["old_value"]["raw"]["target_label"] == "the newer but losing wording"
        )

    def test_edit_target_is_tombstone_plus_assert(self, client, user, pm, rock):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {"relationship_type": "copy", "target_label": "an unknown game"}
                ]
            },
        )
        resp = _patch(
            client,
            pm.slug,
            {"relationships": [{"relationship_type": "copy", "target_slug": "rock"}]},
        )
        assert resp.status_code == 200, resp.json()
        (edge,) = _relationships(resp)
        assert edge["target_machine"]["public_id"] == "rock"
        assert edge["target_label"] == ""

    def test_unchanged_edge_emits_no_claim(self, client, user, pm, rock):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {"relationships": [{"relationship_type": "copy", "target_slug": "rock"}]},
        )
        # Re-sending the identical desired list alongside a scalar change must
        # not re-assert the edge (no duplicate claims in the new changeset).
        resp = _patch(
            client,
            pm.slug,
            {
                "fields": {"year": 1998},
                "relationships": [{"relationship_type": "copy", "target_slug": "rock"}],
            },
        )
        assert resp.status_code == 200, resp.json()
        latest = ChangeSet.objects.filter(actor=user.actor).order_by("-pk").first()
        assert latest is not None
        assert [c.field_name for c in latest.claims.all()] == ["year"]

    def test_one_citation_rides_every_edge_claim(
        self, client, user, pm, rock, citation_source
    ):
        # Dean's flow: a source says "copy of A and B" — add both edges, cite
        # once, and each edge claim carries the citation.
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "copy",
                        "license_status": "unlicensed",
                        "target_slug": "rock",
                    },
                    {
                        "relationship_type": "copy",
                        "license_status": "unlicensed",
                        "target_label": "an unidentified Bally game",
                    },
                ],
                "citations": [
                    {"citation_source_id": citation_source.pk, "locator": "p. 7"}
                ],
            },
        )
        assert resp.status_code == 200, resp.json()
        changeset = ChangeSet.objects.filter(actor=user.actor).get()
        claims = list(changeset.claims.all())
        assert len(claims) == 2
        instances = set()
        for claim in claims:
            (ci,) = list(claim.citation_instances.all())
            assert ci.citation_source_id == citation_source.pk
            instances.add(ci.pk)
        assert len(instances) == 1  # one shared instance, not cloned evidence

    def test_null_leaves_edges_unchanged(self, client, user, pm, rock):
        client.force_login(user)
        _patch(
            client,
            pm.slug,
            {"relationships": [{"relationship_type": "copy", "target_slug": "rock"}]},
        )
        resp = _patch(client, pm.slug, {"fields": {"year": 1998}})
        assert resp.status_code == 200
        assert len(_relationships(resp)) == 1

    # --- row validation ----------------------------------------------------

    def test_both_targets_rejected(self, client, user, pm, rock):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {
                        "relationship_type": "copy",
                        "target_slug": "rock",
                        "target_label": "redundant",
                    }
                ]
            },
        )
        assert resp.status_code == 422
        assert "relationships.rock" in resp.json()["detail"]["field_errors"]

    def test_no_target_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(
            client, pm.slug, {"relationships": [{"relationship_type": "copy"}]}
        )
        assert resp.status_code == 422

    def test_unknown_target_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {"relationship_type": "copy", "target_slug": "no-such-model"}
                ]
            },
        )
        assert resp.status_code == 422
        assert "relationships.no-such-model" in resp.json()["detail"]["field_errors"]

    def test_self_target_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {"relationships": [{"relationship_type": "copy", "target_slug": pm.slug}]},
        )
        assert resp.status_code == 422

    def test_duplicate_target_rejected(self, client, user, pm, rock):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "relationships": [
                    {"relationship_type": "copy", "target_slug": "rock"},
                    {"relationship_type": "conversion", "target_slug": "rock"},
                ]
            },
        )
        assert resp.status_code == 422

    def test_out_of_vocab_type_rejected_by_schema(self, client, user, pm, rock):
        # The Literal union rejects at the pydantic layer, before the planner.
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {"relationships": [{"relationship_type": "remake", "target_slug": "rock"}]},
        )
        assert resp.status_code == 422


def test_relationship_literals_match_choices() -> None:
    """The wire Literals are locked to the model TextChoices — a new enum value
    must show up in both or this fails."""
    from typing import get_args

    from apps.catalog.api.schemas import (
        LicenseStatusLiteral,
        RelationshipTypeLiteral,
    )
    from apps.catalog.models import LicenseStatus, RelationshipType

    assert set(get_args(RelationshipTypeLiteral)) == set(RelationshipType.values)
    assert set(get_args(LicenseStatusLiteral)) == set(LicenseStatus.values)


def test_cross_title_relation_covers_every_edge_type() -> None:
    """CrossTitleRelation is a hand-written flat Literal (kept flat so it inlines
    in the OpenAPI schema), so this locks it to {remake_of} ∪ the edge types — a
    new relationship_type can't silently omit its cross-title arm and fail
    Literal validation at serialize time (a re-theme's donor nearly always sits
    under its own Title, so this is a re-theme's normal read path)."""
    from typing import get_args

    from apps.catalog.api.schemas import RelationshipTypeLiteral
    from apps.catalog.api.titles import CrossTitleRelation

    assert set(get_args(CrossTitleRelation)) == {
        "remake_of",
        *get_args(RelationshipTypeLiteral),
    }
