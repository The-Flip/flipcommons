"""Tests for database-level CHECK constraints on catalog and provenance models.

Verifies that constraints enforce ranges, cross-field invariants, non-blank
rules, and self-referential anti-cycles at the DB level — independent of
Python validators.
"""

import pytest
from django.db import IntegrityError, connection
from django.db.models import ProtectedError

from apps.catalog.models import (
    UNCLASSIFIED_SLUG,
    Cabinet,
    CorporateEntity,
    Credit,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    Franchise,
    GameFormat,
    Location,
    MachineModel,
    Manufacturer,
    ModelExportMarket,
    ModelRelationship,
    Person,
    PersonAlias,
    ProductionStatus,
    RelationshipType,
    Series,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    ThemeParent,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Claim, IngestRun, Source
from apps.provenance.test_factories import make_claim, user_changeset

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
            name="Test", slug="test-machine", corporate_entity=ce, production_year=1992
        )

    def test_production_year_above_max_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, production_year=2101)

    def test_production_year_below_min_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, production_year=1799)

    def test_production_month_zero_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, production_month=0)

    def test_production_month_thirteen_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, production_month=13)

    def test_project_year_above_max_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, project_year=2101)

    def test_project_year_below_min_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, project_year=1799)

    def test_project_month_zero_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, project_year=1990, project_month=0)

    def test_project_month_thirteen_rejected(self, machine):
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, machine.pk, project_year=1990, project_month=13)

    def test_valid_range_accepted(self, machine):
        _raw_update(MachineModel, machine.pk, production_year=1800, production_month=12)
        machine.refresh_from_db()
        assert machine.production_year == 1800
        assert machine.production_month == 12

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
# Reserved slug on the sparse vocabularies
# ---------------------------------------------------------------------------


SPARSE_VOCABULARIES = [Cabinet, GameFormat, ProductionStatus]


