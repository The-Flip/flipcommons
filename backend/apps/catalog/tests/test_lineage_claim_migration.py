"""Guards for the lineage-FK-claims → edge-claims migration (catalog 0021).

The migration rewrites ``converted_from`` / ``bootleg_of`` /
``licensed_build_of`` claims in place into ``model_relationship`` edge claims,
materializes the missing edge rows and nulls the legacy columns. Risks covered:

1. The value mapping — conversion vs conversion_kit (tag-aware), copy with the
   licensed/unlicensed axis — and the canonical claim_key, locked against the
   live builder so the inlined key format can't drift.
2. In-place rewrite: the claim row keeps its pk, so citations and attribution
   survive by construction.
3. The collision rule: where the campaign already asserts the same edge from
   the same actor, the legacy claim deactivates instead of double-activating.
4. Inactive history transforms without materializing; cleared/dangling/self
   values deactivate rather than producing unmaterializable active claims.

Legacy claims are created directly (not via ``make_claim``) because the live
write path validates against the current schema; the legacy scalar shape is
exactly what this migration exists to convert.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType

from apps.catalog.models import (
    MachineModel,
    MachineModelTag,
    ModelRelationship,
    Tag,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import Claim
from apps.provenance.test_factories import make_ingest_source, source_changeset

_migration = importlib.import_module(
    "apps.catalog.migrations.0021_lineage_fk_claims_to_edges"
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def src(db):
    return make_ingest_source(name="Legacy", slug="legacy", source_type="database")


@pytest.fixture
def subject(db):
    return make_machine_model(name="Subject", slug="subject")


@pytest.fixture
def target(db):
    return make_machine_model(name="Target", slug="target")


def _legacy_claim(src, subject, field_name, value, *, is_active=True):
    claim = Claim.objects.create(
        content_type=ContentType.objects.get_for_model(type(subject)),
        object_id=subject.pk,
        actor=src.actor,
        changeset=source_changeset(src),
        field_name=field_name,
        claim_key=field_name,
        value=value,
    )
    if not is_active:
        # Sidestep the active-claim unique index / retraction bookkeeping;
        # the migration only reads pk/value/is_active.
        Claim.objects.filter(pk=claim.pk).update(is_active=False)
        claim.refresh_from_db()
    return claim


def _run():
    _migration.transform_lineage_claims(django_apps, None)


def test_claim_key_format_locked_to_live_builder():
    """The inlined key format must match make_claim_key's canonical output."""
    live_key, _value = build_relationship_claim(
        "model_relationship",
        {
            "target_machine": 42,
            "target_label": "",
            "relationship_type": "conversion",
            "license_status": "unknown",
        },
    )
    assert _migration._edge_claim_key(42) == live_key


def test_converted_from_transforms_in_place(src, subject, target):
    subject.converted_from = target
    subject.save(update_fields=["converted_from"])
    claim = _legacy_claim(src, subject, "converted_from", target.pk)

    _run()

    claim.refresh_from_db()  # same row: pk (and thus citations) preserved
    assert claim.field_name == "model_relationship"
    assert claim.claim_key == _migration._edge_claim_key(target.pk)
    assert claim.value == {
        "target_machine": target.pk,
        "target_label": "",
        "relationship_type": "conversion",
        "license_status": "unknown",
        "exists": True,
    }
    assert claim.is_active

    edge = ModelRelationship.objects.get(machine_model=subject)
    assert edge.target_machine == target
    assert edge.relationship_type == "conversion"
    assert edge.license_status == "unknown"

    subject.refresh_from_db()
    assert subject.converted_from is None


def test_kit_tagged_subject_becomes_conversion_kit(src, subject, target):
    kit = Tag.objects.create(name="Conversion Kit", slug="conversion-kit")
    MachineModelTag.objects.create(machinemodel=subject, tag=kit)
    claim = _legacy_claim(src, subject, "converted_from", target.pk)

    _run()

    claim.refresh_from_db()
    assert claim.value["relationship_type"] == "conversion_kit"
    edge = ModelRelationship.objects.get(machine_model=subject)
    assert edge.relationship_type == "conversion_kit"


@pytest.mark.parametrize(
    ("field_name", "license_status"),
    [("bootleg_of", "unlicensed"), ("licensed_build_of", "licensed")],
)
def test_copy_fields_map_license_axis(src, subject, target, field_name, license_status):
    claim = _legacy_claim(src, subject, field_name, target.pk)

    _run()

    claim.refresh_from_db()
    assert claim.value["relationship_type"] == "copy"
    assert claim.value["license_status"] == license_status
    edge = ModelRelationship.objects.get(machine_model=subject)
    assert edge.license_status == license_status


def test_collision_with_campaign_claim_deactivates_legacy(src, subject, target):
    # The campaign (same actor) already asserts this edge with sourced values.
    claim_key, value = build_relationship_claim(
        "model_relationship",
        {
            "target_machine": target.pk,
            "target_label": "",
            "relationship_type": "copy",
            "license_status": "unknown",
        },
    )
    campaign = _legacy_claim(src, subject, "model_relationship", value)
    Claim.objects.filter(pk=campaign.pk).update(claim_key=claim_key)
    ModelRelationship.objects.create(
        machine_model=subject,
        target_machine=target,
        relationship_type="copy",
        license_status="unknown",
    )
    legacy = _legacy_claim(src, subject, "bootleg_of", target.pk)

    _run()

    legacy.refresh_from_db()
    assert legacy.field_name == "model_relationship"
    assert not legacy.is_active  # the campaign's per-row-sourced claim wins
    campaign.refresh_from_db()
    assert campaign.is_active
    edge = ModelRelationship.objects.get(machine_model=subject)
    assert edge.license_status == "unknown"  # not overwritten to unlicensed


def test_inactive_history_transforms_without_materializing(src, subject, target):
    claim = _legacy_claim(src, subject, "converted_from", target.pk, is_active=False)

    _run()

    claim.refresh_from_db()
    assert claim.field_name == "model_relationship"
    assert not claim.is_active
    assert not ModelRelationship.objects.filter(machine_model=subject).exists()


def test_cleared_value_deactivates_untransformed(src, subject):
    claim = _legacy_claim(src, subject, "converted_from", "")

    _run()

    claim.refresh_from_db()
    assert claim.field_name == "converted_from"  # nothing to transform into
    assert not claim.is_active


def test_dangling_target_transforms_inactive(src, subject, target):
    missing_pk = target.pk
    claim = _legacy_claim(src, subject, "converted_from", missing_pk)
    Claim.objects.filter(object_id=missing_pk).delete()
    MachineModel.objects.filter(pk=missing_pk).delete()

    _run()

    claim.refresh_from_db()
    assert claim.field_name == "model_relationship"
    assert not claim.is_active
    assert not ModelRelationship.objects.filter(machine_model=subject).exists()


def test_idempotent_rerun(src, subject, target):
    _legacy_claim(src, subject, "converted_from", target.pk)

    _run()
    _run()  # re-run: transformed claims are no longer legacy-named — no-op

    assert ModelRelationship.objects.filter(machine_model=subject).count() == 1
    assert (
        Claim.objects.filter(
            object_id=subject.pk, field_name="model_relationship", is_active=True
        ).count()
        == 1
    )
