"""Tests for CitationInstance model behavior and admin."""

import pytest
from django.contrib import admin
from django.db.models import ProtectedError
from django.test import RequestFactory

from apps.citation.models import CitationSource
from apps.citation.test_factories import make_citation_source
from apps.provenance.admin import CitationInstanceAdmin
from apps.provenance.models import CitationInstance, Claim, Source
from apps.provenance.test_factories import claim_citation_instance, source_changeset


@pytest.fixture
def citation_source(db):
    return make_citation_source(name="The Encyclopedia of Pinball", source_type="book")


@pytest.fixture
def provenance_source(db):
    return Source.objects.create(
        name="Test Source", slug="test-source", source_type="editorial"
    )


@pytest.fixture
def claim(db, provenance_source):
    from django.contrib.contenttypes.models import ContentType

    # Use CitationSource as a convenient target — any model works. This target
    # isn't claim-controlled, so we create the row directly (not via make_claim);
    # actor + changeset are NOT NULL, so supply a source changeset and its actor.
    ct = ContentType.objects.get_for_model(CitationSource)
    cs = make_citation_source(name="Target", source_type="web")
    changeset = source_changeset(provenance_source)
    return Claim.objects.create(
        content_type=ct,
        object_id=cs.pk,
        actor=provenance_source.actor,
        changeset=changeset,
        field_name="name",
        claim_key="name",
        value="Target",
    )


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


class TestCitationInstanceCreation:
    def test_valid_with_claim(self, citation_source, claim):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
            claim=claim,
            locator="p. 30",
        )
        assert ci.pk is not None
        assert ci.claim == claim
        assert ci.locator == "p. 30"

    def test_valid_without_claim(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
            locator="front",
        )
        assert ci.pk is not None
        assert ci.claim is None

    def test_valid_with_empty_locator(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
        )
        assert ci.locator == ""

    def test_created_at_set(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
        )
        assert ci.created_at is not None


# ---------------------------------------------------------------------------
# Slug minting
# ---------------------------------------------------------------------------


class TestCitationInstanceSlug:
    def test_save_assigns_slug(self, citation_source):
        ci = CitationInstance.objects.create(citation_source=citation_source)
        assert ci.slug
        assert ci.slug.isalpha()
        assert ci.slug.islower()
        assert not any(c in "aeiou" for c in ci.slug)

    def test_slugs_unique_across_instances(self, citation_source):
        slugs = {
            CitationInstance.objects.create(citation_source=citation_source).slug
            for _ in range(25)
        }
        assert len(slugs) == 25

    def test_explicit_slug_preserved(self, citation_source):
        ci = CitationInstance(citation_source=citation_source, slug="bcdfghjk")
        ci.save()
        assert ci.slug == "bcdfghjk"

    @pytest.mark.parametrize(
        "bad_slug",
        [
            "abc123de",  # digits
            "bcdfghj",  # too short
            "bcdfghjkl",  # too long
            "bcdfghja",  # vowel
            "BCDFGHJK",  # uppercase
            "bcd-fghj",  # punctuation
        ],
    )
    def test_save_rejects_invalid_explicit_slug(self, citation_source, bad_slug):
        from django.core.exceptions import ValidationError

        ci = CitationInstance(citation_source=citation_source, slug=bad_slug)
        with pytest.raises(ValidationError, match="Invalid citation slug"):
            ci.save()

    def test_db_length_check_rejects_wrong_length(self, citation_source):
        # bulk_create skips save() (and its charset validation), so the
        # cross-backend length CHECK is the belt that still rejects a bad length.
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            CitationInstance.objects.bulk_create(
                [CitationInstance(citation_source=citation_source, slug="bcd")]
            )

    def test_mint_many_assigns_slugs(self, citation_source):
        instances = [
            CitationInstance(citation_source=citation_source) for _ in range(3)
        ]
        CitationInstance.objects.mint_many(instances)
        assert all(inst.pk and inst.slug for inst in instances)
        assert len({inst.slug for inst in instances}) == 3

    def test_mint_many_empty(self, db):
        assert CitationInstance.objects.mint_many([]) == []

    def test_mint_many_collision_retries_under_outer_atomic(
        self, citation_source, monkeypatch
    ):
        # Pre-seed a slug, then force the generator to emit it on the first
        # attempt (poisoning the insert) and a fresh one on the retry. The whole
        # thing runs inside an outer atomic() — the savepoint must let the failed
        # bulk_create roll back so the retry succeeds rather than raising
        # TransactionManagementError.
        from django.db import transaction

        from apps.provenance.models import citation_instance as ci_mod

        existing = CitationInstance.objects.create(
            citation_source=citation_source, slug="bcdbcdbc"
        )
        calls = {"n": 0}

        def fake_slug() -> str:
            calls["n"] += 1
            return "bcdbcdbc" if calls["n"] == 1 else "dfgdfgdf"

        monkeypatch.setattr(ci_mod, "generate_citation_slug", fake_slug)

        with transaction.atomic():
            (minted,) = CitationInstance.objects.mint_many(
                [CitationInstance(citation_source=citation_source)]
            )

        assert minted.slug == "dfgdfgdf"
        assert minted.slug != existing.slug
        assert calls["n"] >= 2  # collided once, regenerated


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestCitationInstanceImmutability:
    def test_save_raises_on_update(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
            locator="p. 30",
        )
        ci.locator = "p. 31"
        with pytest.raises(ValueError, match="immutable"):
            ci.save()


# ---------------------------------------------------------------------------
# PROTECT behavior
# ---------------------------------------------------------------------------


class TestCitationInstanceProtect:
    def test_protect_prevents_source_delete(self, citation_source):
        CitationInstance.objects.create(citation_source=citation_source)
        with pytest.raises(ProtectedError):
            citation_source.delete()

    def test_protect_prevents_claim_delete(self, citation_source, claim):
        CitationInstance.objects.create(citation_source=citation_source, claim=claim)
        with pytest.raises(ProtectedError):
            claim.delete()


# ---------------------------------------------------------------------------
# __str__
# ---------------------------------------------------------------------------


class TestCitationInstanceStr:
    def test_with_locator(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
            locator="p. 30",
        )
        assert str(ci) == f"Citation: {citation_source.pk} @ p. 30"

    def test_without_locator(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
        )
        assert str(ci) == f"Citation: {citation_source.pk}"


# ---------------------------------------------------------------------------
# Reverse relations
# ---------------------------------------------------------------------------


class TestCitationInstanceReverseRelations:
    def test_source_instances(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source, locator="p. 30"
        )
        assert ci in citation_source.instances.all()

    def test_claim_citation_instances(self, citation_source, claim):
        """``claim.citation_instances`` resolves through the join, not the
        legacy FK: a join-linked floating instance appears; an instance that
        only sets the FK does not."""
        linked = CitationInstance.objects.create(citation_source=citation_source)
        claim_citation_instance(claim, linked)
        fk_only = CitationInstance.objects.create(
            citation_source=citation_source, claim=claim
        )

        assert linked in claim.citation_instances.all()
        assert fk_only not in claim.citation_instances.all()
        assert claim in linked.claims.all()


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class TestCitationInstanceAdmin:
    @pytest.fixture
    def admin_instance(self):
        return CitationInstanceAdmin(CitationInstance, admin.site)

    def test_registered_in_admin(self):
        assert CitationInstance in admin.site._registry

    def test_is_read_only(self, admin_instance):
        factory = RequestFactory()
        request = factory.get("/")
        assert admin_instance.has_add_permission(request) is False
        assert admin_instance.has_change_permission(request) is False
        assert admin_instance.has_delete_permission(request) is False
