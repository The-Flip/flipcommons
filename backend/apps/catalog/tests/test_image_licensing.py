"""Tests for image license denormalization and display threshold filtering."""

import pytest

from apps.catalog.api.images import extract_image_urls
from apps.catalog.models import Title
from apps.catalog.resolve import resolve_machine_models, resolve_model
from apps.catalog.tests.conftest import make_machine_model
from apps.core.models import License
from apps.provenance.licensing import resolve_effective_license
from apps.provenance.models import Source, SourceFieldLicense
from apps.provenance.test_factories import make_claim


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


@pytest.fixture
def opdb(cc_by_sa):
    return Source.objects.create(
        name="OPDB",
        slug="opdb",
        source_type="database",
        priority=200,
        default_license=None,  # unknown
    )


@pytest.fixture
def ipdb(not_allowed):
    return Source.objects.create(
        name="IPDB",
        slug="ipdb",
        source_type="database",
        priority=100,
        default_license=not_allowed,
    )


@pytest.mark.django_db
class TestEffectiveLicenseResolution:
    def test_claim_license_overrides_all(self, opdb, cc_by_sa):
        """Per-claim license takes precedence over source defaults."""
        title = Title.objects.create(name="Test Title", slug="t1")
        claim = make_claim(title, "description", "text", source=opdb)
        claim.license = cc_by_sa
        claim.save()
        claim.refresh_from_db()
        # Need source loaded for resolution
        claim.source = opdb

        lic = resolve_effective_license(claim)
        assert lic == cc_by_sa

    def test_source_field_license_used(self, opdb, cc_by_sa):
        """SourceFieldLicense overrides source default for matching field."""
        SourceFieldLicense.objects.create(
            source=opdb, field_name="description", license=cc_by_sa
        )
        title = Title.objects.create(name="Test Title", slug="t1")
        claim = make_claim(title, "description", "text", source=opdb)
        claim.source = opdb

        from apps.provenance.licensing import build_source_field_license_map

        sfl_map = build_source_field_license_map()
        lic = resolve_effective_license(claim, sfl_map)
        assert lic == cc_by_sa

    def test_source_default_license_fallback(self, ipdb, not_allowed):
        """Falls back to source.default_license when no overrides exist."""
        title = Title.objects.create(name="Test Title", slug="t1")
        claim = make_claim(title, "description", "text", source=ipdb)
        claim.source = ipdb

        lic = resolve_effective_license(claim)
        assert lic == not_allowed

    def test_all_null_returns_none(self, opdb):
        """Returns None when no license is set anywhere."""
        title = Title.objects.create(name="Test Title", slug="t1")
        claim = make_claim(title, "description", "text", source=opdb)
        claim.source = opdb

        lic = resolve_effective_license(claim)
        assert lic is None


@pytest.mark.django_db
class TestImageLicenseDenormalization:
    def test_image_license_resolution_does_not_n_plus_one(
        self, opdb, cc_by_sa, django_assert_max_num_queries
    ):
        """The image-license fallback must not lazy-load default_license per model.

        The resolver reads ``claim.actor.source.default_license`` for image
        fields; ``ranked_claims(...).select_related("actor__source__default_license")``
        must prefetch the whole chain. If it ever shortens to ``actor__source``
        (or the stale ``source__default_license``), each model adds one query —
        an N+1 the byte-identical value tests can't see. Six licensed-image
        models would add six queries; this bound (measured ~211 + slack) catches
        the regression while tolerating unrelated query drift.
        """
        opdb.default_license = cc_by_sa
        opdb.save()
        for i in range(6):
            pm = make_machine_model(name=f"M{i}", slug=f"m{i}")
            make_claim(pm, "name", f"M{i}", source=opdb)
            make_claim(
                pm,
                "opdb.images",
                [{"primary": True, "urls": {"large": f"https://img/{i}.jpg"}}],
                source=opdb,
                claim_key=f"opdb.images|x:{i}",
            )

        with django_assert_max_num_queries(216):
            resolve_machine_models()

    def test_resolution_stores_permissiveness_rank_in_extra_data(self, opdb, cc_by_sa):
        """Resolution should denormalize license rank into extra_data for image fields."""
        opdb.default_license = cc_by_sa
        opdb.save()

        pm = make_machine_model(name="Test", slug="test-pm")
        make_claim(pm, "name", "Test", source=opdb)
        make_claim(
            pm,
            "opdb.images",
            [
                {
                    "primary": True,
                    "urls": {
                        "small": "https://img.opdb.org/s.jpg",
                        "medium": "https://img.opdb.org/m.jpg",
                        "large": "https://img.opdb.org/l.jpg",
                    },
                }
            ],
            source=opdb,
        )

        resolve_model(pm)
        pm.refresh_from_db()

        assert pm.extra_data.get("opdb.images.__license_slug") == "cc-by-sa-4-0"
        assert pm.extra_data.get("opdb.images.__permissiveness_rank") == 50

    def test_null_license_stores_null_rank(self, opdb):
        """Null license should store null rank in extra_data."""
        pm = make_machine_model(name="Test", slug="test-pm")
        make_claim(pm, "name", "Test", source=opdb)
        make_claim(
            pm,
            "opdb.images",
            [
                {
                    "primary": True,
                    "urls": {
                        "small": "https://img.opdb.org/s.jpg",
                        "medium": "https://img.opdb.org/m.jpg",
                        "large": "https://img.opdb.org/l.jpg",
                    },
                }
            ],
            source=opdb,
        )

        resolve_model(pm)
        pm.refresh_from_db()

        assert pm.extra_data.get("opdb.images.__license_slug") is None
        assert pm.extra_data.get("opdb.images.__permissiveness_rank") is None


