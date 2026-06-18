"""Tests for Source.is_enabled filtering in claim resolution."""

import pytest

from apps.catalog.models import (
    CreditRole,
    Manufacturer,
    Person,
    Theme,
    Title,
)
from apps.catalog.resolve import (
    _resolve_bulk,
    resolve_all_themes,
    resolve_entity,
)
from apps.catalog.resolve._relationships import resolve_all_credits
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.helpers import active_claims
from apps.provenance.models import Claim, Source, get_claim_fields


@pytest.fixture
def source_a():
    return Source.objects.create(
        name="Source A", slug="source-a", source_type="database", priority=100
    )


@pytest.fixture
def source_b():
    return Source.objects.create(
        name="Source B", slug="source-b", source_type="editorial", priority=200
    )


@pytest.mark.django_db
class TestIsEnabledResolveSingle:
    def test_disabled_source_excluded_from_resolution(self, source_a):
        """Claims from a disabled source should not participate in resolution."""
        mfr = Manufacturer.objects.create(name="Test Mfr", slug="test-mfr")
        Claim.objects.assert_claim(mfr, "name", "From Disabled", source=source_a)

        source_a.is_enabled = False
        source_a.save()

        resolve_entity(mfr)
        mfr.refresh_from_db()
        assert mfr.name == "Test Mfr"

    def test_disabled_source_fallback_to_enabled(self, source_a, source_b):
        """When the higher-priority source is disabled, the lower-priority one wins."""
        mfr = Manufacturer.objects.create(name="Test Mfr", slug="test-mfr")
        Claim.objects.assert_claim(mfr, "name", "Low Priority", source=source_a)
        Claim.objects.assert_claim(mfr, "name", "High Priority", source=source_b)

        # With both enabled, source_b wins (priority 200 > 100).
        resolve_entity(mfr)
        mfr.refresh_from_db()
        assert mfr.name == "High Priority"

        # Disable source_b; source_a should now win.
        source_b.is_enabled = False
        source_b.save()

        resolve_entity(mfr)
        mfr.refresh_from_db()
        assert mfr.name == "Low Priority"


@pytest.mark.django_db
class TestIsEnabledResolveBulk:
    def test_disabled_source_excluded_from_bulk_resolution(self, source_a, source_b):
        """Bulk resolution should skip claims from disabled sources."""
        t = Title.objects.create(opdb_id="G1", name="Test Title", slug="t1")
        # Name claim from source_b (stays enabled) so name satisfies constraint.
        Claim.objects.assert_claim(t, "name", "Test Title", source=source_b)
        Claim.objects.assert_claim(t, "description", "From Disabled", source=source_a)

        source_a.is_enabled = False
        source_a.save()

        _resolve_bulk(Title, get_claim_fields(Title))

        t.refresh_from_db()
        assert t.description == ""  # Disabled source's claim excluded.

    def test_bulk_fallback_when_winner_disabled(self, source_a, source_b):
        """Bulk resolution falls back to enabled source when winner is disabled."""
        t = Title.objects.create(opdb_id="G1", name="Test Title", slug="t1")
        Claim.objects.assert_claim(t, "name", "Low Priority", source=source_a)
        Claim.objects.assert_claim(t, "name", "High Priority", source=source_b)

        source_b.is_enabled = False
        source_b.save()

        _resolve_bulk(Title, get_claim_fields(Title))

        t.refresh_from_db()
        assert t.name == "Low Priority"


@pytest.mark.django_db
class TestIsEnabledUserClaims:
    def test_user_claims_unaffected_by_source_enabled(self, source_a, user):
        """User claims (source=None) should not be filtered by is_enabled."""
        mfr = Manufacturer.objects.create(name="Test Mfr", slug="test-mfr")
        Claim.objects.assert_claim(mfr, "name", "User Claim", user=user)

        # Disable source_a (irrelevant — the claim is user-owned, not source-owned).
        source_a.is_enabled = False
        source_a.save()

        resolve_entity(mfr)
        mfr.refresh_from_db()
        assert mfr.name == "User Claim"


@pytest.mark.django_db
class TestIsEnabledRelationshipResolution:
    def test_disabled_source_theme_excluded(self, source_a):
        """Theme claims from a disabled source should not materialize."""
        theme = Theme.objects.create(name="Medieval", slug="medieval")
        pm = make_machine_model(name="Test", slug="test-pm")

        claim_key, value = build_relationship_claim("theme", {"theme": theme.pk})
        Claim.objects.assert_claim(
            pm,
            "theme",
            value,
            source=source_a,
            claim_key=claim_key,
        )

        # With source enabled, theme should resolve.
        resolve_all_themes(subject_ids={pm.pk})
        assert theme in pm.themes.all()

        # Disable source; theme should be removed.
        source_a.is_enabled = False
        source_a.save()

        resolve_all_themes(subject_ids={pm.pk})
        assert theme not in pm.themes.all()

    def test_disabled_source_credit_excluded(self, source_a):
        """Credit claims from a disabled source should not materialize."""
        role = CreditRole.objects.create(name="Design", slug="design")
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        pm = make_machine_model(name="Test", slug="test-pm")

        claim_key, value = build_relationship_claim(
            "credit", {"person": person.pk, "role": role.pk}
        )
        Claim.objects.assert_claim(
            pm,
            "credit",
            value,
            source=source_a,
            claim_key=claim_key,
        )

        # With source enabled, credit should resolve.
        resolve_all_credits(subject_ids={pm.pk})
        assert pm.credits.filter(person=person, role=role).exists()

        # Disable source; credit should be removed.
        source_a.is_enabled = False
        source_a.save()

        resolve_all_credits(subject_ids={pm.pk})
        assert not pm.credits.filter(person=person, role=role).exists()


@pytest.mark.django_db
class TestIsEnabledSourcesPrefetch:
    def test_claims_prefetch_excludes_disabled_source(self, source_a, source_b):
        """claims_prefetch() should not include claims from disabled sources."""
        from apps.provenance.helpers import claims_prefetch

        mfr = Manufacturer.objects.create(name="Test Mfr", slug="test-mfr")
        Claim.objects.assert_claim(mfr, "name", "From A", source=source_a)
        Claim.objects.assert_claim(mfr, "description", "From B", source=source_b)

        source_a.is_enabled = False
        source_a.save()

        prefetched = Manufacturer.objects.prefetch_related(claims_prefetch()).get(
            pk=mfr.pk
        )

        claims = active_claims(prefetched)
        source_slugs = {c.source.slug for c in claims if c.source}
        assert "source-a" not in source_slugs
        assert "source-b" in source_slugs
