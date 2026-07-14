"""Tests for CitationInstance model behavior and admin."""

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import RequestFactory

from apps.accounts.test_factories import make_user
from apps.citation.admin import CitationInstanceAdmin
from apps.citation.models import (
    CitationInstance,
    ReservedCitationSlug,
    reserve_citation_slug,
)
from apps.citation.test_factories import make_citation_source


@pytest.fixture
def citation_source(db):
    return make_citation_source(name="The Encyclopedia of Pinball", source_type="book")


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


class TestCitationInstanceCreation:
    def test_valid(self, citation_source):
        ci = CitationInstance.objects.create(
            citation_source=citation_source,
            locator="p. 30",
        )
        assert ci.pk is not None
        assert ci.locator == "p. 30"

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
# Quote mojibake — verbatim excerpts may reproduce a garbled source
# ---------------------------------------------------------------------------


class TestCitationInstanceQuoteMojibake:
    """``quote`` is a verbatim excerpt, so it must reproduce a source's own
    encoding corruption — including U+FFFD — rather than reject it. The
    corruption-rejecting ``validate_no_mojibake`` guard belongs on our authored
    fields (``locator`` and the ``CitationSource`` text), not here.
    """

    # IPDB machine 4645's Notes render "Sky<U+FFFD>Line"; a faithful quote of
    # that source contains the replacement character verbatim.
    GARBLED_QUOTE = "This game is a copy of Gottlieb's 1965 'Sky�Line'."

    def test_quote_allows_verbatim_replacement_character(self, citation_source):
        ci = CitationInstance(
            citation_source=citation_source,
            quote=self.GARBLED_QUOTE,
        )
        # Must not raise: a verbatim quote of a garbled source is legitimate.
        # slug is minted on save, so it isn't set on this unsaved instance.
        ci.full_clean(exclude=["slug"])

    def test_locator_still_rejects_mojibake(self, citation_source):
        ci = CitationInstance(
            citation_source=citation_source,
            locator="Sky�Line",
        )
        with pytest.raises(ValidationError, match="mojibake|replacement character"):
            ci.full_clean(exclude=["slug"])


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

        from apps.citation import models as ci_mod

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

    def test_mint_many_dodges_live_reservations(self, citation_source, monkeypatch):
        # A reservation and an instance live in separate tables, so the unique
        # constraint can't arbitrate — mint_many must skip a reserved slug
        # explicitly or it would break the reservation-holding draft's save.
        from apps.citation import models as ci_mod

        make_user_reservation(slug="bcdbcdbc")
        calls = {"n": 0}

        def fake_slug() -> str:
            calls["n"] += 1
            return "bcdbcdbc" if calls["n"] == 1 else "dfgdfgdf"

        monkeypatch.setattr(ci_mod, "generate_citation_slug", fake_slug)

        (minted,) = CitationInstance.objects.mint_many(
            [CitationInstance(citation_source=citation_source)]
        )
        assert minted.slug == "dfgdfgdf"

    def test_save_autogen_dodges_live_reservations(self, citation_source, monkeypatch):
        from apps.citation import models as ci_mod

        make_user_reservation(slug="bcdbcdbc")
        calls = {"n": 0}

        def fake_slug() -> str:
            calls["n"] += 1
            return "bcdbcdbc" if calls["n"] == 1 else "dfgdfgdf"

        monkeypatch.setattr(ci_mod, "generate_citation_slug", fake_slug)

        ci = CitationInstance.objects.create(citation_source=citation_source)
        assert ci.slug == "dfgdfgdf"

    def test_save_explicit_slug_may_match_a_reservation(self, citation_source):
        # An explicit slug IS a reservation being consumed by the save-time
        # mint — the dodge applies only to auto-generated slugs.
        make_user_reservation(slug="bcdbcdbc")
        ci = CitationInstance(citation_source=citation_source, slug="bcdbcdbc")
        ci.save()
        assert ci.slug == "bcdbcdbc"


# ---------------------------------------------------------------------------
# Slug reservations
# ---------------------------------------------------------------------------


def make_user_reservation(slug: str) -> ReservedCitationSlug:
    return ReservedCitationSlug.objects.create(slug=slug, created_by=make_user())


class TestReservedCitationSlug:
    def test_reserve_creates_row(self, user):
        reservation = reserve_citation_slug(user)
        assert reservation.created_by == user
        assert ReservedCitationSlug.objects.filter(slug=reservation.slug).exists()

    def test_reserve_dodges_existing_instance_slug(
        self, citation_source, user, monkeypatch
    ):
        from apps.citation import models as ci_mod

        CitationInstance.objects.create(
            citation_source=citation_source, slug="bcdbcdbc"
        )
        calls = {"n": 0}

        def fake_slug() -> str:
            calls["n"] += 1
            return "bcdbcdbc" if calls["n"] == 1 else "dfgdfgdf"

        monkeypatch.setattr(ci_mod, "generate_citation_slug", fake_slug)

        reservation = reserve_citation_slug(user)
        assert reservation.slug == "dfgdfgdf"

    def test_reserve_retries_on_reservation_collision_under_outer_atomic(
        self, user, monkeypatch
    ):
        from django.db import transaction

        from apps.citation import models as ci_mod

        make_user_reservation(slug="bcdbcdbc")
        calls = {"n": 0}

        def fake_slug() -> str:
            calls["n"] += 1
            return "bcdbcdbc" if calls["n"] == 1 else "dfgdfgdf"

        monkeypatch.setattr(ci_mod, "generate_citation_slug", fake_slug)

        with transaction.atomic():
            reservation = reserve_citation_slug(user)
        assert reservation.slug == "dfgdfgdf"

    def test_save_rejects_invalid_slug(self, user):
        with pytest.raises(ValidationError):
            ReservedCitationSlug.objects.create(slug="not-valid", created_by=user)


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
    # Claim-side lifecycle lives on the join: deleting a claim cascades its
    # ClaimCitationInstance links and deleting a linked instance is blocked by
    # the join's PROTECT — both covered in test_claim_citation_instance.py.
    def test_protect_prevents_source_delete(self, citation_source):
        CitationInstance.objects.create(citation_source=citation_source)
        with pytest.raises(ProtectedError):
            citation_source.delete()


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
