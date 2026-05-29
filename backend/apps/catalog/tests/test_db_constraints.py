"""Tests for database-level CHECK constraints on catalog and provenance models.

Verifies that constraints enforce ranges, cross-field invariants, non-blank
rules, and self-referential anti-cycles at the DB level — independent of
Python validators.
"""

import pytest
from django.db import IntegrityError, connection

from apps.catalog.models import (
    CorporateEntity,
    DisplaySubtype,
    DisplayType,
    Franchise,
    Location,
    MachineModel,
    Manufacturer,
    Person,
    PersonAlias,
    Series,
    TechnologyGeneration,
    TechnologySubgeneration,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Claim, IngestRun, Source
from apps.provenance.test_factories import user_changeset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_update(model, pk, **fields):
    """Bypass ORM validation with a raw SQL UPDATE."""
    table = model._meta.db_table
    sets = ", ".join(f"{col} = %s" for col in fields)
    with connection.cursor() as cur:
        # Table/column identifiers come from test-controlled ORM metadata; values parameterized.
        sql = f"UPDATE {table} SET {sets} WHERE id = %s"  # noqa: S608
        cur.execute(sql, [*fields.values(), pk])


# ---------------------------------------------------------------------------
# Non-blank constraints
# ---------------------------------------------------------------------------


class TestNonBlankConstraints:
    def test_manufacturer_empty_name_rejected(self, db):
        with pytest.raises(IntegrityError):
            Manufacturer.objects.create(name="", slug="test")

    def test_person_alias_empty_value_rejected(self, db):
        person = Person.objects.create(name="Test", slug="test-person")
        with pytest.raises(IntegrityError):
            PersonAlias.objects.create(person=person, value="")

    def test_location_empty_path_rejected(self, db):
        with pytest.raises(IntegrityError):
            Location.objects.create(location_path="", slug="test", name="Test")

    def test_machine_model_title_null_rejected(self, db):
        """MachineModel.title is NOT NULL — creating without one fails at the DB."""
        with pytest.raises(IntegrityError):
            # Deliberate type violation to assert the DB rejects NULL.
            MachineModel.objects.create(name="No Title", slug="no-title", title=None)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Uniqueness constraints
# ---------------------------------------------------------------------------


class TestUniqueNameConstraints:
    def test_duplicate_series_name_rejected(self, db):
        Series.objects.create(name="Eight Ball", slug="eight-ball")
        with pytest.raises(IntegrityError):
            Series.objects.create(name="Eight Ball", slug="eight-ball-2")

    def test_duplicate_franchise_name_rejected(self, db):
        Franchise.objects.create(name="Indiana Jones", slug="indiana-jones")
        with pytest.raises(IntegrityError):
            Franchise.objects.create(name="Indiana Jones", slug="indiana-jones-2")

    def test_duplicate_technology_subgeneration_name_rejected(self, db):
        gen = TechnologyGeneration.objects.create(name="Solid State", slug="ss")
        TechnologySubgeneration.objects.create(
            name="Discrete Logic", slug="discrete-logic", technology_generation=gen
        )
        with pytest.raises(IntegrityError):
            TechnologySubgeneration.objects.create(
                name="Discrete Logic",
                slug="discrete-logic-2",
                technology_generation=gen,
            )

    def test_duplicate_display_subtype_name_rejected(self, db):
        dt = DisplayType.objects.create(name="LCD", slug="lcd")
        DisplaySubtype.objects.create(
            name="Standard LCD", slug="standard-lcd", display_type=dt
        )
        with pytest.raises(IntegrityError):
            DisplaySubtype.objects.create(
                name="Standard LCD", slug="standard-lcd-2", display_type=dt
            )


class TestLocationSiblingSlugUniqueness:
    def test_duplicate_root_slug_rejected(self, db):
        Location.objects.create(location_path="usa", slug="usa", name="USA")
        with pytest.raises(IntegrityError):
            Location.objects.create(location_path="usa-2", slug="usa", name="USA Two")

    def test_duplicate_sibling_slug_rejected(self, db):
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        Location.objects.create(
            location_path="usa/chicago",
            slug="chicago",
            name="Chicago",
            parent=usa,
        )
        with pytest.raises(IntegrityError):
            Location.objects.create(
                location_path="usa/chicago-2",
                slug="chicago",
                name="Chicago Two",
                parent=usa,
            )

    def test_same_slug_under_different_parents_allowed(self, db):
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        canada = Location.objects.create(
            location_path="canada", slug="canada", name="Canada"
        )
        Location.objects.create(
            location_path="usa/portland",
            slug="portland",
            name="Portland",
            parent=usa,
        )
        Location.objects.create(
            location_path="canada/portland",
            slug="portland",
            name="Portland",
            parent=canada,
        )

    def test_same_slug_at_root_and_under_parent_allowed(self, db):
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        Location.objects.create(
            location_path="usa/usa", slug="usa", name="Usa City", parent=usa
        )


class TestLocationSiblingNameUniqueness:
    def test_duplicate_root_name_rejected(self, db):
        Location.objects.create(location_path="usa", slug="usa", name="USA")
        with pytest.raises(IntegrityError):
            Location.objects.create(location_path="usa-2", slug="usa-2", name="USA")

    def test_duplicate_sibling_name_rejected(self, db):
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        Location.objects.create(
            location_path="usa/chicago",
            slug="chicago",
            name="Chicago",
            parent=usa,
        )
        with pytest.raises(IntegrityError):
            Location.objects.create(
                location_path="usa/chicago-2",
                slug="chicago-2",
                name="Chicago",
                parent=usa,
            )

    def test_same_name_under_different_parents_allowed(self, db):
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        canada = Location.objects.create(
            location_path="canada", slug="canada", name="Canada"
        )
        Location.objects.create(
            location_path="usa/portland",
            slug="portland",
            name="Portland",
            parent=usa,
        )
        Location.objects.create(
            location_path="canada/portland",
            slug="portland",
            name="Portland",
            parent=canada,
        )

    def test_same_name_at_root_and_under_parent_allowed(self, db):
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        Location.objects.create(
            location_path="usa/usa-city", slug="usa-city", name="USA", parent=usa
        )

    def test_blank_name_rejected(self, db):
        with pytest.raises(IntegrityError):
            Location.objects.create(location_path="usa", slug="usa", name="")

    def test_name_uniqueness_is_case_insensitive(self, db):
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        Location.objects.create(
            location_path="usa/chicago",
            slug="chicago",
            name="Chicago",
            parent=usa,
        )
        with pytest.raises(IntegrityError):
            Location.objects.create(
                location_path="usa/chicago-2",
                slug="chicago-2",
                name="chicago",
                parent=usa,
            )


# ---------------------------------------------------------------------------
# Range constraints
# ---------------------------------------------------------------------------


class TestRangeConstraints:
    @pytest.fixture
    def machine(self, db):
        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        ce = CorporateEntity.objects.create(
            name="Williams Electronics", slug="williams-electronics", manufacturer=mfr
        )
        return make_machine_model(
            name="Test", slug="test-machine", corporate_entity=ce, year=1992
        )

    def test_year_above_max_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, year=2101)

    def test_year_below_min_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, year=1799)

    def test_month_zero_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, month=0)

    def test_month_thirteen_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, month=13)

    def test_valid_range_accepted(self, machine):
        _raw_update(MachineModel, machine.pk, year=1800, month=12)
        machine.refresh_from_db()
        assert machine.year == 1800
        assert machine.month == 12

    def test_person_birth_day_above_max_rejected(self, db):
        person = Person.objects.create(
            name="Test", slug="test-person", birth_year=1950, birth_month=6
        )
        with pytest.raises(IntegrityError):
            _raw_update(Person, person.pk, birth_day=32)


