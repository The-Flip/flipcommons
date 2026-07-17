"""Tests for model-relationship claim resolution (the target-XOR namespace).

The ``model_relationship`` namespace exercises the spec shapes no other
namespace does: a nullable FK identity member (machine XOR label), a required
literal member with ""-as-absent, and a compound string payload
(``relationship_type`` + ``license_status``). These tests cover the shape
end-to-end: claims in, materialized ``ModelRelationship`` rows out.
"""

import pytest

from apps.catalog.models import (
    MachineModel,
    ModelRelationship,
)
from apps.catalog.resolve import resolve_relationship
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.test_factories import make_claim, make_ingest_source


@pytest.fixture
def source(db):
    return make_ingest_source(
        name="IPDB", slug="ipdb", source_type="database", priority=10
    )


@pytest.fixture
def high_source(db):
    return make_ingest_source(
        name="Editorial", slug="editorial", source_type="editorial", priority=100
    )


@pytest.fixture
def subject(db):
    return make_machine_model(name="Punky Willy", slug="punky-willy")


@pytest.fixture
def target(db):
    return make_machine_model(name="Rock", slug="rock")


@pytest.fixture
def target2(db):
    return make_machine_model(name="Rock Encore", slug="rock-encore")


def _identity(machine_pk=None, label=""):
    return {
        "target_machine": machine_pk,
        "target_label": label,
    }


def _assert_edge_claim(
    subject,
    source,
    *,
    machine_pk=None,
    label="",
    relationship_type="copy",
    license_status="unknown",
    exists=True,
):
    """Mint one model_relationship claim through the normal build path."""
    identity = _identity(machine_pk, label)
    payload = (
        {"relationship_type": relationship_type, "license_status": license_status}
        if exists
        else {}
    )
    claim_key, value = build_relationship_claim(
        "model_relationship", {**identity, **payload}, exists=exists
    )
    make_claim(
        subject,
        "model_relationship",
        value,
        ingest_source=source,
        claim_key=claim_key,
    )


def _resolve(subject):
    resolve_relationship(MachineModel, "model_relationship", subject_ids={subject.pk})


class TestResolveModelRelationships:
    def test_machine_target_materializes(self, subject, target, source):
        _assert_edge_claim(
            subject,
            source,
            machine_pk=target.pk,
            relationship_type="copy",
            license_status="unlicensed",
        )
        _resolve(subject)

        edge = ModelRelationship.objects.get(machine_model=subject)
        assert edge.target_machine == target
        assert edge.target_label == ""
        assert edge.relationship_type == "copy"
        assert edge.license_status == "unlicensed"

    def test_label_target_materializes(self, subject, source):
        """The label rung: a null target_machine identity part passes through
        instead of dropping the claim."""
        _assert_edge_claim(
            subject,
            source,
            label="several Gottlieb EM models",
            relationship_type="conversion_kit",
        )
        _resolve(subject)

        edge = ModelRelationship.objects.get(machine_model=subject)
        assert edge.target_machine is None
        assert edge.target_label == "several Gottlieb EM models"
        assert edge.relationship_type == "conversion_kit"
        assert edge.license_status == "unknown"

    def test_multiple_edges_per_subject(self, subject, target, target2, source):
        """punky-willy: one copy edge per copied machine."""
        _assert_edge_claim(subject, source, machine_pk=target.pk)
        _assert_edge_claim(subject, source, machine_pk=target2.pk)
        _resolve(subject)

        assert ModelRelationship.objects.filter(machine_model=subject).count() == 2

    def test_idempotent(self, subject, target, source):
        _assert_edge_claim(subject, source, machine_pk=target.pk)
        _resolve(subject)
        _resolve(subject)

        assert ModelRelationship.objects.filter(machine_model=subject).count() == 1

    def test_payload_update_supersedes_in_place(
        self, subject, target, source, high_source
    ):
        """Same edge identity, higher-priority payload correction: the row's
        type/status change without a second edge appearing."""
        _assert_edge_claim(
            subject,
            source,
            machine_pk=target.pk,
            relationship_type="conversion",
            license_status="unknown",
        )
        _resolve(subject)
        _assert_edge_claim(
            subject,
            high_source,
            machine_pk=target.pk,
            relationship_type="conversion_kit",
            license_status="licensed",
        )
        _resolve(subject)

        edge = ModelRelationship.objects.get(machine_model=subject)
        assert edge.relationship_type == "conversion_kit"
        assert edge.license_status == "licensed"

    def test_retraction_deletes_edge(self, subject, target, source, high_source):
        _assert_edge_claim(subject, source, machine_pk=target.pk)
        _resolve(subject)
        assert ModelRelationship.objects.filter(machine_model=subject).exists()

        _assert_edge_claim(subject, high_source, machine_pk=target.pk, exists=False)
        _resolve(subject)
        assert not ModelRelationship.objects.filter(machine_model=subject).exists()

    def test_unresolved_machine_target_drops_claim(self, subject, target, source):
        """A non-null target_machine pk that doesn't exist drops the claim —
        nullability doesn't weaken the FK guard."""
        _assert_edge_claim(subject, source, machine_pk=target.pk)
        missing_pk = target.pk
        target.delete()
        _resolve(subject)

        assert not ModelRelationship.objects.filter(
            machine_model=subject, target_machine_id=missing_pk
        ).exists()

    def test_claim_key_is_target_machine_only(self, subject, target, source):
        """The identity is the machine target alone — the label wording never
        enters the key (a label edge's key is constant per model)."""
        claim_key, _value = build_relationship_claim(
            "model_relationship",
            {
                **_identity(machine_pk=target.pk),
                "relationship_type": "copy",
                "license_status": "unknown",
            },
        )
        assert claim_key == f"model_relationship|target_machine:{target.pk}"

        label_key, _value = build_relationship_claim(
            "model_relationship",
            {
                **_identity(label="an unknown Gottlieb game"),
                "relationship_type": "copy",
                "license_status": "unknown",
            },
        )
        assert label_key == "model_relationship|target_machine:null"
