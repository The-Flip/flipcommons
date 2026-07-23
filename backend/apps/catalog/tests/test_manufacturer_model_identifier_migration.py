"""Guards for the manufacturer-model-identifier promotion migration (catalog 0026).

The migration renames ``ipdb.model_number`` claims to
``manufacturer_model_identifier`` (keeping their IPDB ingest attribution) and
moves the parked ``extra_data`` value into the new column, so the value
displays immediately after deploy instead of after each entity re-resolves.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.test_factories import make_claim, make_ingest_source

_migration = importlib.import_module(
    "apps.catalog.migrations.0026_promote_manufacturer_model_identifier"
)


@pytest.fixture
def ipdb(db):
    return make_ingest_source(name="IPDB", source_type="database", priority=10)


@pytest.mark.django_db
class TestManufacturerModelIdentifierMigration:
    def test_claim_renamed_and_value_promoted(self, ipdb):
        pm = make_machine_model(name="M", slug="m")
        claim = make_claim(pm, "ipdb.model_number", "20021", ingest_source=ipdb)
        pm.extra_data = {"ipdb.model_number": "20021", "ipdb.notes": "kept"}
        pm.save(update_fields=["extra_data"])

        _migration.promote_model_number(django_apps, None)

        pm.refresh_from_db()
        assert pm.manufacturer_model_identifier == "20021"
        assert "ipdb.model_number" not in pm.extra_data
        # Neighbouring parked keys untouched.
        assert pm.extra_data["ipdb.notes"] == "kept"

        # The claim row is renamed in place — same actor, so the IPDB ingest
        # attribution carries over without a new ChangeSet.
        claim.refresh_from_db()
        assert claim.field_name == "manufacturer_model_identifier"
        # claim_key is derived from field_name, so it has to move with it.
        # Asserting only the line above is what let the original migration ship
        # having rewritten the input and not the output, stranding every
        # promoted row in a slot no later claim could reach. See provenance 0027.
        assert claim.claim_key == "manufacturer_model_identifier"

    def test_blank_parked_value_drops_key_leaves_null(self, ipdb):
        pm = make_machine_model(name="M", slug="m")
        pm.extra_data = {"ipdb.model_number": "  "}
        pm.save(update_fields=["extra_data"])

        _migration.promote_model_number(django_apps, None)

        pm.refresh_from_db()
        assert pm.manufacturer_model_identifier is None
        assert pm.extra_data == {}

    def test_rows_without_key_untouched(self):
        pm = make_machine_model(name="M", slug="m")
        pm.extra_data = {"ipdb.notes": "n"}
        pm.save(update_fields=["extra_data"])

        _migration.promote_model_number(django_apps, None)

        pm.refresh_from_db()
        assert pm.manufacturer_model_identifier is None
        assert pm.extra_data == {"ipdb.notes": "n"}

    def test_reverse_parks_value_back(self, ipdb):
        pm = make_machine_model(name="M", slug="m")
        claim = make_claim(pm, "ipdb.model_number", "20021", ingest_source=ipdb)
        pm.extra_data = {"ipdb.model_number": "20021"}
        pm.save(update_fields=["extra_data"])

        _migration.promote_model_number(django_apps, None)
        _migration.demote_model_number(django_apps, None)

        pm.refresh_from_db()
        assert pm.manufacturer_model_identifier is None
        assert pm.extra_data == {"ipdb.model_number": "20021"}
        assert pm.claims.filter(field_name="ipdb.model_number").exists()
        assert not pm.claims.filter(field_name="manufacturer_model_identifier").exists()
        # Both columns come back together. Moving field_name alone would be the
        # same drift mirrored, and would now trip the provenance 0027 constraint
        # on the way down.
        claim.refresh_from_db()
        assert claim.field_name == claim.claim_key == "ipdb.model_number"
