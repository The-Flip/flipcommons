"""Guards for the actor-FK backfill migration (0013).

0012 added ``ChangeSet.actor`` / ``Claim.actor`` nullable and minted an Actor per
User/Source; 0013 fills the historical tail — the seed/old rows minted before the
write path stamped ``actor``, still at ``actor = NULL``.

These build the pre-backfill state (``actor = NULL`` rows, plus the broken shapes
the fail-fast checks catch), which can't exist on the post-0014 schema, so they
run against the historical state via :func:`historical_apps` (rewound to
provenance 0012 + accounts 0004, the node 0013 builds on). The reconstructed
historical models have no ``ActorModel`` save hook, so the test mints each Actor
and links its backing record by hand. The backfill never dereferences a claim's
subject, so a content type + arbitrary object_id stands in for a catalog record.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from apps.provenance.test_migration_state import historical_apps

_migration = importlib.import_module(
    "apps.provenance.migrations.0013_backfill_actor_fks"
)

_BEFORE = (
    ("provenance", "0012_source_actor_and_changeset_claim_actor"),
    ("accounts", "0004_user_actor"),
)


def _ct(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct, _ = ContentType.objects.get_or_create(app_label="catalog", model="manufacturer")
    return ct


def _mint(apps, backing: str, *, priority: int = 1000, status: str = "active"):
    Actor = apps.get_model("actors", "Actor")
    return Actor.objects.create(
        backing_model=backing, priority=priority, resolution_status=status
    )


def _user_with_actor(apps, username: str = "moses"):
    # Source.actor / User.actor are already NOT NULL at this state (0012/0004
    # minted them), so the Actor must exist before its backing record.
    User = apps.get_model("accounts", "User")
    return User.objects.create(
        username=username,
        email=f"{username}@example.com",
        password="!",
        actor=_mint(apps, "user"),
    )


def _source_with_actor(apps, slug: str = "opdb"):
    Source = apps.get_model("provenance", "Source")
    return Source.objects.create(
        name=slug.upper(),
        slug=slug,
        source_type="database",
        actor=_mint(apps, "source"),
    )


def _ingest_run(apps, source):
    IngestRun = apps.get_model("provenance", "IngestRun")
    return IngestRun.objects.create(
        source=source,
        input_fingerprint=f"sha256:{source.slug}",
        status="success",
        finished_at=datetime(2024, 1, 1, 17, 33, 28, tzinfo=UTC),
    )


def _claim(apps, ct, source=None, user=None, *, changeset, actor=None):
    Claim = apps.get_model("provenance", "Claim")
    return Claim.objects.create(
        content_type=ct,
        object_id=1,
        source=source,
        user=user,
        actor=actor,
        field_name="name",
        claim_key="name",
        value="x",
        changeset=changeset,
    )


@pytest.mark.django_db(transaction=True)
def test_backfills_user_attribution():
    with historical_apps(*_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        user = _user_with_actor(apps)
        cs = ChangeSet.objects.create(user=user, action="edit")  # actor=NULL
        claim = _claim(apps, ct, user=user, changeset=cs)  # actor=NULL

        _migration._forward(apps, None)

        cs.refresh_from_db()
        claim.refresh_from_db()
        assert cs.actor_id == user.actor_id
        assert claim.actor_id == user.actor_id


@pytest.mark.django_db(transaction=True)
def test_backfills_ingest_attribution():
    with historical_apps(*_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        source = _source_with_actor(apps)
        run = _ingest_run(apps, source)
        cs = ChangeSet.objects.create(ingest_run=run)  # actor=NULL
        claim = _claim(apps, ct, source=source, changeset=cs)  # actor=NULL

        _migration._forward(apps, None)

        cs.refresh_from_db()
        claim.refresh_from_db()
        assert cs.actor_id == source.actor_id
        assert claim.actor_id == source.actor_id


@pytest.mark.django_db(transaction=True)
def test_post_condition_no_nulls():
    with historical_apps(*_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        Claim = apps.get_model("provenance", "Claim")
        ct = _ct(apps)
        user = _user_with_actor(apps)
        source = _source_with_actor(apps)
        run = _ingest_run(apps, source)
        user_claim = _claim(
            apps,
            ct,
            user=user,
            changeset=ChangeSet.objects.create(user=user, action="edit"),
        )
        src_claim = Claim.objects.create(
            content_type=ct,
            object_id=1,
            source=source,
            field_name="url",
            claim_key="url",
            value="x",
            changeset=ChangeSet.objects.create(ingest_run=run),
        )

        _migration._forward(apps, None)

        assert not ChangeSet.objects.filter(actor__isnull=True).exists()
        assert not Claim.objects.filter(actor__isnull=True).exists()
        # The claims share a record but distinct authors, so distinct actors.
        user_claim.refresh_from_db()
        src_claim.refresh_from_db()
        assert user_claim.actor_id == user.actor_id
        assert src_claim.actor_id == source.actor_id


@pytest.mark.django_db(transaction=True)
def test_forward_is_idempotent():
    with historical_apps(*_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        Claim = apps.get_model("provenance", "Claim")
        ct = _ct(apps)
        user = _user_with_actor(apps)
        cs = ChangeSet.objects.create(user=user, action="edit")
        _claim(apps, ct, user=user, changeset=cs)

        _migration._forward(apps, None)
        first = dict(ChangeSet.objects.values_list("pk", "actor_id")) | dict(
            Claim.objects.values_list("pk", "actor_id")
        )
        _migration._forward(apps, None)
        second = dict(ChangeSet.objects.values_list("pk", "actor_id")) | dict(
            Claim.objects.values_list("pk", "actor_id")
        )

        assert first == second


@pytest.mark.django_db(transaction=True)
def test_prepopulated_rows_left_intact():
    """A row the write path already stamped is untouched (the actor__isnull filter)."""
    with historical_apps(*_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        user = _user_with_actor(apps)
        cs = ChangeSet.objects.create(user=user, action="edit", actor=user.actor)
        claim = _claim(apps, ct, user=user, changeset=cs, actor=user.actor)
        # Deliberately NOT nulled — these already carry the right actor.

        _migration._forward(apps, None)

        cs.refresh_from_db()
        claim.refresh_from_db()
        assert cs.actor_id == user.actor_id
        assert claim.actor_id == user.actor_id


@pytest.mark.django_db(transaction=True)
def test_reverse_nulls_actors():
    with historical_apps(*_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        user = _user_with_actor(apps)
        cs = ChangeSet.objects.create(user=user, action="edit")
        claim = _claim(apps, ct, user=user, changeset=cs)
        _migration._forward(apps, None)

        _migration._reverse(apps, None)

        cs.refresh_from_db()
        claim.refresh_from_db()
        assert cs.actor_id is None
        assert claim.actor_id is None


@pytest.mark.django_db(transaction=True)
def test_fail_fast_on_changeset_less_claim():
    with historical_apps(*_BEFORE) as apps:
        Claim = apps.get_model("provenance", "Claim")
        ct = _ct(apps)
        source = _source_with_actor(apps)
        # A claim with no changeset can never get an actor — trips the Claim null
        # checkpoint (0009/0011 should have given every claim a changeset).
        Claim.objects.create(
            content_type=ct,
            object_id=1,
            source=source,
            field_name="name",
            claim_key="name",
            value="x",
        )

        with pytest.raises(RuntimeError, match="changeset-less"):
            _migration._forward(apps, None)


@pytest.mark.django_db(transaction=True)
def test_fail_fast_on_attribution_mismatch():
    with historical_apps(*_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        # A historical bad row: claim attributed to src_a but riding a changeset
        # minted for src_b. The funnel would refuse this; construct it directly.
        src_a = _source_with_actor(apps, slug="src-a")
        src_b = _source_with_actor(apps, slug="src-b")
        cs_b = ChangeSet.objects.create(
            ingest_run=_ingest_run(apps, src_b)
        )  # actor backfills to src_b.actor
        _claim(apps, ct, source=src_a, changeset=cs_b)

        with pytest.raises(RuntimeError, match="disagrees with source"):
            _migration._forward(apps, None)
