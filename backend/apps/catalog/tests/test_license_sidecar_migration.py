"""Guards for the license-sidecar conversion migration (catalog 0019).

The migration rewrites already-materialized ``extra_data`` sidecars from
``{field}.__license_slug`` to ``{field}.__license_id`` so attribution keeps
working immediately after deploy — without it, the reader (which knows only
``__license_id``) would silently drop attribution until each entity happened
to re-resolve.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from apps.catalog.models import Manufacturer
from apps.catalog.tests.conftest import make_machine_model
from apps.core.models import License

_migration = importlib.import_module(
    "apps.catalog.migrations.0019_license_sidecar_slug_to_id"
)


@pytest.fixture
def cc_by_sa(db):
    return License.objects.create(
        name="CC BY-SA 4.0",
        slug="cc-by-sa-4-0",
        short_name="CC BY-SA",
        permissiveness_rank=50,
    )


@pytest.mark.django_db
class TestLicenseSidecarMigration:
    def test_slug_sidecar_converts_to_id(self, cc_by_sa):
        pm = make_machine_model(name="M", slug="m")
        pm.extra_data = {
            "opdb.images": [{"primary": True, "urls": {"medium": "https://x/m.jpg"}}],
            "opdb.images.__license_slug": "cc-by-sa-4-0",
            "opdb.images.__permissiveness_rank": 50,
        }
        pm.save(update_fields=["extra_data"])

        _migration.convert_license_sidecars(django_apps, None)

        pm.refresh_from_db()
        assert pm.extra_data["opdb.images.__license_id"] == cc_by_sa.pk
        assert "opdb.images.__license_slug" not in pm.extra_data
        # Neighbouring keys untouched.
        assert pm.extra_data["opdb.images.__permissiveness_rank"] == 50

    def test_null_slug_becomes_null_id(self):
        pm = make_machine_model(name="M", slug="m")
        pm.extra_data = {"image_urls.__license_slug": None}
        pm.save(update_fields=["extra_data"])

        _migration.convert_license_sidecars(django_apps, None)

        pm.refresh_from_db()
        assert pm.extra_data == {"image_urls.__license_id": None}

    def test_covers_every_extra_data_model(self, cc_by_sa):
        # Introspection-driven: any model with an extra_data JSONField is
        # covered, not just MachineModel.
        mfr = Manufacturer.objects.create(
            name="Acme",
            slug="acme",
            extra_data={"image_urls.__license_slug": "cc-by-sa-4-0"},
        )

        _migration.convert_license_sidecars(django_apps, None)

        mfr.refresh_from_db()
        assert mfr.extra_data == {"image_urls.__license_id": cc_by_sa.pk}

    def test_rows_without_sidecars_untouched(self):
        pm = make_machine_model(name="M", slug="m")
        pm.extra_data = {"model_number": "20021"}
        pm.save(update_fields=["extra_data"])

        _migration.convert_license_sidecars(django_apps, None)

        pm.refresh_from_db()
        assert pm.extra_data == {"model_number": "20021"}

    def test_unknown_license_slug_fails_with_report(self):
        pm = make_machine_model(name="M", slug="m")
        pm.extra_data = {"opdb.images.__license_slug": "never-existed"}
        pm.save(update_fields=["extra_data"])

        with pytest.raises(RuntimeError, match="never-existed"):
            _migration.convert_license_sidecars(django_apps, None)

        pm.refresh_from_db()
        assert pm.extra_data == {"opdb.images.__license_slug": "never-existed"}

    def test_idempotent_on_converted_data(self, cc_by_sa):
        pm = make_machine_model(name="M", slug="m")
        pm.extra_data = {"opdb.images.__license_id": cc_by_sa.pk}
        pm.save(update_fields=["extra_data"])

        _migration.convert_license_sidecars(django_apps, None)

        pm.refresh_from_db()
        assert pm.extra_data == {"opdb.images.__license_id": cc_by_sa.pk}
