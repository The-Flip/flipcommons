"""Tests for Claim.license write path — assert_claim and the apply path."""

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.plan import IngestPlan, PlannedClaimAssert
from apps.core.models import License
from apps.provenance.models import Claim, Source


@pytest.fixture
def source():
    return Source.objects.create(name="Test", slug="test", priority=100)


@pytest.fixture
def cc_by_sa(db):
    return License.objects.create(
        name="CC BY-SA 4.0",
        slug="cc-by-sa-4-0",
        short_name="CC BY-SA",
        permissiveness_rank=50,
        allows_display=True,
    )


@pytest.fixture
def not_allowed(db):
    return License.objects.create(
        name="Not Allowed",
        slug="not-allowed",
        short_name="Not Allowed",
        permissiveness_rank=0,
        allows_display=False,
    )


@pytest.mark.django_db
class TestAssertClaimLicense:
    def test_assert_claim_with_license(self, source, cc_by_sa):
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer.objects.create(name="Test", slug="test")
        claim = Claim.objects.assert_claim(
            mfr, "description", "text", source=source, license=cc_by_sa
        )
        assert claim.license == cc_by_sa

    def test_assert_claim_without_license(self, source):
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer.objects.create(name="Test", slug="test")
        claim = Claim.objects.assert_claim(mfr, "description", "text", source=source)
        assert claim.license is None


@pytest.mark.django_db
class TestApplyPlanLicense:
    """License-aware claim diffing on the bulk ingest (apply) path."""

    def _desc_plan(self, source, ct_id, obj_id, fp, license_id):
        # patch_id keyed off the (per-call distinct) fingerprint so the ledger's
        # per-patch_id uniqueness stays happy across the two runs.
        return IngestPlan(
            source=source,
            input_fingerprint=fp,
            patch_id=fp,
            assertions=[
                PlannedClaimAssert(
                    field_name="description",
                    value="text",
                    content_type_id=ct_id,
                    object_id=obj_id,
                    license_id=license_id,
                    entry_index=0,
                ),
            ],
        )

    def test_license_change_detected(self, source, cc_by_sa, not_allowed):
        """Changing only the license on a claim should supersede the old one."""
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer.objects.create(name="Test", slug="test")
        ct_id = ContentType.objects.get_for_model(Manufacturer).pk

        # First: assert with cc_by_sa license.
        report = apply_plan(self._desc_plan(source, ct_id, mfr.pk, "fp-1", cc_by_sa.pk))
        assert report.asserted == 1

        # Second: same value, different license.
        report = apply_plan(
            self._desc_plan(source, ct_id, mfr.pk, "fp-2", not_allowed.pk)
        )
        assert report.asserted == 1
        assert report.superseded == 1

        # Verify the active claim has the new license.
        active = Claim.objects.get(
            content_type_id=ct_id,
            object_id=mfr.pk,
            field_name="description",
            is_active=True,
        )
        assert active.license == not_allowed

    def test_same_license_unchanged(self, source, cc_by_sa):
        """Re-asserting the same value+license should be a no-op."""
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer.objects.create(name="Test", slug="test")
        ct_id = ContentType.objects.get_for_model(Manufacturer).pk

        apply_plan(self._desc_plan(source, ct_id, mfr.pk, "fp-1", cc_by_sa.pk))

        # Re-assert identical claim.
        report = apply_plan(self._desc_plan(source, ct_id, mfr.pk, "fp-2", cc_by_sa.pk))
        assert report.unchanged == 1
        assert report.asserted == 0
