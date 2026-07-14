"""Tests for provenance.validation — claim-boundary validation."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import (
    CorporateEntity,
    Location,
    MachineModel,
    Manufacturer,
    Person,
    System,
    Theme,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Claim
from apps.provenance.test_factories import make_claim, make_ingest_source
from apps.provenance.validation import (
    DIRECT,
    EXTRA,
    RELATIONSHIP,
    UNRECOGNIZED,
    FkClaim,
    classify_claim,
    validate_claim_value,
    validate_claims_batch,
    validate_fk_claims_batch,
    validate_relationship_claims_batch,
)

# ---------------------------------------------------------------------------
# validate_claim_value
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateClaimValue:
    def test_valid_string_passes(self):
        result = validate_claim_value("name", "Eight Ball Deluxe", MachineModel)
        assert result == "Eight Ball Deluxe"

    def test_valid_integer_passes(self):
        # ipdb_id has MinValueValidator(1)
        result = validate_claim_value("ipdb_id", 42, MachineModel)
        assert result == 42

    def test_out_of_range_integer_rejected(self):
        # ipdb_id has MinValueValidator(1), so 0 should fail
        with pytest.raises(ValidationError):
            validate_claim_value("ipdb_id", 0, MachineModel)

    def test_invalid_type_coercion_rejected(self):
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_claim_value("ipdb_id", "not-a-number", MachineModel)

    def test_mojibake_rejected(self):
        # Mojibake: "Ã©" is é misinterpreted through cp1252
        with pytest.raises(ValidationError, match="mojibake"):
            validate_claim_value("name", "Caf\u00c3\u00a9", Person)

    def test_valid_accented_passes(self):
        result = validate_claim_value("name", "Café", Person)
        assert result == "Café"

    def test_whitespace_only_rejected_for_required_field(self):
        with pytest.raises(ValidationError, match="cannot be blank"):
            validate_claim_value("name", "   ", MachineModel)

    def test_whitespace_only_allowed_for_blank_field(self):
        # production_quantity is blank=True — whitespace-only is fine
        result = validate_claim_value("production_quantity", "   ", MachineModel)
        assert result == "   "

    def test_empty_string_skips_validators(self):
        # Empty string is the sentinel for "clear this field". Should not run
        # validators (which would reject "" as out of range for ipdb_id).
        result = validate_claim_value("ipdb_id", "", MachineModel)
        assert result == ""

    def test_float_decimal_field_not_rejected(self):
        # JSON has no Decimal type — values arrive as float. Ensure float 8.95
        # is not rejected by DecimalValidator due to IEEE 754 artifacts.
        result = validate_claim_value("ipdb_rating", 8.95, MachineModel)
        assert result == 8.95

    def test_fk_field_accepts_int_pk(self):
        # System.manufacturer is a FK to Manufacturer — PKs pass unchanged.
        assert validate_claim_value("manufacturer", 42, System) == 42

    def test_fk_field_accepts_clear_sentinels(self):
        assert validate_claim_value("manufacturer", "", System) == ""
        assert validate_claim_value("manufacturer", None, System) is None

    def test_fk_field_rejects_string(self):
        # Slugs are an authoring-boundary format; a string reaching the mint
        # primitive is a caller bug.
        with pytest.raises(ValidationError, match="integer PK"):
            validate_claim_value("manufacturer", "some-slug", System)

    def test_fk_field_rejects_bool(self):
        with pytest.raises(ValidationError, match="integer PK"):
            validate_claim_value("manufacturer", True, System)

    # --- Field-specific validators ---

    def test_wikidata_id_valid_format_passes(self):
        result = validate_claim_value("wikidata_id", "Q312897", Person)
        assert result == "Q312897"

    def test_wikidata_id_invalid_format_rejected(self):
        with pytest.raises(ValidationError, match="Wikidata ID"):
            validate_claim_value("wikidata_id", "WD312897", Person)

    def test_wikidata_id_bare_number_rejected(self):
        with pytest.raises(ValidationError, match="Wikidata ID"):
            validate_claim_value("wikidata_id", "312897", Person)

    def test_wikidata_id_manufacturer_valid_passes(self):
        result = validate_claim_value("wikidata_id", "Q180268", Manufacturer)
        assert result == "Q180268"

    def test_wikidata_id_manufacturer_invalid_rejected(self):
        with pytest.raises(ValidationError, match="Wikidata ID"):
            validate_claim_value("wikidata_id", "WD180268", Manufacturer)

    def test_opdb_manufacturer_id_zero_rejected(self):
        with pytest.raises(ValidationError):
            validate_claim_value("opdb_manufacturer_id", 0, Manufacturer)

    def test_opdb_manufacturer_id_valid_passes(self):
        result = validate_claim_value("opdb_manufacturer_id", 7, Manufacturer)
        assert result == 7

    def test_ipdb_manufacturer_id_zero_rejected(self):
        with pytest.raises(ValidationError):
            validate_claim_value("ipdb_manufacturer_id", 0, CorporateEntity)

    def test_fandom_page_id_zero_rejected(self):
        with pytest.raises(ValidationError):
            validate_claim_value("fandom_page_id", 0, Title)

    def test_fandom_page_id_valid_passes(self):
        result = validate_claim_value("fandom_page_id", 42, Title)
        assert result == 42

    def test_production_quantity_mojibake_rejected(self):
        with pytest.raises(ValidationError, match="mojibake"):
            validate_claim_value("production_quantity", "Caf\u00c3\u00a9", MachineModel)

    def test_birth_place_mojibake_rejected(self):
        with pytest.raises(ValidationError, match="mojibake"):
            validate_claim_value("birth_place", "Caf\u00c3\u00a9", Person)

    def test_location_description_mojibake_rejected(self):
        with pytest.raises(ValidationError, match="mojibake"):
            validate_claim_value("description", "Caf\u00c3\u00a9", Location)


# ---------------------------------------------------------------------------
# validate_claims_batch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateClaimsBatch:
    @pytest.fixture
    def manufacturer(self):
        return Manufacturer.objects.create(name="Williams", slug="williams")

    @pytest.fixture
    def system(self, manufacturer):
        return System.objects.create(name="WPC", slug="wpc", manufacturer=manufacturer)

    @pytest.fixture
    def model(self):
        return make_machine_model(name="Eight Ball", slug="eight-ball")

    def test_valid_scalar_claim_passes(self, model):
        claim = Claim.for_object(model, field_name="name", value="Eight Ball Deluxe")
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 0
        assert len(valid) == 1
        assert valid[0].value == "Eight Ball Deluxe"

    def test_invalid_scalar_claim_rejected(self, model):
        claim = Claim.for_object(model, field_name="ipdb_id", value="not-a-number")
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 1
        assert len(valid) == 0

    def test_mixed_valid_and_invalid(self, model):
        good = Claim.for_object(model, field_name="name", value="Good Name")
        bad = Claim.for_object(model, field_name="ipdb_id", value="bad")
        valid, rejected = validate_claims_batch([good, bad])
        assert rejected == 1
        assert len(valid) == 1
        assert valid[0].field_name == "name"

    def test_relationship_with_valid_targets_passes(self, model, credit_targets):
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={"person": pat_pk, "role": design_pk, "exists": True},
            claim_key=f"credit|person:{pat_pk}|role:{design_pk}",
        )
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 0
        assert len(valid) == 1

    def test_extra_data_claim_passes_through(self, model):
        claim = Claim.for_object(
            model, field_name="opdb.description", value="A great game"
        )
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 0
        assert len(valid) == 1

    def test_unrecognized_field_name_rejected(self):
        # Use Theme which has no extra_data fallback — unknown fields are rejected.
        theme = Theme.objects.create(name="Medieval", slug="medieval")
        claim = Claim.for_object(
            theme, field_name="nonexistent_field", value="whatever"
        )
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 1
        assert len(valid) == 0

    def test_unknown_field_on_extra_data_model_passes(self, model):
        # MachineModel has extra_data — unknown fields resolve into it.
        claim = Claim.for_object(
            model, field_name="nonexistent_field", value="whatever"
        )
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 0
        assert len(valid) == 1

    def test_fk_claim_with_valid_target(self, system, manufacturer):
        claim = Claim.for_object(
            system, field_name="manufacturer", value=manufacturer.pk
        )
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 0
        assert len(valid) == 1

    def test_fk_claim_with_nonexistent_target(self, system):
        claim = Claim.for_object(system, field_name="manufacturer", value=999999)
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 1
        assert len(valid) == 0

    def test_fk_claim_with_empty_value_passes(self, system):
        claim = Claim.for_object(system, field_name="manufacturer", value="")
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 0
        assert len(valid) == 1


# ---------------------------------------------------------------------------
# validate_fk_claims_batch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateFkClaimsBatch:
    @pytest.fixture
    def manufacturer(self):
        return Manufacturer.objects.create(name="Williams", slug="williams")

    @pytest.fixture
    def system(self, manufacturer):
        return System.objects.create(name="WPC", slug="wpc", manufacturer=manufacturer)

    def test_valid_fk_passes(self, system, manufacturer):
        claim = Claim.for_object(
            system, field_name="manufacturer", value=manufacturer.pk
        )
        rejected = validate_fk_claims_batch([FkClaim(claim, System)])
        assert rejected == []

    def test_invalid_fk_rejected(self, system):
        claim = Claim.for_object(system, field_name="manufacturer", value=999999)
        rejected = validate_fk_claims_batch([FkClaim(claim, System)])
        assert len(rejected) == 1

    def test_non_int_value_rejected_without_query(self, system):
        # A stray string can never resolve; rejected outright.
        claim = Claim.for_object(
            system, field_name="manufacturer", value="no-such-slug"
        )
        rejected = validate_fk_claims_batch([FkClaim(claim, System)])
        assert len(rejected) == 1

    def test_empty_value_not_rejected(self, system):
        claim = Claim.for_object(system, field_name="manufacturer", value="")
        rejected = validate_fk_claims_batch([FkClaim(claim, System)])
        assert rejected == []

    def test_batch_queries_once_per_group(
        self, system, manufacturer, django_assert_num_queries
    ):
        """Multiple claims for the same (model, field) should result in one query."""
        c1 = Claim.for_object(system, field_name="manufacturer", value=manufacturer.pk)
        c2 = Claim.for_object(system, field_name="manufacturer", value=999999)
        with django_assert_num_queries(1):
            rejected = validate_fk_claims_batch(
                [
                    FkClaim(c1, System),
                    FkClaim(c2, System),
                ]
            )
        assert len(rejected) == 1


# ---------------------------------------------------------------------------
# classify_claim
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestClassifyClaim:
    def test_scalar_field_is_direct(self):
        assert classify_claim(MachineModel, "name", "", "Test") == DIRECT

    def test_fk_field_is_direct(self):
        assert classify_claim(System, "manufacturer", "", "williams") == DIRECT

    def test_relationship_claim_detected(self):
        """Compound claim_key + dict value with 'exists' → RELATIONSHIP."""
        assert (
            classify_claim(
                MachineModel,
                "credit",
                "credit|person:1|role:2",
                {"person": 1, "role": 2, "exists": True},
            )
            == RELATIONSHIP
        )

    def test_extra_data_on_model_with_extra_data(self):
        """Unknown field on a model with extra_data → EXTRA."""
        assert classify_claim(MachineModel, "opdb.description", "", "text") == EXTRA

    def test_unrecognized_on_model_without_extra_data(self):
        """Unknown field on a model without extra_data → UNRECOGNIZED."""
        assert classify_claim(Theme, "nonexistent", "", "whatever") == UNRECOGNIZED

    def test_undotted_extra_data_on_model_with_extra_data(self):
        """Undotted unknown field on model with extra_data → EXTRA."""
        assert classify_claim(MachineModel, "manufacturer", "", "williams") == EXTRA

    def test_every_registered_namespace_classifies_as_relationship(self):
        """Integration check: registry and classifier agree.

        Two properties in one walk:
        (1) ``build_relationship_claim`` accepts every namespace surfaced by
            ``get_all_namespace_keys()`` — drift between the two helpers
            surfaces as a ``ValueError`` here.
        (2) ``classify_claim`` returns ``RELATIONSHIP`` for every registered
            namespace (when not shadowed by a DIRECT field on the subject).

        The claim_key / value *contract* — canonical key shape, required
        ``exists``, dict payload — is pinned by ``TestBuildRelationshipClaim
        CanonicalKey`` in ``test_claims.py`` and by the rejection-mode tests
        below, not by the classifier (which is registry-driven and does not
        inspect ``claim_key`` or ``value``).
        """
        from apps.catalog.claims import get_all_namespace_keys
        from apps.provenance.claims import build_relationship_claim

        for namespace, keys in get_all_namespace_keys().items():
            identity = dict.fromkeys(keys, "test-value")
            claim_key, value = build_relationship_claim(namespace, identity)

            # MachineModel isn't in every namespace's valid_subjects, but
            # classify_claim is subject-agnostic for RELATIONSHIP routing —
            # wrong-subject is the validator's concern, not the classifier's.
            result = classify_claim(MachineModel, namespace, claim_key, value)
            assert result == RELATIONSHIP, (
                f"Namespace {namespace!r} classified as {result!r}, expected RELATIONSHIP."
            )


# ---------------------------------------------------------------------------
# assert_claim validation (B4)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssertClaimValidation:
    @pytest.fixture
    def source(self):
        return make_ingest_source(
            name="test-source", source_type="database", priority=10
        )

    def test_rejects_invalid_direct_claim(self, source):
        """assert_claim should reject invalid scalar values."""
        model = make_machine_model(name="Test", slug="test")
        with pytest.raises(ValidationError, match="must be an integer"):
            make_claim(model, "ipdb_id", "not-a-number", ingest_source=source)

    def test_allows_valid_direct_claim(self, source):
        model = make_machine_model(name="Test", slug="test")
        claim = make_claim(model, "ipdb_id", 42, ingest_source=source)
        assert claim.value == 42

    def test_allows_relationship_claim(self, source):
        """assert_claim accepts relationship claims (batch target validation is separate)."""
        model = make_machine_model(name="Test", slug="test")
        claim = make_claim(
            model,
            "credit",
            {"person": 1, "role": 2, "exists": True},
            ingest_source=source,
            claim_key="credit|person:1|role:2",
        )
        assert claim.field_name == "credit"

    def test_allows_extra_data_claim(self, source):
        """Extra-data claims should pass through without validation."""
        model = make_machine_model(name="Test", slug="test")
        claim = make_claim(
            model, "opdb.description", "A great game", ingest_source=source
        )
        assert claim.value == "A great game"

    def test_rejects_unrecognized_claim(self, source):
        """Unrecognized field on a model without extra_data is rejected."""
        theme = Theme.objects.create(name="Medieval", slug="medieval")
        with pytest.raises(ValueError, match="Unrecognized claim field_name"):
            make_claim(theme, "nonexistent_field", "whatever", ingest_source=source)


# ---------------------------------------------------------------------------
# validate_relationship_claims_batch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateRelationshipClaimsBatch:
    @pytest.fixture
    def model(self):
        return make_machine_model(name="Eight Ball", slug="eight-ball")

    @pytest.fixture
    def theme(self):
        return Theme.objects.create(name="Medieval", slug="medieval")

    def test_valid_credit_passes(self, model, credit_targets):
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={"person": pat_pk, "role": design_pk, "exists": True},
            claim_key=f"credit|person:{pat_pk}|role:{design_pk}",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert rejected == []

    def test_nonexistent_person_rejected(self, model, credit_targets):
        design_pk = credit_targets["roles"]["design"].pk
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={
                "person": 99999,
                "role": design_pk,
                "exists": True,
            },
            claim_key=f"credit|person:99999|role:{design_pk}",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert len(rejected) == 1

    def test_nonexistent_role_rejected(self, model, credit_targets):
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={
                "person": pat_pk,
                "role": 99999,
                "exists": True,
            },
            claim_key=f"credit|person:{pat_pk}|role:99999",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert len(rejected) == 1

    def test_both_targets_invalid_rejects_once(self, model):
        """A credit with both person and role missing is rejected once, not twice."""
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={
                "person": 99998,
                "role": 99999,
                "exists": True,
            },
            claim_key="credit|person:99998|role:99999",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert len(rejected) == 1

    def test_valid_theme_passes(self, model, theme):
        claim = Claim.for_object(
            model,
            field_name="theme",
            value={"theme": theme.pk, "exists": True},
            claim_key=f"theme|theme:{theme.pk}",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert rejected == []

    def test_nonexistent_theme_rejected(self, model):
        claim = Claim.for_object(
            model,
            field_name="theme",
            value={"theme": 99999, "exists": True},
            claim_key="theme|theme:99999",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert len(rejected) == 1

    def test_retraction_with_nonexistent_target_passes(self, model):
        """exists=False retractions pass even when the target no longer exists."""
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={
                "person": 99998,
                "role": 99999,
                "exists": False,
            },
            claim_key="credit|person:99998|role:99999",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert rejected == []

    def test_alias_namespace_passes_through(self, model):
        """Alias namespaces are not registered — claims pass without checking."""
        claim = Claim.for_object(
            model,
            field_name="theme_alias",
            value={"alias_value": "anything", "exists": True},
            claim_key="theme_alias|alias:anything",
        )
        rejected = validate_relationship_claims_batch([claim])
        assert rejected == []

    def test_batch_queries_once_per_group(
        self, model, credit_targets, django_assert_num_queries
    ):
        """Multiple credit claims should batch into one Person + one CreditRole query."""
        steve = Person.objects.create(name="Steve Ritchie", slug="steve-ritchie")
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        c1 = Claim.for_object(
            model,
            field_name="credit",
            value={"person": pat_pk, "role": design_pk, "exists": True},
            claim_key=f"credit|person:{pat_pk}|role:{design_pk}",
        )
        c2 = Claim.for_object(
            model,
            field_name="credit",
            value={
                "person": steve.pk,
                "role": design_pk,
                "exists": True,
            },
            claim_key=f"credit|person:{steve.pk}|role:{design_pk}",
        )
        # 2 queries: one for Person PKs, one for CreditRole PKs.
        with django_assert_num_queries(2):
            rejected = validate_relationship_claims_batch([c1, c2])
        assert rejected == []


# ---------------------------------------------------------------------------
# validate_claims_batch — relationship integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateClaimsBatchRelationships:
    @pytest.fixture
    def model(self):
        return make_machine_model(name="Test", slug="test")

    def test_valid_relationship_passes_batch(self, model, credit_targets):
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={"person": pat_pk, "role": design_pk, "exists": True},
            claim_key=f"credit|person:{pat_pk}|role:{design_pk}",
        )
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 0
        assert len(valid) == 1

    def test_invalid_relationship_rejected_in_batch(self, model, credit_targets):
        design_pk = credit_targets["roles"]["design"].pk
        claim = Claim.for_object(
            model,
            field_name="credit",
            value={
                "person": 99999,
                "role": design_pk,
                "exists": True,
            },
            claim_key=f"credit|person:99999|role:{design_pk}",
        )
        valid, rejected = validate_claims_batch([claim])
        assert rejected == 1
        assert len(valid) == 0

    def test_mixed_scalar_and_relationship(self, model, credit_targets):
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        good_scalar = Claim.for_object(model, field_name="name", value="Good Name")
        good_rel = Claim.for_object(
            model,
            field_name="credit",
            value={"person": pat_pk, "role": design_pk, "exists": True},
            claim_key=f"credit|person:{pat_pk}|role:{design_pk}",
        )
        bad_rel = Claim.for_object(
            model,
            field_name="theme",
            value={"theme": 99999, "exists": True},
            claim_key="theme|theme:99999",
        )
        valid, rejected = validate_claims_batch([good_scalar, good_rel, bad_rel])
        assert rejected == 1
        assert len(valid) == 2

    @pytest.mark.parametrize(
        "mode",
        [
            "wrong-subject",
            "missing-exists",
            "unknown-key",
            "default-claim-key",
        ],
    )
    def test_shape_rejection_propagates_through_batch(
        self, model, credit_targets, mode
    ):
        """One parametrized test pinning the batch-path glue for shape rejections.

        Each mode exercises a different rule in ``validate_single_relationship_claim``
        (wrong-subject, missing exists, unknown keys, non-canonical claim_key).
        Alongside each bad claim we include a *valid* companion claim, which
        pins the property that the batch loop continues past a rejection
        rather than aborting — the single-validator tests can't verify that,
        and the pre-existing FK-existence batch test exercises a different
        rejection path.
        """
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        good_claim_key = f"credit|person:{pat_pk}|role:{design_pk}"
        good_value = {"person": pat_pk, "role": design_pk, "exists": True}

        good = Claim.for_object(
            model, field_name="credit", value=good_value, claim_key=good_claim_key
        )

        if mode == "wrong-subject":
            # Route a "credit" claim at a Title, which isn't in credit.valid_subjects.
            from apps.catalog.models import Title

            title = Title.objects.create(name="T", slug="t")
            bad = Claim.for_object(
                title,
                field_name="credit",
                value=good_value,
                claim_key=good_claim_key,
            )
        elif mode == "missing-exists":
            bad = Claim.for_object(
                model,
                field_name="credit",
                value={"person": pat_pk, "role": design_pk},
                claim_key=good_claim_key,
            )
        elif mode == "unknown-key":
            bad = Claim.for_object(
                model,
                field_name="credit",
                value={**good_value, "bogus": 1},
                claim_key=good_claim_key,
            )
        elif mode == "default-claim-key":
            # Caller forgot to pass claim_key → defaulted to field_name.
            bad = Claim.for_object(
                model,
                field_name="credit",
                value=good_value,
                claim_key="credit",
            )
        else:
            raise AssertionError(f"unhandled mode {mode!r}")

        valid, rejected_count = validate_claims_batch([good, bad])

        assert rejected_count == 1
        # The malformed claim is absent from ``valid``, the good one is present.
        valid_ids = {id(c) for c in valid}
        assert id(bad) not in valid_ids
        assert id(good) in valid_ids


@pytest.mark.django_db
class TestValidateClaimsBatchContentTypeNarrowing:
    """Claims whose ``content_type`` points at a non-``ClaimControlledModel``
    are rejected at the ``ContentType.model_class()`` boundary.

    Two-claim shape is load-bearing: it confirms that the rejection path
    does NOT poison ``model_cache``/``fields_cache`` and short-circuit
    later iterations as if the ct_id were resolved.
    """

    def test_rejects_claims_for_non_ccm_content_type(self, caplog):
        import logging

        from django.contrib.contenttypes.models import ContentType

        from apps.core.models import License

        # License extends TimeStampedModel, not ClaimControlledModel.
        license_ct = ContentType.objects.get_for_model(License)

        bad_a = Claim(
            content_type_id=license_ct.pk,
            object_id=1,
            field_name="name",
            claim_key="",
            value="x",
        )
        bad_b = Claim(
            content_type_id=license_ct.pk,
            object_id=2,
            field_name="name",
            claim_key="",
            value="y",
        )

        with caplog.at_level(logging.WARNING, logger="apps.provenance.validation"):
            valid, rejected_count = validate_claims_batch([bad_a, bad_b])

        assert rejected_count == 2
        valid_ids = {id(c) for c in valid}
        assert id(bad_a) not in valid_ids
        assert id(bad_b) not in valid_ids
        non_ccm_warnings = [
            r for r in caplog.records if "non-claim-controlled" in r.getMessage()
        ]
        assert len(non_ccm_warnings) == 2


# ---------------------------------------------------------------------------
# validate_single_relationship_claim — shape-rejection rules
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateSingleRelationshipClaim:
    """Direct coverage of each shape-rejection rule in validator order.

    The batch-path integration tests below exercise the same rules through
    ``validate_claims_batch`` so both entry points are covered.
    """

    @pytest.fixture
    def model(self):
        return make_machine_model(name="Test", slug="test")

    @pytest.fixture
    def canonical(self, credit_targets):
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        return {
            "person_pk": pat_pk,
            "role_pk": design_pk,
            "value": {"person": pat_pk, "role": design_pk, "exists": True},
            "claim_key": f"credit|person:{pat_pk}|role:{design_pk}",
        }

    def _validate(self, **kwargs):
        from apps.provenance.validation import validate_single_relationship_claim

        return validate_single_relationship_claim(**kwargs)

    def test_valid_claim_passes(self, model, canonical):
        # Sanity baseline — if this ever fails the other rejection tests are
        # meaningless.
        self._validate(
            subject_model=MachineModel,
            field_name="credit",
            claim_key=canonical["claim_key"],
            value=canonical["value"],
        )

    def test_wrong_subject_rejected(self, canonical):
        with pytest.raises(ValidationError, match="not valid on Title"):
            self._validate(
                subject_model=Title,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=canonical["value"],
            )

    def test_non_dict_value_rejected(self):
        with pytest.raises(ValidationError, match="must be a dict"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key="credit",
                value="not a dict",
            )

    def test_missing_exists_rejected(self, canonical):
        value = {"person": canonical["person_pk"], "role": canonical["role_pk"]}
        with pytest.raises(ValidationError, match="missing required 'exists'"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=value,
            )

    def test_non_bool_exists_rejected(self, canonical):
        value = {**canonical["value"], "exists": "true"}
        with pytest.raises(ValidationError, match="'exists' must be bool"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=value,
            )

    def test_missing_required_key_rejected(self, canonical):
        value = {"person": canonical["person_pk"], "exists": True}
        with pytest.raises(ValidationError, match="missing required key 'role'"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=value,
            )

    def test_wrong_scalar_type_required_key_rejected(self, canonical):
        value = {**canonical["value"], "person": "not-an-int"}
        with pytest.raises(ValidationError, match="'person' must be int"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=value,
            )

    def test_bool_as_int_rejected(self, canonical):
        # `isinstance(True, int)` is True; the `type(v) is T` rule rejects it.
        value = {**canonical["value"], "person": True}
        with pytest.raises(ValidationError, match="'person' must be int"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=value,
            )

    def test_wrong_scalar_type_optional_key_rejected(self, credit_targets):
        # `gameplay_feature.count` is optional + nullable int.
        from apps.catalog.models import GameplayFeature

        gf = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        with pytest.raises(ValidationError, match="'count' must be int"):
            self._validate(
                subject_model=MachineModel,
                field_name="gameplay_feature",
                claim_key=f"gameplay_feature|gameplay_feature:{gf.pk}",
                value={"gameplay_feature": gf.pk, "count": "5", "exists": True},
            )

    def test_nullable_optional_accepts_none(self):
        from apps.catalog.models import GameplayFeature

        gf = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        self._validate(
            subject_model=MachineModel,
            field_name="gameplay_feature",
            claim_key=f"gameplay_feature|gameplay_feature:{gf.pk}",
            value={"gameplay_feature": gf.pk, "count": None, "exists": True},
        )

    def test_non_nullable_optional_rejects_none(self):
        # `media_attachment.is_primary` is optional, non-nullable bool.
        # Schema-only check — no DB row needed; the validator operates on
        # the (namespace, subject_model, claim_key, value) tuple.
        with pytest.raises(ValidationError, match="'is_primary' may not be null"):
            self._validate(
                subject_model=MachineModel,
                field_name="media_attachment",
                claim_key="media_attachment|media_asset:1",
                value={
                    "media_asset": 1,
                    "is_primary": None,
                    "exists": True,
                },
            )

    def test_unknown_key_rejected(self, canonical):
        value = {**canonical["value"], "bogus": 1}
        with pytest.raises(ValidationError, match="unknown keys"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=value,
            )

    def test_unknown_key_rejected_on_retraction(self, canonical):
        # Retractions aren't carved out from shape rules (only FK existence).
        value = {**canonical["value"], "exists": False, "bogus": 1}
        with pytest.raises(ValidationError, match="unknown keys"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=canonical["claim_key"],
                value=value,
            )

    def test_default_claim_key_rejected(self, canonical):
        # Caller passes no claim_key → assert_claim defaults to field_name;
        # the canonical form is the compound key.
        with pytest.raises(ValidationError, match="not canonical"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key="credit",
                value=canonical["value"],
            )

    def test_mismatched_claim_key_rejected(self, canonical):
        wrong = f"credit|person:99999|role:{canonical['role_pk']}"
        with pytest.raises(ValidationError, match="not canonical"):
            self._validate(
                subject_model=MachineModel,
                field_name="credit",
                claim_key=wrong,
                value=canonical["value"],
            )


# ---------------------------------------------------------------------------
# validate_single_relationship_claim — xor_groups + choices rules
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModelRelationshipClaimShape:
    """The target-ladder rules: member exclusivity (rule 7) and choices (rule 5).

    ``model_relationship`` is the only namespace with ``xor_groups`` and
    ``choices``, so its schema is where these rules are exercised. Schema-only
    checks — the referenced pks never hit the DB.
    """

    def _validate(self, value, claim_key=None):
        from apps.provenance.models import make_claim_key
        from apps.provenance.validation import validate_single_relationship_claim

        if claim_key is None:
            claim_key = make_claim_key(
                "model_relationship",
                target_machine=value.get("target_machine"),
                target_label=value.get("target_label"),
            )
        return validate_single_relationship_claim(
            subject_model=MachineModel,
            field_name="model_relationship",
            claim_key=claim_key,
            value=value,
        )

    def _value(self, machine=None, label="", **overrides):
        return {
            "target_machine": machine,
            "target_label": label,
            "relationship_type": "copy",
            "license_status": "unknown",
            "exists": True,
            **overrides,
        }

    def test_machine_target_passes(self):
        self._validate(self._value(machine=42))

    def test_label_target_passes(self):
        self._validate(self._value(label="several Gottlieb EM models"))

    def test_machine_plus_label_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            self._validate(self._value(machine=42, label="redundant"))

    def test_absent_target_rejected(self):
        """All-null ladder (label "" counts as absent) sets zero groups."""
        with pytest.raises(ValidationError, match="exactly one"):
            self._validate(self._value())

    def test_out_of_vocab_relationship_type_rejected(self):
        with pytest.raises(ValidationError, match="'relationship_type' must be one"):
            self._validate(self._value(machine=42, relationship_type="remake"))

    def test_out_of_vocab_license_status_rejected(self):
        with pytest.raises(ValidationError, match="'license_status' must be one"):
            self._validate(self._value(machine=42, license_status="disputed"))

    def test_missing_required_payload_rejected(self):
        value = self._value(machine=42)
        del value["license_status"]
        with pytest.raises(ValidationError, match="missing required key"):
            self._validate(value)

    def test_retraction_without_payload_passes(self):
        """Tombstones strip payload; required payload applies to positive
        claims only."""
        self._validate(
            {
                "target_machine": 42,
                "target_label": "",
                "exists": False,
            }
        )

    def test_null_label_rejected(self):
        """The literal member is not nullable — absence is the empty string."""
        with pytest.raises(ValidationError, match="'target_label' may not be null"):
            self._validate(self._value(machine=42, target_label=None))

    def test_missing_null_identity_part_rejected(self):
        """Nullable identity keys must still be present in the value dict."""
        value = self._value(machine=42)
        del value["target_machine"]
        with pytest.raises(
            ValidationError, match="missing required key 'target_machine'"
        ):
            self._validate(value)


# ---------------------------------------------------------------------------
# assert_claim — shape rejection end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssertClaimRelationshipShape:
    """``assert_claim`` routes RELATIONSHIP claims through the shape validator."""

    @pytest.fixture
    def model(self):
        return make_machine_model(name="Test", slug="test")

    @pytest.fixture
    def source(self):
        return make_ingest_source(
            name="Test Source", source_type="database", priority=50
        )

    def test_malformed_payload_on_extra_data_model_rejected(self, model, source):
        # Before the classifier change, a credit claim missing "exists" on a
        # model with extra_data would fall through to EXTRA and silently land.
        # Now it routes to RELATIONSHIP and the validator rejects it.
        with pytest.raises(ValidationError, match="missing required 'exists'"):
            make_claim(
                model,
                "credit",
                {"person": 1, "role": 1},  # no "exists"
                ingest_source=source,
                claim_key="credit|person:1|role:1",
            )

    def test_default_claim_key_rejected(self, model, source, credit_targets):
        pat_pk = credit_targets["persons"]["pat-lawlor"].pk
        design_pk = credit_targets["roles"]["design"].pk
        with pytest.raises(ValidationError, match="not canonical"):
            # No claim_key= → assert_claim defaults it to field_name.
            make_claim(
                model,
                "credit",
                {"person": pat_pk, "role": design_pk, "exists": True},
                ingest_source=source,
            )

    def test_wrong_subject_rejected(self, source):
        title = Title.objects.create(name="T", slug="t")
        with pytest.raises(ValidationError, match="not valid on Title"):
            make_claim(
                title,
                "credit",
                {"person": 1, "role": 1, "exists": True},
                ingest_source=source,
                claim_key="credit|person:1|role:1",
            )


# ---------------------------------------------------------------------------
# register_relationship_schema — invariants
# ---------------------------------------------------------------------------


class TestRegisterRelationshipSchemaGuards:
    """Registration-time invariants fail at startup, not at write time."""

    def test_non_required_identity_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        with pytest.raises(
            ImproperlyConfigured, match="identity keys must be required"
        ):
            register_relationship_schema(
                namespace="_test_bad_identity",
                value_keys=(
                    ValueKeySpec(
                        name="x",
                        scalar_type=int,
                        required=False,
                        identity="x",
                    ),
                ),
                valid_subjects={Theme},
            )
        # Pin "raise before insert" — a future refactor that inserts and
        # then validates would pass the exception assertion but pollute the
        # registry across tests.
        assert "_test_bad_identity" not in _relationship_schemas

    def test_collision_with_direct_field_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        # ``name`` is a concrete claim field on Theme — collision guard fires.
        existing = _relationship_schemas.get("name")
        with pytest.raises(ImproperlyConfigured, match="collides with a concrete"):
            register_relationship_schema(
                namespace="name",
                value_keys=(
                    ValueKeySpec(
                        name="x",
                        scalar_type=int,
                        required=True,
                        identity="x",
                    ),
                ),
                valid_subjects={Theme},
            )
        # Same "raise before insert" invariant. Compared against any
        # pre-existing entry (there shouldn't be one) to stay robust if a
        # future catalog namespace happens to be called "name".
        assert _relationship_schemas.get("name") == existing

    def test_display_key_on_non_identity_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        with pytest.raises(
            ImproperlyConfigured, match="display_key is only allowed on identity specs"
        ):
            register_relationship_schema(
                namespace="_test_display_key_non_identity",
                value_keys=(
                    ValueKeySpec(
                        name="x",
                        scalar_type=str,
                        required=False,
                        display_key="y",
                    ),
                    ValueKeySpec(name="y", scalar_type=str, required=False),
                ),
                valid_subjects={Theme},
            )
        assert "_test_display_key_non_identity" not in _relationship_schemas

    def test_display_key_dangling_target_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        with pytest.raises(ImproperlyConfigured, match="does not name a sibling spec"):
            register_relationship_schema(
                namespace="_test_display_key_dangling",
                value_keys=(
                    ValueKeySpec(
                        name="x",
                        scalar_type=str,
                        required=True,
                        identity="x",
                        display_key="nope",
                    ),
                ),
                valid_subjects={Theme},
            )
        assert "_test_display_key_dangling" not in _relationship_schemas

    def test_display_key_target_is_identity_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        with pytest.raises(ImproperlyConfigured, match="must be non-identity"):
            register_relationship_schema(
                namespace="_test_display_key_target_identity",
                value_keys=(
                    ValueKeySpec(
                        name="a",
                        scalar_type=str,
                        required=True,
                        identity="a",
                        display_key="b",
                    ),
                    ValueKeySpec(
                        name="b",
                        scalar_type=str,
                        required=True,
                        identity="b",
                    ),
                ),
                valid_subjects={Theme},
            )
        assert "_test_display_key_target_identity" not in _relationship_schemas

    def test_display_key_scalar_type_mismatch_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        with pytest.raises(ImproperlyConfigured, match="scalar_type"):
            register_relationship_schema(
                namespace="_test_display_key_type_mismatch",
                value_keys=(
                    ValueKeySpec(
                        name="x",
                        scalar_type=str,
                        required=True,
                        identity="x",
                        display_key="y",
                    ),
                    ValueKeySpec(name="y", scalar_type=int, required=False),
                ),
                valid_subjects={Theme},
            )
        assert "_test_display_key_type_mismatch" not in _relationship_schemas

    def test_display_key_target_with_fk_target_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            FkTarget,
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        with pytest.raises(ImproperlyConfigured, match="must not declare fk_target"):
            register_relationship_schema(
                namespace="_test_display_key_target_fk",
                value_keys=(
                    ValueKeySpec(
                        name="x",
                        scalar_type=str,
                        required=True,
                        identity="x",
                        display_key="y",
                    ),
                    ValueKeySpec(
                        name="y",
                        scalar_type=str,
                        required=False,
                        fk_target=FkTarget(Person, "slug"),
                    ),
                ),
                valid_subjects={Theme},
            )
        assert "_test_display_key_target_fk" not in _relationship_schemas

    def test_two_identity_specs_naming_same_display_key_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.provenance.validation import (
            ValueKeySpec,
            _relationship_schemas,
            register_relationship_schema,
        )

        with pytest.raises(ImproperlyConfigured, match="both declare display_key"):
            register_relationship_schema(
                namespace="_test_display_key_collision",
                value_keys=(
                    ValueKeySpec(
                        name="a",
                        scalar_type=str,
                        required=True,
                        identity="a",
                        display_key="shared",
                    ),
                    ValueKeySpec(
                        name="b",
                        scalar_type=str,
                        required=True,
                        identity="b",
                        display_key="shared",
                    ),
                    ValueKeySpec(name="shared", scalar_type=str, required=False),
                ),
                valid_subjects={Theme},
            )
        assert "_test_display_key_collision" not in _relationship_schemas


class TestGetDisplayOverride:
    """get_display_override truthy semantics match the resolver's historical
    ``val.get("alias_display") or alias_val`` expression."""

    def test_returns_override_when_truthy(self):
        from apps.provenance.validation import (
            get_display_override,
            get_relationship_schema,
        )

        schema = get_relationship_schema("person_alias")
        assert schema is not None
        override = get_display_override(
            {"alias_value": "the patster", "alias_display": "The Patster"},
            schema,
            "alias_value",
        )
        assert override == "The Patster"

    def test_returns_none_when_override_absent(self):
        from apps.provenance.validation import (
            get_display_override,
            get_relationship_schema,
        )

        schema = get_relationship_schema("person_alias")
        assert schema is not None
        override = get_display_override(
            {"alias_value": "the patster"}, schema, "alias_value"
        )
        assert override is None

    def test_returns_none_when_override_empty(self):
        # Empty strings fall through to canonical identity — preserves the
        # historical ``or`` semantics in the resolver.
        from apps.provenance.validation import (
            get_display_override,
            get_relationship_schema,
        )

        schema = get_relationship_schema("person_alias")
        assert schema is not None
        override = get_display_override(
            {"alias_value": "the patster", "alias_display": ""},
            schema,
            "alias_value",
        )
        assert override is None

    def test_returns_none_when_no_display_key_declared(self):
        # ``theme`` identity has no display_key — override is always None.
        from apps.provenance.validation import (
            get_display_override,
            get_relationship_schema,
        )

        schema = get_relationship_schema("theme")
        assert schema is not None
        override = get_display_override({"theme": 7}, schema, "theme")
        assert override is None
