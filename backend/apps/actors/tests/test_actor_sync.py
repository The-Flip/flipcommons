"""The drift contract: Actor mirrors backing fields on create and on update."""

import pytest

from apps.accounts.test_factories import make_user
from apps.actors.models import Actor
from apps.provenance.models import Source


@pytest.mark.django_db
def test_non_default_source_create_mints_correct_actor():
    # The case the class-default approach got wrong: a disabled, high-priority
    # source must mint priority=10, suppressed — not the defaults.
    source = Source.objects.create(
        name="Retired DB",
        slug="retired-db",
        source_type="database",
        priority=10,
        is_enabled=False,
    )

    assert source.actor.priority == 10
    assert source.actor.resolution_status == "suppressed"


@pytest.mark.django_db
def test_editing_source_resyncs_actor():
    source = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=5
    )
    actor_id = source.actor_id
    # Seed sources (provenance/0004) already minted actors, so assert on a
    # before/after delta rather than an absolute count.
    actor_count = Actor.objects.count()

    source.priority = 99
    source.is_enabled = False
    source.save()

    source.actor.refresh_from_db()
    assert source.actor_id == actor_id  # same Actor, not a new one
    assert source.actor.priority == 99
    assert source.actor.resolution_status == "suppressed"
    assert Actor.objects.count() == actor_count  # update synced, did not mint


@pytest.mark.django_db
def test_editing_user_priority_resyncs_actor():
    user = make_user(priority=10000)

    user.priority = 50
    user.save()

    user.actor.refresh_from_db()
    assert user.actor.priority == 50
    assert user.actor.resolution_status == "active"


@pytest.mark.django_db
def test_queryset_update_bypasses_mirror():
    """Pins the permanent limitation: QuerySet.update() skips save(), so it does
    NOT sync the Actor. The mirror is permanent (the satellite columns are kept),
    so this constraint is permanent too — e.g. a bulk is_enabled update would
    silently leave the kill switch desynced.
    See ActorModel mirror-hooks INVARIANT in apps/actors/models/base.py.
    """
    source = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=5
    )

    Source.objects.filter(pk=source.pk).update(priority=99)

    source.actor.refresh_from_db()
    assert source.actor.priority == 5  # mirror NOT updated by .update()