class TestExtractImageUrlsWithThreshold:
    @pytest.fixture(autouse=True)
    def _licensed_only_policy(self):
        from constance.test import override_config

        with override_config(CONTENT_DISPLAY_POLICY="licensed-only"):
            yield

    def test_skips_images_below_threshold(self):
        """Images with rank below display threshold should be skipped."""
        extra_data = {
            "opdb.images": [
                {
                    "primary": True,
                    "urls": {
                        "medium": "https://img.opdb.org/m.jpg",
                        "large": "https://img.opdb.org/l.jpg",
                    },
                }
            ],
            "opdb.images.__license_slug": "not-allowed",
            "opdb.images.__permissiveness_rank": 0,
        }
        thumb, hero = extract_image_urls(extra_data, None)
        assert thumb is None
        assert hero is None

    def test_falls_through_to_licensed_source(self):
        """When first source is below threshold, fall through to next."""
        extra_data = {
            "opdb.images": [
                {
                    "primary": True,
                    "urls": {
                        "medium": "https://img.opdb.org/opdb.jpg",
                        "large": "https://img.opdb.org/opdb-l.jpg",
                    },
                }
            ],
            "opdb.images.__permissiveness_rank": 0,  # below threshold
            "ipdb.image_urls": ["https://ipdb.org/ipdb.jpg"],
            "ipdb.image_urls.__permissiveness_rank": 85,  # above threshold
        }
        thumb, _ = extract_image_urls(extra_data, None)
        assert thumb == "https://ipdb.org/ipdb.jpg"

    def test_null_rank_uses_unknown_rank(self):
        """Null permissiveness_rank (unknown license) should use UNKNOWN_LICENSE_RANK."""
        extra_data = {
            "opdb.images": [
                {
                    "primary": True,
                    "urls": {
                        "medium": "https://img.opdb.org/m.jpg",
                        "large": "https://img.opdb.org/l.jpg",
                    },
                }
            ],
            "opdb.images.__permissiveness_rank": None,  # unknown
        }
        # With "licensed-only" (min_rank=38), unknown (rank 5) should be hidden.
        thumb, hero = extract_image_urls(extra_data, None)
        assert thumb is None
        assert hero is None

    def test_show_all_displays_everything(self):
        """With show-all policy, even Not Allowed images display."""
        from constance.test import override_config

        extra_data = {
            "opdb.images": [
                {
                    "primary": True,
                    "urls": {
                        "medium": "https://img.opdb.org/m.jpg",
                        "large": "https://img.opdb.org/l.jpg",
                    },
                }
            ],
            "opdb.images.__permissiveness_rank": 0,
        }
        with override_config(CONTENT_DISPLAY_POLICY="show-all"):
            thumb, _ = extract_image_urls(extra_data, None)
        assert thumb == "https://img.opdb.org/m.jpg"

    def test_include_unknown_shows_null_rank(self):
        """With include-unknown policy, null-rank images display."""
        from constance.test import override_config

        extra_data = {
            "opdb.images": [
                {
                    "primary": True,
                    "urls": {
                        "medium": "https://img.opdb.org/m.jpg",
                        "large": "https://img.opdb.org/l.jpg",
                    },
                }
            ],
            "opdb.images.__permissiveness_rank": None,
        }
        with override_config(CONTENT_DISPLAY_POLICY="include-unknown"):
            thumb, _ = extract_image_urls(extra_data, None)
        assert thumb == "https://img.opdb.org/m.jpg"
