"""Mint-on-create: every backing record auto-creates and links its Actor."""

import pytest

from apps.accounts.test_factories import make_user
from apps.actors.models import Actor
from apps.actors.registry import is_machine_actor
from apps.provenance.models import Source


@pytest.mark.django_db
def test_creating_user_mints_actor():
    user = make_user(priority=10000)

    assert user.actor is not None
    assert user.actor.backing_model == "user"
    assert user.actor.priority == 10000
    assert user.actor.resolution_status == "active"
    # back-link resolves and is_machine derives from the registry
    assert user.actor.user == user
    assert is_machine_actor(user.actor.backing_model) is False


@pytest.mark.django_db
def test_creating_source_mints_actor():
    # Source.objects.create() is the admin / create() path — the guard that
    # Source creation never orphans an Actor.
    source = Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=10
    )

    assert source.actor is not None
    assert source.actor.backing_model == "source"
    assert source.actor.priority == 10
    assert source.actor.resolution_status == "active"
    assert source.actor.source == source
    assert is_machine_actor(source.actor.backing_model) is True


@pytest.mark.django_db
def test_resaving_does_not_mint_second_actor():
    user = make_user()
    original_actor_id = user.actor_id
    actor_count = Actor.objects.count()

    user.username = "renamed"
    user.save()

    user.refresh_from_db()
    assert user.actor_id == original_actor_id
    assert Actor.objects.count() == actor_count