@pytest.mark.parametrize(
    "model", SPARSE_VOCABULARIES, ids=[m.__name__ for m in SPARSE_VOCABULARIES]
)
class TestReservedUnclassifiedSlug:
    """The filtering API reads ``unclassified`` as "this field is unset", so a
    vocabulary row carrying that slug would be unreachable by filter."""

    def test_reserved_slug_rejected(self, db, model):
        with pytest.raises(IntegrityError):
            model.objects.create(name="Unclassified", slug=UNCLASSIFIED_SLUG)

    def test_reserved_slug_rejected_in_bulk_create(self, db, model):
        """The bulk patch-ingest path never runs model validation, so the
        constraint has to hold for a write that skips ``save()`` entirely."""
        with pytest.raises(IntegrityError):
            model.objects.bulk_create(
                [
                    model(name="Real Row", slug="real-row"),
                    model(name="Unclassified", slug=UNCLASSIFIED_SLUG),
                ]
            )

    def test_slug_containing_the_reserved_word_accepted(self, db, model):
        """Only the exact slug is reserved — nothing shadows a longer one."""
        row = model.objects.create(name="Unclassified Other", slug="unclassified-other")
        assert row.pk is not None


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

    @pytest.fixture
    def corporate_entity(self, db):
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        return CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )

    def test_machine_model_production_month_without_year_rejected(
        self, corporate_entity
    ):
        with pytest.raises(IntegrityError):
            make_machine_model(
                name="Test",
                slug="test-mm",
                corporate_entity=corporate_entity,
                production_month=6,
                production_year=None,
            )

    def test_machine_model_project_month_without_year_rejected(self, corporate_entity):
        with pytest.raises(IntegrityError):
            make_machine_model(
                name="Test",
                slug="test-mm",
                corporate_entity=corporate_entity,
                project_month=6,
                project_year=None,
            )

    def test_project_year_after_production_year_rejected(self, corporate_entity):
        with pytest.raises(IntegrityError):
            make_machine_model(
                name="Test",
                slug="test-mm",
                corporate_entity=corporate_entity,
                production_year=1992,
                project_year=1993,
            )

    def test_project_month_after_production_month_same_year_rejected(
        self, corporate_entity
    ):
        with pytest.raises(IntegrityError):
            make_machine_model(
                name="Test",
                slug="test-mm",
                corporate_entity=corporate_entity,
                production_year=1992,
                production_month=3,
                project_year=1992,
                project_month=5,
            )

    def test_project_before_production_accepted(self, corporate_entity):
        m = make_machine_model(
            name="Test",
            slug="test-mm",
            corporate_entity=corporate_entity,
            production_year=1992,
            production_month=3,
            project_year=1991,
            project_month=11,
        )
        assert m.pk is not None

    def test_project_null_month_gets_benefit_of_the_doubt(self, corporate_entity):
        # project "1992" vs production "1992-03": the missing month is
        # treated as unknown, not as December.
        m = make_machine_model(
            name="Test",
            slug="test-mm",
            corporate_entity=corporate_entity,
            production_year=1992,
            production_month=3,
            project_year=1992,
        )
        assert m.pk is not None


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
        claim = make_claim(mfr, "name", "Test", ingest_source=source)

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
            name="Test Machine",
            slug="test-mm",
            corporate_entity=ce,
            production_year=1992,
        )
        make_claim(mm, "name", "Test Machine", ingest_source=source)
        make_claim(mm, "production_month", 6, ingest_source=source)
        # No year claim — resolver will reset production_year to None while
        # production_month stays 6. validate_check_constraints should catch
        # this before save().
        from apps.provenance.resolution import resolve_after_mutation

        with pytest.raises(
            ValidationError, match="production_month requires production_year"
        ):
            resolve_after_mutation(mm)

    def test_resolver_catches_project_after_production(self, db):
        """Independently-won project and production claims that violate the
        ordering rule fail as a clean ValidationError, not an IntegrityError
        at ``bulk_update``."""
        from django.core.exceptions import ValidationError

        source = Source.objects.create(name="Test", source_type="database")
        mfr = Manufacturer.objects.create(name="Test", slug="test-mfr")
        ce = CorporateEntity.objects.create(
            name="Test Corp", slug="test-corp", manufacturer=mfr
        )
        mm = make_machine_model(
            name="Test Machine", slug="test-mm", corporate_entity=ce
        )
        make_claim(mm, "name", "Test Machine", ingest_source=source)
        make_claim(mm, "production_year", 1992, ingest_source=source)
        make_claim(mm, "project_year", 1993, ingest_source=source)
        from apps.provenance.resolution import resolve_after_mutation

        with pytest.raises(
            ValidationError, match="project date cannot be after production date"
        ):
            resolve_after_mutation(mm)

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
        make_claim(ce, "name", "Williams Corp", ingest_source=source)
        make_claim(ce, "year_start", 1985, ingest_source=source)
        make_claim(ce, "year_end", 2000, ingest_source=source)

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


# ---------------------------------------------------------------------------
# Credit model/series XOR + per-branch uniqueness
# ---------------------------------------------------------------------------