# ---------------------------------------------------------------------------
# Nullable string ID constraints (NULL or non-empty)
# ---------------------------------------------------------------------------


class TestNullableIdConstraints:
    def test_machine_model_opdb_id_empty_string_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(name="Test", slug="test-mm", corporate_entity=ce)
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, mm.pk, opdb_id="")

    def test_machine_model_pinside_id_empty_string_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(name="Test", slug="test-mm", corporate_entity=ce)
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, mm.pk, pinside_id="")

    def test_machine_model_opdb_id_null_accepted(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(
            name="Test", slug="test-mm", corporate_entity=ce, opdb_id="ABC"
        )
        _raw_update(MachineModel, mm.pk, opdb_id=None)
        mm.refresh_from_db()
        assert mm.opdb_id is None

    def test_title_opdb_id_empty_string_rejected(self, db):
        from apps.catalog.models import Title

        t = Title.objects.create(name="Test", slug="test-title")
        with pytest.raises(IntegrityError):
            _raw_update(Title, t.pk, opdb_id="")

    def test_person_wikidata_id_empty_string_rejected(self, db):
        p = Person.objects.create(name="Test", slug="test-person")
        with pytest.raises(IntegrityError):
            _raw_update(Person, p.pk, wikidata_id="")

    def test_manufacturer_wikidata_id_empty_string_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        with pytest.raises(IntegrityError):
            _raw_update(Manufacturer, mfr.pk, wikidata_id="")


# ---------------------------------------------------------------------------
# Cross-field constraints
# ---------------------------------------------------------------------------


class TestCrossFieldConstraints:
    def test_corporate_entity_year_start_after_end_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        with pytest.raises(IntegrityError):
            CorporateEntity.objects.create(
                name="Test Corp",
                slug="test-corp",
                manufacturer=mfr,
                year_start=2000,
                year_end=1900,
            )

    def test_corporate_entity_valid_year_range_accepted(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp",
            slug="test-corp",
            manufacturer=mfr,
            year_start=1900,
            year_end=2000,
        )
        assert ce.pk is not None

    def test_person_birth_month_without_year_rejected(self, db):
        with pytest.raises(IntegrityError):
            Person.objects.create(
                name="Test", slug="test-person", birth_month=6, birth_year=None
            )

    def test_person_birth_month_with_year_accepted(self, db):
        p = Person.objects.create(
            name="Test", slug="test-person", birth_year=1950, birth_month=6
        )
        assert p.pk is not None

    def test_person_death_day_without_month_rejected(self, db):
        with pytest.raises(IntegrityError):
            Person.objects.create(
                name="Test",
                slug="test-person",
                death_year=2000,
                death_day=15,
                death_month=None,
            )

    def test_person_birth_before_death_accepted(self, db):
        p = Person.objects.create(
            name="Test", slug="test-person", birth_year=1950, death_year=2020
        )
        assert p.pk is not None

    def test_person_birth_after_death_rejected(self, db):
        with pytest.raises(IntegrityError):
            Person.objects.create(
                name="Test", slug="test-person", birth_year=2020, death_year=1950
            )

    def test_machine_model_month_without_year_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        with pytest.raises(IntegrityError):
            make_machine_model(
                name="Test", slug="test-mm", corporate_entity=ce, month=6, year=None
            )


# ---------------------------------------------------------------------------
# Self-referential anti-cycle constraints
# ---------------------------------------------------------------------------


class TestSelfRefConstraints:
    def test_machine_model_variant_of_self_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(name="Test", slug="test-mm", corporate_entity=ce)
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, mm.pk, variant_of_id=mm.pk)

    def test_machine_model_converted_from_self_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(name="Test", slug="test-mm", corporate_entity=ce)
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, mm.pk, converted_from_id=mm.pk)

    def test_machine_model_remake_of_self_rejected(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(name="Test", slug="test-mm", corporate_entity=ce)
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, mm.pk, remake_of_id=mm.pk)

    def test_location_parent_self_rejected(self, db):
        loc = Location.objects.create(location_path="usa", slug="usa", name="USA")
        with pytest.raises(IntegrityError):
            _raw_update(Location, loc.pk, parent_id=loc.pk)


