import pytest
from django.apps import apps
from django.core.validators import MinValueValidator, RegexValidator
from django.db import IntegrityError, models, transaction

from apps.catalog.models import (
    CorporateEntity,
    Credit,
    CreditRole,
    Manufacturer,
    Person,
    System,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.core.validators import validate_no_mojibake
from apps.provenance.models import Claim, get_claim_fields
from apps.provenance.test_factories import make_claim, make_ingest_source


@pytest.fixture
def source(db):
    return make_ingest_source(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def editorial_source(db):
    return make_ingest_source(
        name="The Flip Editorial", source_type="editorial", priority=100
    )


@pytest.fixture
def manufacturer(db):
    return Manufacturer.objects.create(name="Williams", slug="williams")


@pytest.fixture
def corporate_entity(db, manufacturer):
    return CorporateEntity.objects.create(
        name="Williams Electronics",
        slug="williams-electronics",
        manufacturer=manufacturer,
    )


@pytest.fixture
def machine_model(db, corporate_entity):
    return make_machine_model(
        name="Medieval Madness",
        slug="medieval-madness",
        corporate_entity=corporate_entity,
        year=1997,
    )


@pytest.fixture
def person(db):
    return Person.objects.create(name="Brian Eddy", slug="brian-eddy")


# --- Source ---


class TestSource:
    def test_auto_slug(self, source):
        assert source.slug == "ipdb"

    def test_str(self, source):
        assert str(source) == "IPDB"

    def test_unique_name(self, db, source):
        with pytest.raises(IntegrityError):
            make_ingest_source(name="IPDB")


# --- Manufacturer ---


class TestManufacturer:
    def test_str(self, manufacturer):
        assert str(manufacturer) == "Williams"


# --- CorporateEntity ---


class TestCorporateEntity:
    def test_create(self, manufacturer):
        entity = CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Manufacturing Company",
            slug="williams-mfg",
            year_start=1943,
            year_end=1985,
        )
        assert entity.manufacturer == manufacturer

    def test_str_with_years(self, manufacturer):
        entity = CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Manufacturing Company",
            slug="williams-mfg",
            year_start=1943,
            year_end=1985,
        )
        assert "Williams Manufacturing Company" in str(entity)
        assert "1943" in str(entity)
        assert "1985" in str(entity)

    def test_str_without_years(self, manufacturer):
        entity = CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Manufacturing Company",
            slug="williams-mfg",
        )
        assert str(entity) == "Williams Manufacturing Company"

    def test_multiple_entities_per_manufacturer(self, manufacturer):
        CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Manufacturing Company",
            slug="williams-mfg",
            year_start=1943,
            year_end=1985,
        )
        CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Electronics",
            slug="williams-elec",
            year_start=1985,
            year_end=1999,
        )
        assert manufacturer.entities.count() == 2


# --- System ---


class TestSystem:
    """Verify System.manufacturer is required at the DB level."""

    def test_manufacturer_required(self, db):
        with pytest.raises(IntegrityError), transaction.atomic():
            System.objects.create(name="WPC-95", slug="wpc-95")

    def test_explicit_null_manufacturer_rejected(self, db):
        with pytest.raises(IntegrityError), transaction.atomic():
            # Deliberate type violation to assert the DB rejects NULL.
            System.objects.create(name="WPC-95", slug="wpc-95", manufacturer=None)  # type: ignore[misc]


# --- MachineModel ---


class TestMachineModel:
    def test_str(self, machine_model):
        assert "Medieval Madness" in str(machine_model)
        assert "Williams Electronics" in str(machine_model)
        assert "1997" in str(machine_model)


# --- Person ---


class TestPerson:
    def test_str(self, person):
        assert str(person) == "Brian Eddy"


# --- Slug enforcement ---


class TestCatalogSlugEnforcement:
    """Verify that the DB CHECK constraint rejects empty slugs."""

    def test_empty_slug_rejected(self, db):
        with pytest.raises(IntegrityError):
            Manufacturer.objects.create(name="Test", slug="")

    def test_missing_slug_rejected(self, db):
        """SlugField defaults to '' when not provided — CHECK catches it."""
        with pytest.raises(IntegrityError):
            Manufacturer.objects.create(name="Test")


# --- Credit ---


class TestCredit:
    def test_create(self, machine_model, person, credit_roles):
        role = CreditRole.objects.get(slug="design")
        credit = Credit.objects.create(model=machine_model, person=person, role=role)
        assert "Brian Eddy" in str(credit)
        assert "Design" in str(credit)

    def test_unique_constraint(self, machine_model, person, credit_roles):
        role = CreditRole.objects.get(slug="design")
        Credit.objects.create(model=machine_model, person=person, role=role)
        with pytest.raises(IntegrityError):
            Credit.objects.create(model=machine_model, person=person, role=role)

    def test_different_roles_ok(self, machine_model, person, credit_roles):
        design = CreditRole.objects.get(slug="design")
        concept = CreditRole.objects.get(slug="concept")
        Credit.objects.create(model=machine_model, person=person, role=design)
        Credit.objects.create(model=machine_model, person=person, role=concept)
        assert machine_model.credits.count() == 2


# --- Claim ---