class TestCreditXorConstraint:
    """The ``credit`` namespace's ``XorSubject`` is backed by DB constraints.

    The ``check_claim_through_models`` system check deliberately does NOT verify
    the ``model XOR series`` ``CheckConstraint`` (that would mean walking a ``Q``
    tree or hardcoding a catalog constraint name), so the XOR semantic and the
    two conditional UCs are pinned by behavior here instead.
    """

    @pytest.fixture
    def parts(self, db):
        person = Person.objects.create(name="Pat Lawlor", slug="xor-pat-lawlor")
        role = CreditRole.objects.create(name="Design", slug="xor-design")
        machine = make_machine_model(name="Medieval Madness", slug="xor-mm")
        series = Series.objects.create(name="World Cup Soccer", slug="xor-wcs")
        return person, role, machine, series

    def test_neither_subject_rejected(self, parts):
        person, role, _machine, _series = parts
        with pytest.raises(IntegrityError):
            Credit.objects.create(model=None, series=None, person=person, role=role)

    def test_both_subjects_rejected(self, parts):
        person, role, machine, series = parts
        with pytest.raises(IntegrityError):
            Credit.objects.create(
                model=machine, series=series, person=person, role=role
            )

    def test_model_only_accepted(self, parts):
        person, role, machine, _series = parts
        credit = Credit.objects.create(model=machine, person=person, role=role)
        assert credit.pk is not None

    def test_series_only_accepted(self, parts):
        person, role, _machine, series = parts
        credit = Credit.objects.create(series=series, person=person, role=role)
        assert credit.pk is not None

    def test_duplicate_model_branch_rejected(self, parts):
        person, role, machine, _series = parts
        Credit.objects.create(model=machine, person=person, role=role)
        with pytest.raises(IntegrityError):
            Credit.objects.create(model=machine, person=person, role=role)

    def test_duplicate_series_branch_rejected(self, parts):
        person, role, _machine, series = parts
        Credit.objects.create(series=series, person=person, role=role)
        with pytest.raises(IntegrityError):
            Credit.objects.create(series=series, person=person, role=role)


# ---------------------------------------------------------------------------
# Promoted parent through-models — CASCADE + (from, to) uniqueness
# ---------------------------------------------------------------------------


class TestParentThroughConstraints:
    """``ThemeParent`` preserves the delete + uniqueness behavior of the M2M.

    ``on_delete=CASCADE`` does no DDL (Django enforces it in the ORM collector,
    not a DB ``ON DELETE`` clause), so it is justified solely by delete behavior:
    deleting either endpoint reaps the edge and leaves the other endpoint. The
    ``unique_together`` over the two FKs is the auto-M2M's unnamed unique index.
    """

    @pytest.fixture
    def edge(self, db):
        child = Theme.objects.create(name="2-Ball Multiball", slug="tp-child")
        parent = Theme.objects.create(name="Multiball", slug="tp-parent")
        ThemeParent.objects.create(from_theme=child, to_theme=parent)
        return child, parent

    def test_duplicate_edge_rejected(self, edge):
        child, parent = edge
        with pytest.raises(IntegrityError):
            ThemeParent.objects.create(from_theme=child, to_theme=parent)

    def test_deleting_child_reaps_edge_keeps_parent(self, edge):
        child, parent = edge
        child.delete()
        assert not ThemeParent.objects.filter(to_theme=parent).exists()
        assert Theme.objects.filter(pk=parent.pk).exists()

    def test_deleting_parent_reaps_edge_keeps_child(self, edge):
        child, parent = edge
        parent.delete()
        assert not ThemeParent.objects.filter(from_theme=child).exists()
        assert Theme.objects.filter(pk=child.pk).exists()


# ---------------------------------------------------------------------------
# ModelRelationship: target ladder XOR, rung uniqueness, choices
# ---------------------------------------------------------------------------