# ---------------------------------------------------------------------------
# Provenance cross-field constraints
# ---------------------------------------------------------------------------


class TestProvenanceConstraints:
    def test_claim_retracted_while_active_rejected(self, user):
        source = Source.objects.create(name="Test", source_type="database")
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        claim = Claim.objects.assert_claim(mfr, "name", "Test", source=source)

        cs = user_changeset(user)
        with pytest.raises(IntegrityError):
            _raw_update(Claim, claim.pk, retracted_by_changeset_id=cs.pk)

    def test_ingest_run_finished_while_running_rejected(self, db):
        from django.utils import timezone

        source = Source.objects.create(name="Test", source_type="database")
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        assert run.status == "running"
        with pytest.raises(IntegrityError):
            _raw_update(IngestRun, run.pk, finished_at=timezone.now())

    def test_ingest_run_finished_when_success_accepted(self, db):
        from django.utils import timezone

        source = Source.objects.create(name="Test", source_type="database")
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        now = timezone.now()
        _raw_update(IngestRun, run.pk, status="success", finished_at=now)
        run.refresh_from_db()
        assert run.status == "success"
        assert run.finished_at is not None

    def test_ingest_run_success_without_finished_at_rejected(self, db):
        """Terminal status requires finished_at to be set."""
        source = Source.objects.create(name="Test", source_type="database")
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        with pytest.raises(IntegrityError):
            _raw_update(IngestRun, run.pk, status="success")

    def test_source_invalid_type_rejected(self, db):
        with pytest.raises(IntegrityError):
            Source.objects.create(name="Bad", source_type="invalid")


