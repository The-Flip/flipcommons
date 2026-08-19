"""Cross-table actor-attribution invariants across every write path.

The interactive primitives are actor-first and bulk ingest stamps ``actor`` on
every row. ``actor`` is NOT NULL on both tables, so these rules hold table-wide
after any write:

* ``claim.actor == claim.changeset.actor``
* ``changeset.ingest_run IS NULL OR changeset.actor == ingest_run.source.actor``
* interactive changesets (``ingest_run IS NULL``) are user-backed
  (``actor.backing_model == "user"``) — the rule that moved off the dropped
  ``ChangeSet.user`` column.
"""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.catalog.models import Manufacturer
from apps.catalog.tests.conftest import make_machine_model
from apps.claim_edit.claim_write import (
    ClaimSpec,
    EntityClaims,
    execute_claims,
    execute_multi_entity_claims,
)
from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.plan import IngestPlan, PlannedClaimAssert, PlannedEntityCreate
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim, Source
from apps.provenance.revert import execute_revert, execute_undo_changeset

pytestmark = pytest.mark.django_db


def assert_attribution_invariants() -> None:
    """Assert the cross-table attribution rules over every row in the DB."""
    for claim in Claim.objects.select_related("changeset").all():
        cs = claim.changeset
        assert cs is not None, f"Claim {claim.pk} carries no changeset"
        assert claim.actor_id == cs.actor_id, (
            f"Claim {claim.pk}.actor != its changeset.actor"
        )

    for cs in ChangeSet.objects.select_related("actor", "ingest_run__source").all():
        ingest_run = cs.ingest_run
        if ingest_run is not None:
            assert cs.actor_id == ingest_run.source.actor_id, (
                f"ChangeSet {cs.pk}.actor != ingest_run.source.actor"
            )
        else:
            # Interactive changesets must be user-backed.
            assert cs.actor.backing_model == "user", (
                f"Interactive ChangeSet {cs.pk} has a "
                f"{cs.actor.backing_model!r} actor, expected 'user'"
            )


@pytest.fixture
def pm(db, bootstrap_source):
    return make_machine_model(
        name="Medieval Madness", slug="medieval-madness", production_year=1997
    )


def _active_user_claim(entity, field_name, user) -> Claim:
    ct = ContentType.objects.get_for_model(entity)
    return Claim.objects.get(
        content_type=ct,
        object_id=entity.pk,
        field_name=field_name,
        actor=user.actor,
        is_active=True,
    )


class TestWritePathSetsActor:
    def test_interactive(self, user, pm):
        execute_claims(
            pm, [ClaimSpec(field_name="production_year", value=1998)], user=user
        )
        claim = _active_user_claim(pm, "production_year", user)
        assert claim.actor_id == user.actor_id
        assert_attribution_invariants()

    def test_multi_entity(self, user, pm):
        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        execute_multi_entity_claims(
            [
                EntityClaims(pm, [ClaimSpec(field_name="production_year", value=1999)]),
                EntityClaims(mfr, [ClaimSpec(field_name="description", value="x")]),
            ],
            user=user,
            action=ChangeSetAction.EDIT,
        )
        for entity, field in ((pm, "production_year"), (mfr, "description")):
            assert _active_user_claim(entity, field, user).actor_id == user.actor_id
        assert_attribution_invariants()

    def test_revert(self, user, pm):
        execute_claims(
            pm, [ClaimSpec(field_name="production_year", value=1998)], user=user
        )
        claim = _active_user_claim(pm, "production_year", user)
        execute_revert(pm, claim_id=claim.pk, user=user, note="undo it")
        assert_attribution_invariants()

    def test_undo_changeset(self, user, pm):
        cs = execute_multi_entity_claims(
            [EntityClaims(pm, [ClaimSpec(field_name="production_year", value=1998)])],
            user=user,
            action=ChangeSetAction.DELETE,
        )
        execute_undo_changeset(cs, user=user, note="undo delete")
        assert_attribution_invariants()

    def test_ingest_bulk(self, bootstrap_source):
        source = Source.objects.create(
            name="TestSource", slug="test-source", source_type="database", priority=50
        )
        plan = IngestPlan(
            source=source,
            input_fingerprint="fp-actor",
            patch_id="fp-actor",
            entities=[
                PlannedEntityCreate(
                    model_class=Manufacturer,
                    kwargs={"name": "Bally", "slug": "bally", "status": "active"},
                    handle="bally",
                )
            ],
            assertions=[
                PlannedClaimAssert(
                    field_name="name", value="Bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="slug", value="bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="status", value="active", handle="bally", entry_index=0
                ),
            ],
        )
        apply_plan(plan)
        claim = Claim.objects.get(actor=source.actor, field_name="name")
        assert claim.actor_id == source.actor_id
        assert claim.changeset is not None
        assert claim.changeset.actor_id == source.actor_id
        assert_attribution_invariants()
