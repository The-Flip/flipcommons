"""Tests for the CorporateEntity ``operating_status`` field.

Records whether a corporate entity is still producing pinball
(``ongoing``/``ended``/``unknown``) — a claim-controlled editorial signal
distinct from the corporate-lifespan ``year_start``/``year_end`` columns.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from apps.catalog.models import CorporateEntity, Manufacturer, OperatingStatus
from apps.catalog.resolve import resolve_entity
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim
from apps.provenance.validation import validate_claim_value

pytestmark = pytest.mark.django_db


@pytest.fixture
def test_source(db):
    return Source.objects.create(
        name="TestSource",
        slug="test-source",
        source_type="database",
        priority=50,
    )


@pytest.fixture
def entity(db, test_source):
    mfr = Manufacturer.objects.create(name="Gottlieb", slug="gottlieb")
    ce = CorporateEntity.objects.create(
        name="D. Gottlieb & Company",
        slug="d-gottlieb-company",
        manufacturer=mfr,
    )
    # Name is non-unique, so resolution resets it to blank unless a claim
    # backs it. Seed one so resolve_entity() in these tests keeps the name.
    make_claim(ce, "name", "D. Gottlieb & Company", source=test_source)
    return ce


# ── Default ──────────────────────────────────────────────────────


def test_default_is_unknown(entity):
    """A freshly created entity defaults to ``unknown``."""
    assert entity.operating_status == OperatingStatus.UNKNOWN
    assert entity.operating_status == "unknown"


# ── Precedence rollup ────────────────────────────────────────────


class TestRollup:
    def test_empty_is_unknown(self):
        assert OperatingStatus.rollup([]) == OperatingStatus.UNKNOWN

    def test_any_ongoing_wins(self):
        assert (
            OperatingStatus.rollup(["ended", "ongoing", "unknown"])
            == OperatingStatus.ONGOING
        )

    def test_all_ended_is_ended(self):
        assert OperatingStatus.rollup(["ended", "ended"]) == OperatingStatus.ENDED

    def test_unknown_beats_ended(self):
        # ENDED only when *every* entity is known-ended; a mix is UNKNOWN.
        assert OperatingStatus.rollup(["ended", "unknown"]) == OperatingStatus.UNKNOWN

    def test_accepts_enum_members(self):
        assert (
            OperatingStatus.rollup([OperatingStatus.ENDED, OperatingStatus.ONGOING])
            == OperatingStatus.ONGOING
        )


# ── Choices validation at claim boundary ─────────────────────────


class TestChoicesValidation:
    def test_valid_value_passes_validation(self):
        value = validate_claim_value("operating_status", "ongoing", CorporateEntity)
        assert value == "ongoing"

    def test_invalid_value_rejected(self):
        with pytest.raises(ValidationError, match="not a valid choice"):
            validate_claim_value("operating_status", "bogus", CorporateEntity)

    def test_uppercase_value_rejected(self):
        """Casing is load-bearing — wire values are lowercase only."""
        with pytest.raises(ValidationError, match="not a valid choice"):
            validate_claim_value("operating_status", "Ongoing", CorporateEntity)


# ── Resolution ───────────────────────────────────────────────────


class TestResolution:
    def test_resolved_from_claim(self, entity, test_source):
        """The field resolves from a claim like any other scalar."""
        make_claim(entity, "operating_status", "ongoing", source=test_source)
        resolve_entity(entity)
        entity.refresh_from_db()
        assert entity.operating_status == OperatingStatus.ONGOING

    def test_unclaimed_resolves_to_unknown(self, entity):
        """Without a claim, resolution resets a non-unique field to its default.

        ``operating_status`` is non-unique with ``default=UNKNOWN``, so an
        unclaimed entity resolves to ``unknown`` — the baseline future
        unclassified entities rely on.
        """
        # Seed a non-default value, then resolve with no claims present.
        CorporateEntity.objects.filter(pk=entity.pk).update(
            operating_status=OperatingStatus.ONGOING
        )
        entity.refresh_from_db()
        assert entity.operating_status == OperatingStatus.ONGOING

        resolve_entity(entity)
        entity.refresh_from_db()
        assert entity.operating_status == OperatingStatus.UNKNOWN


# ── CheckConstraint ──────────────────────────────────────────────


class TestConstraint:
    def test_valid_value_accepted(self, entity):
        entity.operating_status = OperatingStatus.ENDED
        entity.full_clean()  # Should not raise.

    def test_invalid_value_rejected_by_db(self, entity):
        """DB constraint rejects invalid values (raw SQL bypasses Python)."""
        with connection.cursor() as cursor, pytest.raises(IntegrityError):
            cursor.execute(
                "UPDATE catalog_corporateentity SET operating_status = 'bogus' "
                "WHERE id = %s",
                [entity.pk],
            )