class TestClaim:
    def test_assert_claim_creates(self, machine_model, source):
        claim = make_claim(
            machine_model, "name", "Medieval Madness", ingest_source=source
        )
        assert claim.is_active is True
        assert claim.value == "Medieval Madness"

    def test_assert_claim_supersedes(self, machine_model, source):
        c1 = make_claim(machine_model, "year", 1997, ingest_source=source)
        c2 = make_claim(machine_model, "year", 1998, ingest_source=source)
        c1.refresh_from_db()
        assert c1.is_active is False
        assert c2.is_active is True

    def test_assert_claim_different_sources_coexist(
        self, machine_model, source, editorial_source
    ):
        c1 = make_claim(machine_model, "year", 1997, ingest_source=source)
        c2 = make_claim(machine_model, "year", 1997, ingest_source=editorial_source)
        c1.refresh_from_db()
        assert c1.is_active is True
        assert c2.is_active is True

    def test_unique_active_constraint(self, machine_model, source):
        from django.contrib.contenttypes.models import ContentType

        first = make_claim(machine_model, "name", "V1", ingest_source=source)
        ct = ContentType.objects.get_for_model(machine_model)
        # Direct create (bypassing the dedupe primitive) of a second active claim
        # for the same author+claim_key should violate the unique-active index.
        # actor + changeset are NOT NULL, so reuse the first claim's changeset.
        with pytest.raises(IntegrityError):
            Claim.objects.create(
                content_type=ct,
                object_id=machine_model.pk,
                actor=source.actor,
                changeset=first.changeset,
                field_name="name",
                claim_key="name",
                value="V2",
                is_active=True,
            )

    def test_str(self, machine_model, source):
        claim = make_claim(machine_model, "year", 1997, ingest_source=source)
        assert "IPDB" in str(claim)
        assert "year" in str(claim)


# --- Field validator enforcement ---


class TestFieldValidatorCoverage:
    """Verify that catalog model fields carry the validators that
    validate_claim_value() depends on.

    These are structural/metadata tests — they check field definitions,
    not runtime behaviour. The companion integration tests in
    provenance/tests/test_validation.py verify that validate_claim_value()
    rejects invalid data for these fields.
    """

    @staticmethod
    def _catalog_models():
        return list(apps.get_app_config("catalog").get_models())

    @staticmethod
    def _has_claims_relation(model):
        """True if the model has a ``claims`` GenericRelation (receives claims)."""
        return any(
            f.name == "claims" and not getattr(f, "concrete", False)
            for f in model._meta.get_fields()
        )

    def test_text_fields_have_mojibake_validator(self):
        """Every claim-controlled CharField/TextField on a claims-bearing model
        must have validate_no_mojibake (or an equivalent format validator).

        Only checks models with a ``claims`` GenericRelation, since
        ``validate_claim_value()`` only runs on those models.
        Skips SlugField (Django's slug regex), URLField (built-in URLValidator),
        and fields with a RegexValidator (stricter than mojibake).
        """
        missing = []
        for model in self._catalog_models():
            if not self._has_claims_relation(model):
                continue
            claim_fields = get_claim_fields(model)
            for f in model._meta.get_fields():
                if not getattr(f, "concrete", False):
                    continue
                if f.name not in claim_fields:
                    continue
                if not isinstance(f, (models.CharField, models.TextField)):
                    continue
                if isinstance(f, (models.SlugField, models.URLField)):
                    continue
                # Fields with choices accept a fixed value set — mojibake
                # is impossible because the input is constrained.
                if f.choices:
                    continue
                has_mojibake = validate_no_mojibake in f.validators
                has_regex = any(isinstance(v, RegexValidator) for v in f.validators)
                if not (has_mojibake or has_regex):
                    missing.append(f"{model.__name__}.{f.name}")
        assert missing == [], (
            f"Claim-controlled text fields missing validate_no_mojibake: {missing}"
        )

    def test_nullable_unique_positive_int_fields_have_min_validator(self):
        """Every nullable unique PositiveIntegerField (cross-reference ID)
        on a claims-bearing model must have MinValueValidator(1).
        """
        missing = []
        for model in self._catalog_models():
            if not self._has_claims_relation(model):
                continue
            claim_fields = get_claim_fields(model)
            for f in model._meta.get_fields():
                if not getattr(f, "concrete", False):
                    continue
                if f.name not in claim_fields:
                    continue
                if not isinstance(f, models.PositiveIntegerField):
                    continue
                if not (f.null and getattr(f, "unique", False)):
                    continue
                has_min = any(
                    isinstance(v, MinValueValidator) and v.limit_value >= 1
                    for v in f.validators
                )
                if not has_min:
                    missing.append(f"{model.__name__}.{f.name}")
        assert missing == [], (
            f"Nullable unique PositiveIntegerField fields missing MinValueValidator(1): {missing}"
        )

    def test_wikidata_id_fields_have_regex_validator(self):
        """Every wikidata_id field must have a RegexValidator for Q-number format."""
        missing = []
        for model in self._catalog_models():
            for f in model._meta.get_fields():
                if not isinstance(f, models.Field):
                    continue
                if not getattr(f, "concrete", False):
                    continue
                if f.name != "wikidata_id":
                    continue
                has_regex = any(isinstance(v, RegexValidator) for v in f.validators)
                if not has_regex:
                    missing.append(f"{model.__name__}.{f.name}")
        assert missing == [], f"wikidata_id fields missing RegexValidator: {missing}"