class TestModelRelationshipConstraints:
    """DB-level behavior of the target-ladder constraints.

    The startup check (``provenance.E008``) verifies only the *shape* of the
    rung UniqueConstraints; the XOR CheckConstraint and the rung semantics are
    delegated to this test, per the credit subject-XOR precedent.
    """

    @pytest.fixture
    def subject(self, db):
        return make_machine_model(name="Punky Willy", slug="punky-willy")

    @pytest.fixture
    def target(self, db):
        return make_machine_model(name="Rock", slug="rock")

    def _edge(self, subject, *, relationship_type=RelationshipType.COPY, **fields):
        return ModelRelationship.objects.create(
            machine_model=subject,
            relationship_type=relationship_type,
            **fields,
        )

    # --- target XOR ---------------------------------------------------------

    def test_machine_target_accepted(self, subject, target):
        self._edge(subject, target_machine=target)

    def test_label_target_accepted(self, subject):
        self._edge(subject, target_label="several Gottlieb EM models")

    def test_no_target_rejected(self, subject):
        with pytest.raises(IntegrityError):
            self._edge(subject)

    def test_machine_plus_label_rejected(self, subject, target):
        with pytest.raises(IntegrityError):
            self._edge(subject, target_machine=target, target_label="redundant")

    def test_self_target_rejected(self, subject):
        with pytest.raises(IntegrityError):
            self._edge(subject, target_machine=subject)

    # --- rung uniqueness ---------------------------------------------------

    def test_duplicate_machine_target_rejected(self, subject, target):
        self._edge(subject, target_machine=target)
        with pytest.raises(IntegrityError):
            self._edge(subject, target_machine=target)

    def test_duplicate_label_target_rejected(self, subject):
        self._edge(subject, target_label="an unknown game")
        with pytest.raises(IntegrityError):
            self._edge(subject, target_label="an unknown game")

    def test_second_label_with_different_wording_rejected(self, subject):
        """The label rung is a singleton slot keyed by the *slot*, not the
        wording — only a different-wording second row proves that (the
        same-wording case above would also violate a wording-inclusive
        UNIQUE)."""
        self._edge(subject, target_label="an unknown Gottlieb game")
        with pytest.raises(IntegrityError):
            self._edge(subject, target_label="an unidentified Gottlieb")

    def test_different_rungs_coexist(self, subject, target):
        self._edge(subject, target_machine=target)
        self._edge(subject, target_label="an unknown game")
        assert ModelRelationship.objects.filter(machine_model=subject).count() == 2

    # --- choices CHECKs ----------------------------------------------------

    def test_invalid_relationship_type_rejected(self, subject, target):
        edge = self._edge(subject, target_machine=target)
        with pytest.raises(IntegrityError):
            _raw_update(ModelRelationship, edge.pk, relationship_type="remake")

    def test_invalid_license_status_rejected(self, subject, target):
        edge = self._edge(subject, target_machine=target)
        with pytest.raises(IntegrityError):
            _raw_update(ModelRelationship, edge.pk, license_status="disputed")

    # --- machine-target-required (derived from RELATIONSHIP_TYPE_BEHAVIOR) ---

    def test_required_type_machine_target_accepted(self, subject, target):
        self._edge(
            subject,
            target_machine=target,
            relationship_type=RelationshipType.RETHEME,
        )

    def test_required_type_label_target_rejected(self, subject):
        """retheme sets requires_machine_target, so its label rung is barred by
        the derived CHECK even though the target XOR alone would allow it."""
        with pytest.raises(IntegrityError):
            self._edge(
                subject,
                target_label="an unknown donor",
                relationship_type=RelationshipType.RETHEME,
            )

    # The derived CHECK doesn't over-reach: types without the flag still accept a
    # label rung — see ``test_label_target_accepted`` (COPY) above.

    # --- delete behavior ---------------------------------------------------

    def test_deleting_subject_reaps_edge_keeps_target(self, subject, target):
        self._edge(subject, target_machine=target)
        subject.delete()
        assert not ModelRelationship.objects.filter(target_machine=target).exists()
        assert MachineModel.objects.filter(pk=target.pk).exists()

    def test_deleting_target_with_inbound_edge_protected(self, subject, target):
        self._edge(subject, target_machine=target)
        with pytest.raises(ProtectedError):
            target.delete()


# ---------------------------------------------------------------------------
# ModelExportMarket: optional target ladder, rung uniqueness
# ---------------------------------------------------------------------------


