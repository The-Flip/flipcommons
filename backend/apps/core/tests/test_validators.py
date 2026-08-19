"""Tests for shared validators."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.catalog.tests.conftest import make_machine_model
from apps.core.validators import SLUG_RE, validate_no_mojibake


class TestSlugRe:
    """The system slug grammar must behave identically under every call style.

    Consumers use all three: ``fullmatch`` (cite parsing), ``match`` (catalog
    entity create, claim validation) and ``search`` (Django's
    ``RegexValidator`` on the citation slug field). With ``$`` anchoring,
    ``match``/``search`` accept one trailing newline that ``fullmatch``
    rejects — a slug that saves but can never be resolved — so the pattern
    must use absolute anchors.
    """

    @pytest.mark.parametrize("value", ["billboard", "1945-09-29", "vol-2"])
    def test_valid_slugs_pass_every_call_style(self, value):
        assert SLUG_RE.fullmatch(value)
        assert SLUG_RE.match(value)
        assert SLUG_RE.search(value)

    @pytest.mark.parametrize(
        "value",
        ["billboard\n", "\nbillboard", "Billboard", "game_room", "-x", "x-", ""],
    )
    def test_invalid_slugs_fail_every_call_style(self, value):
        assert not SLUG_RE.fullmatch(value)
        assert not SLUG_RE.match(value)
        assert not SLUG_RE.search(value)


class TestValidateNoMojibake:
    """validate_no_mojibake rejects encoding-corrupted text."""

    @pytest.mark.parametrize(
        "value",
        [
            "Medieval Madness",
            "D. Gottlieb & Company",
            "Bally/Williams",
            "René Lalonde",
            "Günter",
            "São Paulo",
            "naïve",
            "Señor",
            "François",
            "Łukasz",
            "Rock’n’Roll",
            "Pinball™",
            "Bally — Midway",
            "東京",
            "🎱 Pinball",
            "",
            None,
        ],
    )
    def test_allows_valid_text(self, value):
        validate_no_mojibake(value)

    @pytest.mark.parametrize(
        ("value", "match"),
        [
            ("MediÃ©val", "mojibake"),
            ("Ã¼ber", "mojibake"),
            ("Ã±o", "mojibake"),
            ("FranÃ§ois", "mojibake"),
            ("PokÃ©mon", "mojibake"),
            ("\u00e2\u20ac\u2122s", "mojibake"),  # â€™s
            ("\u00e2\u20ac\u201d", "mojibake"),  # â€” (em dash)
            ("â„¢", "mojibake"),
            ("ðŸŽ± Pinball", "mojibake"),
            ("hello\ufffd", "replacement character"),
            ("\ufffd", "replacement character"),
        ],
    )
    def test_rejects_mojibake_and_replacement_characters(self, value, match):
        with pytest.raises(ValidationError, match=match):
            validate_no_mojibake(value)


@pytest.mark.django_db
class TestMojibakeClaimsApiIntegration:
    """Mojibake is rejected when submitted via the claims PATCH endpoint."""

    @pytest.fixture
    def user(self, db):
        from apps.accounts.test_factories import make_user

        return make_user(email="editor@example.com")

    @pytest.fixture
    def pm(self):

        return make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness",
            production_year=1997,
        )

    def test_rejects_mojibake_name_via_claims_api(self, client, user, pm):
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data={"fields": {"name": "MediÃ©val Madness"}, "note": ""},
            content_type="application/json",
        )
        assert resp.status_code == 422

    def test_accepts_valid_accented_name_via_claims_api(self, client, user, pm):
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data={"fields": {"name": "Médiéval Madness"}, "note": ""},
            content_type="application/json",
        )
        assert resp.status_code == 200


@pytest.mark.django_db
class TestMojibakeBatchValidation:
    """Mojibake handling in batch validation (the bulk ingest path).

    ``validate_claims_batch`` logs and drops invalid claims instead of
    raising, the opposite of the per-field ``validate_no_mojibake`` path.
    """

    @pytest.fixture
    def pm(self):
        return make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness",
            production_year=1997,
        )

    def test_rejects_mojibake_name_claim(self, pm):
        from apps.provenance.models import Claim
        from apps.provenance.validation import validate_claims_batch

        ct_id = ContentType.objects.get_for_model(pm).pk
        pending = [
            Claim(
                content_type_id=ct_id,
                object_id=pm.pk,
                field_name="name",
                value="MediÃ©val Madness",
            ),
        ]
        # Batch validation logs and skips mojibake claims instead of raising.
        valid, rejected = validate_claims_batch(pending)
        assert rejected == 1
        assert valid == []

    def test_allows_valid_accented_name_claim(self, pm):
        from apps.provenance.models import Claim
        from apps.provenance.validation import validate_claims_batch

        ct_id = ContentType.objects.get_for_model(pm).pk
        pending = [
            Claim(
                content_type_id=ct_id,
                object_id=pm.pk,
                field_name="name",
                value="Médiéval Madness",
            ),
        ]
        valid, rejected = validate_claims_batch(pending)
        assert rejected == 0
        assert len(valid) == 1

    def test_allows_mojibake_in_alias_claim(self):
        """Alias fields do NOT have the mojibake validator — garbled source
        names are legitimate lookup values."""
        from apps.catalog.models import Manufacturer
        from apps.provenance.claims import build_relationship_claim
        from apps.provenance.models import Claim
        from apps.provenance.validation import validate_claims_batch

        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        ct_id = ContentType.objects.get_for_model(mfr).pk

        claim_key, value = build_relationship_claim(
            "manufacturer_alias",
            {"alias_value": "GÃ¶ttlieb", "alias_display": "GÃ¶ttlieb"},
        )
        pending = [
            Claim(
                content_type_id=ct_id,
                object_id=mfr.pk,
                field_name="manufacturer_alias",
                claim_key=claim_key,
                value=value,
            ),
        ]
        # Should NOT be rejected — alias values are exempt from mojibake validation.
        valid, rejected = validate_claims_batch(pending)
        assert rejected == 0
        assert len(valid) == 1