# ---------------------------------------------------------------------------
# validate_check_constraints() integration
# ---------------------------------------------------------------------------


class TestValidateCheckConstraints:
    """Verify the resolver catches cross-field violations in Python
    (clean ValidationError) rather than letting them hit the DB
    (raw IntegrityError).
    """

    def test_resolver_catches_month_without_year(self, db):
        """Cross-field violation during resolution raises ValidationError."""
        from django.core.exceptions import ValidationError

        source = Source.objects.create(name="Test", source_type="database")
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(
            name="Test Machine", slug="test-mm", corporate_entity=ce, year=1992
        )
        Claim.objects.assert_claim(mm, "name", "Test Machine", source=source)
        Claim.objects.assert_claim(mm, "month", 6, source=source)
        # No year claim — resolver will reset year to None, month stays 6.
        # validate_check_constraints should catch this before save().
        from apps.catalog.resolve import resolve_model

        with pytest.raises(ValidationError, match="month requires year"):
            resolve_model(mm)

    def test_execute_claims_returns_422_on_cross_field_violation(self, user):
        """PATCH path converts ValidationError to HttpError 422."""
        from django.test import Client

        source = Source.objects.create(
            name="Test", slug="test-src", source_type="database", priority=10
        )
        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        ce = CorporateEntity.objects.create(
            name="Williams Corp",
            slug="williams-corp",
            manufacturer=mfr,
            year_start=1985,
            year_end=2000,
        )
        Claim.objects.assert_claim(ce, "name", "Williams Corp", source=source)
        Claim.objects.assert_claim(ce, "year_start", 1985, source=source)
        Claim.objects.assert_claim(ce, "year_end", 2000, source=source)

        client = Client()
        client.force_login(user)
        # Set year_end < year_start — should get clean 422, not 500
        resp = client.patch(
            f"/api/corporate-entities/{ce.slug}/claims/",
            data='{"fields": {"year_end": 1900}}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert "year_start must be <= year_end" in resp.json()["detail"]["message"]
