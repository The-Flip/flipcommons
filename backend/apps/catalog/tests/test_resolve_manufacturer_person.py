"""Tests for resolve_manufacturer() and resolve_person()."""

import pytest

from apps.catalog.models import Manufacturer, Person
from apps.catalog.resolve import resolve_entity
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim


@pytest.fixture
def ipdb(db):
    return Source.objects.create(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def editorial(db):
    return Source.objects.create(
        name="Editorial", source_type="editorial", priority=100
    )


@pytest.fixture
def mfr(db):
    return Manufacturer.objects.create(name="Placeholder Mfr", slug="placeholder-mfr")


@pytest.fixture
def person(db):
    return Person.objects.create(name="Placeholder Person", slug="placeholder-person")


class TestResolveManufacturer:
    def test_basic_resolution(self, mfr, ipdb):
        make_claim(mfr, "name", "Williams", source=ipdb)

        resolved = resolve_entity(mfr)
        assert resolved.name == "Williams"

    def test_higher_priority_wins(self, mfr, ipdb, editorial):
        make_claim(mfr, "name", "Williams Low", source=ipdb)
        make_claim(mfr, "name", "Williams High", source=editorial)

        resolved = resolve_entity(mfr)
        assert resolved.name == "Williams High"

    def test_deactivated_claim_is_not_applied(self, mfr, ipdb):
        make_claim(mfr, "description", "Old desc", source=ipdb)
        # Supersede it.
        make_claim(mfr, "description", "New desc", source=ipdb)

        resolved = resolve_entity(mfr)
        assert resolved.description == "New desc"
        assert mfr.claims.filter(is_active=False).count() == 1

    def test_no_claims_resets_to_defaults(self, mfr):
        """Claims are the sole source of truth: a field with no active claim is blanked."""
        mfr.description = "Something"
        mfr.save()

        resolved = resolve_entity(mfr)
        assert resolved.description == ""

    def test_all_claims_removed_field_blanked(self, mfr, ipdb):
        """Deactivating all claims for a field blanks it on the next resolve."""
        make_claim(mfr, "description", "Old bio", source=ipdb)
        resolve_entity(mfr)
        assert mfr.description == "Old bio"

        mfr.claims.filter(field_name="description").update(is_active=False)

        resolve_entity(mfr)
        mfr.refresh_from_db()
        assert mfr.description == ""  # blanked — no active claims remain

    def test_saves_to_db(self, mfr, ipdb):
        make_claim(mfr, "name", "Bally", source=ipdb)
        resolve_entity(mfr)
        mfr.refresh_from_db()
        assert mfr.name == "Bally"


class TestResolvePerson:
    def test_basic_resolution(self, person, ipdb):
        make_claim(person, "name", "Pat Lawlor", source=ipdb)
        make_claim(person, "description", "Designer of TAF.", source=ipdb)

        resolved = resolve_entity(person)
        assert resolved.name == "Pat Lawlor"
        assert resolved.description == "Designer of TAF."

    def test_higher_priority_wins(self, person, ipdb, editorial):
        make_claim(person, "name", "Pat Lawlor", source=ipdb)
        make_claim(person, "description", "Short bio.", source=ipdb)
        make_claim(person, "description", "Better bio.", source=editorial)

        resolved = resolve_entity(person)
        assert resolved.description == "Better bio."

    def test_no_claims_resets_to_defaults(self, person, ipdb):
        """Claims are the sole source of truth: a field with no active claim is blanked."""
        person.description = "Something"
        person.save()

        # Name claim required to satisfy the non-blank constraint.
        make_claim(person, "name", "Placeholder Person", source=ipdb)
        resolved = resolve_entity(person)
        assert resolved.description == ""

    def test_saves_to_db(self, person, ipdb):
        make_claim(person, "name", "Steve Ritchie", source=ipdb)
        resolve_entity(person)
        person.refresh_from_db()
        assert person.name == "Steve Ritchie"
