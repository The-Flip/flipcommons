"""Behavior pinned by the "Tighten schema" PR.

After this PR ``ChangeSet.actor`` / ``Claim.actor`` / ``Claim.changeset`` are NOT
NULL, dedupe keys on ``actor``, and a single unified partial-unique index
(``provenance_unique_active_claim_per_actor``) enforces one active claim per
actor per ``claim_key`` on a subject. These tests lock:

* the actor-keyed dedupe / unified-index uniqueness (negative);
* cross-actor coexistence — distinct actors share a field (the unified index is
  the *union* of the old per-source/per-user indexes, never stricter);
* the NOT NULL columns reject actor-less / changeset-less rows.
"""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError

from apps.catalog.models import Manufacturer
from apps.provenance.models import ChangeSet, Claim, Source
from apps.provenance.test_factories import make_claim, source_changeset

pytestmark = pytest.mark.django_db


@pytest.fixture
def mfr():
    return Manufacturer.objects.create(name="Williams", slug="williams")


@pytest.fixture
def source():
    return Source.objects.create(
        name="OPDB", slug="opdb", source_type="database", priority=10
    )


def test_actor_keyed_dedupe_supersedes_prior_claim(mfr, user):
    """A second edit of the same field by the same actor deactivates the first."""
    first = make_claim(mfr, "name", "V1", user=user)
    second = make_claim(mfr, "name", "V2", user=user)

    first.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True
    assert second.actor_id == user.actor_id


def test_unified_index_rejects_duplicate_active_per_actor(mfr, user):
    """Bypassing the dedupe primitive, a second active claim for the same
    (subject, actor, claim_key) trips the unified unique index."""
    first = make_claim(mfr, "name", "V1", user=user)
    ct = ContentType.objects.get_for_model(Manufacturer)
    with pytest.raises(IntegrityError):
        Claim.objects.create(
            content_type=ct,
            object_id=mfr.pk,
            user=user,
            actor=user.actor,
            changeset=first.changeset,
            field_name="name",
            claim_key="name",
            value="V2",
            is_active=True,
        )


def test_distinct_actors_coexist_on_same_field(mfr, user, source):
    """An active source claim and an active user claim on the same
    (subject, claim_key) both survive — they are different keys under the
    unified index, exactly as the two legacy per-author indexes allowed."""
    src_claim = make_claim(mfr, "name", "From source", source=source)
    user_claim = make_claim(mfr, "name", "From user", user=user)

    src_claim.refresh_from_db()
    user_claim.refresh_from_db()
    assert src_claim.is_active is True
    assert user_claim.is_active is True
    assert src_claim.actor_id == source.actor_id
    assert user_claim.actor_id == user.actor_id
    assert src_claim.actor_id != user_claim.actor_id


def test_claim_without_actor_rejected(mfr, source):
    ct = ContentType.objects.get_for_model(Manufacturer)
    with pytest.raises(IntegrityError):
        Claim.objects.create(
            content_type=ct,
            object_id=mfr.pk,
            source=source,
            changeset=source_changeset(source),
            field_name="name",
            claim_key="name",
            value="x",
        )


def test_claim_without_changeset_rejected(mfr, source):
    ct = ContentType.objects.get_for_model(Manufacturer)
    with pytest.raises(IntegrityError):
        Claim.objects.create(
            content_type=ct,
            object_id=mfr.pk,
            source=source,
            actor=source.actor,
            field_name="name",
            claim_key="name",
            value="x",
        )


def test_changeset_without_actor_rejected(user):
    with pytest.raises(IntegrityError):
        ChangeSet.objects.create(user=user, action="edit")
