"""Guards for the ``claim_key`` repair migration (provenance 0027).

The migration renames ``claim_key`` on the rows catalog ``0026`` left pointing
at ``ipdb.model_number`` after moving their ``field_name`` to
``manufacturer_model_identifier``, then adds the CHECK constraint that stops
the two from drifting again.

Rewound to provenance ``0026`` via :func:`historical_apps`, because the drifted
shape cannot be built on the current schema at all — the constraint this very
migration adds rejects it. That is the point of the constraint, and it is also
why these tests need the historical state: catalog ``0026`` stays applied, so
the rewind lands exactly where production was, post-promotion and pre-repair.

Covered:

1. Drifted rows are repaired; canonical and relationship keys are left alone.
2. A repair that would collide with an existing active claim aborts, naming the
   claims, rather than picking a winner.
3. Drift this migration does not target aborts too, instead of surfacing later
   as a constraint failure that names no rows.
"""

from __future__ import annotations

import importlib

import pytest

from apps.provenance.test_migration_state import historical_apps

pytestmark = pytest.mark.migration

_migration = importlib.import_module(
    "apps.provenance.migrations.0027_repair_drifted_claim_keys"
)

_BEFORE = ("provenance", "0026_fk_claim_values_to_pk")

_STALE = "ipdb.model_number"
_FIELD = "manufacturer_model_identifier"


def _ct(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct, _ = ContentType.objects.get_or_create(app_label="catalog", model="machinemodel")
    return ct


def _actor(apps):
    """A bare Actor. The repair keys off (subject, actor, claim_key) only, so
    nothing here needs a backing Source row."""
    Actor = apps.get_model("actors", "Actor")
    return Actor.objects.create(
        backing_model="source", priority=1000, resolution_status="active"
    )


def _claim(apps, ct, actor, object_id, field_name, claim_key, *, is_active=True):
    ChangeSet = apps.get_model("provenance", "ChangeSet")
    Claim = apps.get_model("provenance", "Claim")
    return Claim.objects.create(
        content_type=ct,
        object_id=object_id,
        actor=actor,
        # Interactive changesets carry an action; ingest ones carry an
        # ingest_run instead. Either satisfies the DB's action-iff-interactive
        # check, and the repair reads neither.
        changeset=ChangeSet.objects.create(actor=actor, action="edit"),
        field_name=field_name,
        claim_key=claim_key,
        value="11000-LE",
        is_active=is_active,
    )


@pytest.mark.django_db(transaction=True)
def test_drifted_rows_are_repaired():
    """The 0026 shape gets its slot back; healthy rows are untouched."""
    with historical_apps(_BEFORE) as apps:
        ct = _ct(apps)
        ipdb = _actor(apps)
        drifted = _claim(apps, ct, ipdb, 1, _FIELD, _STALE)
        canonical = _claim(apps, ct, ipdb, 2, "name", "name")
        relationship = _claim(apps, ct, ipdb, 3, "theme", "theme|theme:153")

        _migration.repair_claim_keys(apps, None)

        drifted.refresh_from_db()
        canonical.refresh_from_db()
        relationship.refresh_from_db()
        assert drifted.claim_key == _FIELD
        assert canonical.claim_key == "name"
        assert relationship.claim_key == "theme|theme:153"


@pytest.mark.django_db(transaction=True)
def test_inactive_drifted_rows_are_repaired_too():
    """Inactive rows carry the history the Sources page renders, so they move.

    The unique index is partial on ``is_active``, so an inactive row can never
    collide — but leaving it behind would strand a superseded value in a slot
    nothing else reaches, and the constraint would reject it anyway.
    """
    with historical_apps(_BEFORE) as apps:
        ct = _ct(apps)
        ipdb = _actor(apps)
        superseded = _claim(apps, ct, ipdb, 1, _FIELD, _STALE, is_active=False)

        _migration.repair_claim_keys(apps, None)

        superseded.refresh_from_db()
        assert superseded.claim_key == _FIELD


@pytest.mark.django_db(transaction=True)
def test_collision_aborts_and_names_the_claims():
    """Same subject, same actor, both slots occupied — a human picks the winner."""
    with historical_apps(_BEFORE) as apps:
        ct = _ct(apps)
        ipdb = _actor(apps)
        drifted = _claim(apps, ct, ipdb, 1, _FIELD, _STALE)
        _claim(apps, ct, ipdb, 1, _FIELD, _FIELD)

        with pytest.raises(RuntimeError, match="would collide"):
            _migration.repair_claim_keys(apps, None)

        drifted.refresh_from_db()
        assert drifted.claim_key == _STALE, "aborted repair must not have written"


@pytest.mark.django_db(transaction=True)
def test_a_different_actor_is_not_a_collision():
    """Rival values from different actors are the whole point of the repair.

    This is the Medieval Madness case: IPDB's claim and a user's claim on the
    same field. They must end up in the *same* slot so one can win.
    """
    with historical_apps(_BEFORE) as apps:
        ct = _ct(apps)
        ipdb = _actor(apps)
        other = _actor(apps)
        drifted = _claim(apps, ct, ipdb, 1, _FIELD, _STALE)
        rival = _claim(apps, ct, other, 1, _FIELD, _FIELD)

        _migration.repair_claim_keys(apps, None)

        drifted.refresh_from_db()
        assert drifted.claim_key == rival.claim_key == _FIELD


@pytest.mark.django_db(transaction=True)
def test_untargeted_drift_aborts_before_the_constraint_does():
    """Drift from a cause this migration doesn't know about stops the deploy here.

    Without this sweep the same rows would fail ``AddConstraint`` instead, with
    a message that names no rows and leaves you grepping for them.
    """
    with historical_apps(_BEFORE) as apps:
        ct = _ct(apps)
        ipdb = _actor(apps)
        _claim(apps, ct, ipdb, 1, "some_other_field", "unrelated.key")

        with pytest.raises(RuntimeError, match="does not target"):
            _migration.repair_claim_keys(apps, None)
