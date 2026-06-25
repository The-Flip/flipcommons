"""Guards for the actor-FK backfill migration (0013).

0012 added ``ChangeSet.actor`` / ``Claim.actor`` nullable, and the write path
stamps both on every new row. 0013 fills the historical tail — the seed/old rows
minted before that, still at ``actor = NULL``. Since the live factories route
through ``record_changeset`` (which always sets ``actor``), these tests build
valid rows and then null the columns via :func:`_strip_actors` to recreate the
pre-backfill state, then run ``_forward`` and assert the fill + the fail-fast
checkpoints.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from apps.provenance.models import ChangeSet, Claim, Source
from apps.provenance.test_factories import (
    ingest_changeset,
    make_claim,
    user_changeset,
)
from apps.provenance.test_factories import ingest_run as make_ingest_run

_migration = importlib.import_module(
    "apps.provenance.migrations.0013_backfill_actor_fks"
)


def _strip_actors() -> None:
    """Recreate the pre-backfill historical state: ``actor = NULL`` everywhere."""
    ChangeSet.objects.update(actor=None)
    Claim.objects.update(actor=None)


@pytest.fixture
def mfr():
    from apps.catalog.models import Manufacturer

    return Manufacturer.objects.create(name="Acme", slug="acme")


@pytest.fixture
def user():
    return get_user_model().objects.create(username="moses", email="moses@example.com")


@pytest.fixture
def source():
    return Source.objects.create(name="OPDB", slug="opdb", source_type="database")


@pytest.mark.django_db
def test_backfills_user_attribution(mfr, user):
    cs = user_changeset(user)
    claim = make_claim(mfr, "name", "Acme", user=user, changeset=cs)
    _strip_actors()

    _migration._forward(django_apps, None)

    cs.refresh_from_db()
    claim.refresh_from_db()
    assert cs.actor_id == user.actor_id
    assert claim.actor_id == user.actor_id


@pytest.mark.django_db
def test_backfills_ingest_attribution(mfr, source):
    run = make_ingest_run(source)
    cs = ingest_changeset(run)
    claim = make_claim(mfr, "name", "Acme", source=source, changeset=cs)
    _strip_actors()

    _migration._forward(django_apps, None)

    cs.refresh_from_db()
    claim.refresh_from_db()
    assert cs.actor_id == source.actor_id
    assert claim.actor_id == source.actor_id


@pytest.mark.django_db
def test_post_condition_no_nulls(mfr, user, source):
    run = make_ingest_run(source)
    user_claim = make_claim(
        mfr, "name", "Acme", user=user, changeset=user_changeset(user)
    )
    src_claim = make_claim(
        mfr, "url", "x", source=source, changeset=ingest_changeset(run)
    )
    _strip_actors()

    _migration._forward(django_apps, None)

    assert not ChangeSet.objects.filter(actor__isnull=True).exists()
    assert not Claim.objects.filter(actor__isnull=True).exists()
    # The claims share a record but distinct authors, so distinct actors.
    user_claim.refresh_from_db()
    src_claim.refresh_from_db()
    assert user_claim.actor_id == user.actor_id
    assert src_claim.actor_id == source.actor_id


@pytest.mark.django_db
def test_forward_is_idempotent(mfr, user):
    cs = user_changeset(user)
    make_claim(mfr, "name", "Acme", user=user, changeset=cs)
    _strip_actors()

    _migration._forward(django_apps, None)
    first = dict(ChangeSet.objects.values_list("pk", "actor_id")) | dict(
        Claim.objects.values_list("pk", "actor_id")
    )
    _migration._forward(django_apps, None)
    second = dict(ChangeSet.objects.values_list("pk", "actor_id")) | dict(
        Claim.objects.values_list("pk", "actor_id")
    )

    assert first == second


@pytest.mark.django_db
def test_prepopulated_rows_left_intact(mfr, user):
    """A row the write path already stamped is untouched (the actor__isnull filter)."""
    cs = user_changeset(user)
    claim = make_claim(mfr, "name", "Acme", user=user, changeset=cs)
    # Deliberately NOT stripped — these already carry the right actor.

    _migration._forward(django_apps, None)

    cs.refresh_from_db()
    claim.refresh_from_db()
    assert cs.actor_id == user.actor_id
    assert claim.actor_id == user.actor_id


@pytest.mark.django_db
def test_reverse_nulls_actors(mfr, user):
    cs = user_changeset(user)
    claim = make_claim(mfr, "name", "Acme", user=user, changeset=cs)
    _strip_actors()
    _migration._forward(django_apps, None)

    _migration._reverse(django_apps, None)

    cs.refresh_from_db()
    claim.refresh_from_db()
    assert cs.actor_id is None
    assert claim.actor_id is None


@pytest.mark.django_db
def test_fail_fast_on_changeset_less_claim(mfr, source):
    # A claim with no changeset can never get an actor — trips the Claim null
    # checkpoint (0009/0011 should have given every claim a changeset).
    ct = ContentType.objects.get_for_model(type(mfr))
    Claim.objects.create(
        content_type=ct,
        object_id=mfr.pk,
        source=source,
        field_name="name",
        claim_key="name",
        value="x",
    )

    with pytest.raises(RuntimeError, match="changeset-less"):
        _migration._forward(django_apps, None)


@pytest.mark.django_db
def test_fail_fast_on_attribution_mismatch(mfr):
    # A historical bad row: claim attributed to src_a but riding a changeset
    # minted for src_b. The funnel would refuse this; construct it directly.
    src_a = Source.objects.create(name="A", slug="src-a", source_type="database")
    src_b = Source.objects.create(name="B", slug="src-b", source_type="database")
    cs_b = ingest_changeset(make_ingest_run(src_b))  # actor = src_b.actor
    ct = ContentType.objects.get_for_model(type(mfr))
    Claim.objects.create(
        content_type=ct,
        object_id=mfr.pk,
        source=src_a,
        field_name="name",
        claim_key="name",
        value="x",
        changeset=cs_b,
    )
    _strip_actors()

    with pytest.raises(RuntimeError, match="disagrees with source"):
        _migration._forward(django_apps, None)