class TestModelExportMarketConstraints:
    """DB-level behavior of the export-market target constraints.

    Like ModelRelationship's ladder, but the XOR is *optional*: a row with
    neither target is the legal unknown-market shape, so the CHECK is
    at-most-one rather than exactly-one.
    """

    @pytest.fixture
    def subject(self, db):
        return make_machine_model(name="Black Magic", slug="black-magic")

    @pytest.fixture
    def italy(self, db):
        return Location.objects.create(
            location_path="italy", slug="italy", name="Italy"
        )

    def _row(self, subject, **fields):
        return ModelExportMarket.objects.create(machine_model=subject, **fields)

    # --- target ladder (at most one) ---------------------------------------

    def test_country_target_accepted(self, subject, italy):
        self._row(subject, target_market_location=italy)

    def test_label_target_accepted(self, subject):
        self._row(subject, target_market_label="Europe")

    def test_no_target_accepted(self, subject):
        """Both absent is the legal unknown-market row — the row itself
        asserts "built for export"."""
        self._row(subject)

    def test_location_plus_label_rejected(self, subject, italy):
        with pytest.raises(IntegrityError):
            self._row(
                subject, target_market_location=italy, target_market_label="Europe"
            )

    # --- rung uniqueness ---------------------------------------------------

    def test_duplicate_country_target_rejected(self, subject, italy):
        self._row(subject, target_market_location=italy)
        with pytest.raises(IntegrityError):
            self._row(subject, target_market_location=italy)

    def test_second_null_location_row_rejected(self, subject):
        """The null-location rung is a singleton slot keyed by the *slot*: a
        label row and an unknown row (or two differently-worded label rows)
        collide."""
        self._row(subject, target_market_label="Europe")
        with pytest.raises(IntegrityError):
            self._row(subject)

    def test_country_rows_coexist(self, subject, italy):
        france = Location.objects.create(
            location_path="france", slug="france", name="France"
        )
        self._row(subject, target_market_location=italy)
        self._row(subject, target_market_location=france)
        assert ModelExportMarket.objects.filter(machine_model=subject).count() == 2

    # --- delete behavior ---------------------------------------------------

    def test_deleting_subject_reaps_row_keeps_location(self, subject, italy):
        self._row(subject, target_market_location=italy)
        subject.delete()
        assert not ModelExportMarket.objects.filter(
            target_market_location=italy
        ).exists()
        assert Location.objects.filter(pk=italy.pk).exists()

    def test_deleting_location_with_market_row_protected(self, subject, italy):
        self._row(subject, target_market_location=italy)
        with pytest.raises(ProtectedError):
            italy.delete()


class TestExportEditionOfConstraints:
    def test_self_reference_rejected(self, db):
        pm = make_machine_model(name="Loop", slug="loop")
        with pytest.raises(IntegrityError):
            _raw_update(MachineModel, pm.pk, export_edition_of_id=pm.pk)

    def test_deleting_target_with_export_edition_protected(self, db):
        domestic = make_machine_model(name="Domestic", slug="domestic")
        export = make_machine_model(name="Export", slug="export-ed")
        export.export_edition_of = domestic
        export.save(update_fields=["export_edition_of"])
        with pytest.raises(ProtectedError):
            domestic.delete()


class TestGeneratedDateFallback:
    """The database-generated ``year``/``month`` columns: production date when
    present, else project date — with the month always paired to whichever
    date supplied the year."""

    def _fresh(self, **kwargs) -> MachineModel:
        m = make_machine_model(name="Gen", slug="gen-fallback", **kwargs)
        m.refresh_from_db()
        return m

    def test_production_date_wins(self, db):
        m = self._fresh(
            production_year=1994,
            production_month=3,
            project_year=1993,
            project_month=7,
        )
        assert (m.year, m.month) == (1994, 3)

    def test_falls_back_to_project_date(self, db):
        m = self._fresh(project_year=1993, project_month=7)
        assert (m.year, m.month) == (1993, 7)

    def test_no_dates_yields_null(self, db):
        m = self._fresh()
        assert (m.year, m.month) == (None, None)

    def test_month_never_mixes_sources(self, db):
        # Production supplies the year but has no month; project's month must
        # not leak in alongside production's year.
        m = self._fresh(production_year=1994, project_year=1993, project_month=7)
        assert (m.year, m.month) == (1994, None)

    def test_derived_year_is_filterable_and_sortable(self, db):
        self._fresh(project_year=1993)
        assert MachineModel.objects.filter(year=1993, slug="gen-fallback").exists()
