"""Tests for the validate_catalog management command."""

import json

import pytest
from django.core.management import call_command
from django.db import connection

from apps.catalog.models import (
    CreditRole,
    Franchise,
    MachineModel,
    Manufacturer,
    Person,
    Theme,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Claim, Source


def _create_with_empty_name(model_class, **kwargs):
    """Create a model row with name='' using raw SQL to bypass CHECK constraints.

    The validate_catalog command is supposed to detect these bad rows, so the
    tests must be able to create them even though the DB now forbids it via ORM.
    """
    obj = model_class(**kwargs, name="PLACEHOLDER")
    obj.save()
    table = model_class._meta.db_table
    with connection.cursor() as cur:
        cur.execute("PRAGMA ignore_check_constraints = ON")
        # Table identifier comes from test-controlled ORM metadata; value parameterized.
        sql = f"UPDATE {table} SET name = '' WHERE id = %s"  # noqa: S608
        cur.execute(sql, [obj.pk])
        cur.execute("PRAGMA ignore_check_constraints = OFF")
    obj.refresh_from_db()
    return obj


@pytest.fixture(autouse=True)
def _no_golden_records(monkeypatch, tmp_path):
    """Point golden records at an empty fixture so unrelated tests skip them."""
    import apps.catalog.management.commands.validate_catalog as mod

    empty = tmp_path / "golden_records.json"
    empty.write_text(json.dumps({"models": [], "titles": [], "manufacturers": []}))
    monkeypatch.setattr(mod, "GOLDEN_RECORDS_PATH", empty)


@pytest.fixture
def ipdb(db):
    return Source.objects.create(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def flipcommons_source(db):
    return Source.objects.create(
        name="Flipcommons Catalog",
        slug="flipcommons-catalog",
        source_type="editorial",
        priority=300,
    )


@pytest.fixture
def manufacturer(db):
    return Manufacturer.objects.create(name="Williams", slug="williams")


@pytest.fixture
def title(db):
    return Title.objects.create(
        name="Medieval Madness", slug="medieval-madness", opdb_id="G1234"
    )


class TestValidateCatalogClean:
    """A clean catalog should produce no errors or warnings."""

    def test_empty_catalog_no_errors(self, db, capsys):
        """Empty catalog is valid — no errors or warnings."""
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "error(s)" in captured.out
        assert "0 error(s)" in captured.out
        assert "0 warning(s)" in captured.out

    def test_clean_model_no_errors(self, db, title, capsys):
        make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness-williams-1997",
            title=title,
            year=1997,
        )
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "0 error(s)" in captured.out


class TestNamelessEntities:
    def test_nameless_model_is_error(self, db, title, capsys):
        _create_with_empty_name(MachineModel, slug="empty-name", title=title)
        with pytest.raises(SystemExit, match="1"):
            call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "have no name" in captured.out

    def test_titleless_check_is_registered(self, db, title, capsys):
        """check_titleless_models runs as part of validate_catalog and stays
        at zero for a healthy catalog. The DB NOT NULL guarantees no row can
        actually violate this check via the ORM, but keeping the check
        registered catches any future migration or raw-SQL regression."""
        from apps.catalog.management.commands import validate_catalog

        assert validate_catalog.check_titleless_models in validate_catalog.ALL_CHECKS

        make_machine_model(name="Has Title", slug="has-title", title=title)
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "0 error(s)" in captured.out

    def test_nameless_title_is_error(self, db, capsys):
        _create_with_empty_name(Title, slug="empty-title", opdb_id="G0000")
        with pytest.raises(SystemExit, match="1"):
            call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "title(s) have no name" in captured.out

    def test_nameless_person_is_error(self, db, capsys):
        _create_with_empty_name(Person, slug="empty-person")
        with pytest.raises(SystemExit, match="1"):
            call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "person(s) have no name" in captured.out


class TestVariantChains:
    def test_variant_chain_is_warning(self, db, capsys):
        root = make_machine_model(name="Root", slug="root")
        mid = make_machine_model(name="Mid", slug="mid", variant_of=root)
        make_machine_model(name="Leaf", slug="leaf", variant_of=mid)
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "variant_of chains" in captured.out
        assert "0 error(s)" in captured.out

    def test_variant_chain_fails_with_fail_on_warn(self, db, capsys):
        root = make_machine_model(name="Root", slug="root")
        mid = make_machine_model(name="Mid", slug="mid", variant_of=root)
        make_machine_model(name="Leaf", slug="leaf", variant_of=mid)
        with pytest.raises(SystemExit, match="1"):
            call_command("validate_catalog", "--fail-on-warn")


class TestDuplicatePersons:
    def test_duplicate_person_names_are_warning(self, db, capsys):
        Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        Person.objects.create(name="pat lawlor", slug="pat-lawlor-2")
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "person name(s) appear more than once" in captured.out


class TestWinningClaims:
    def test_disabled_source_claim_never_wins(self, db, ipdb):
        """_winning_claims must match the resolver: disabled sources are excluded.

        Routing the validator through the shared ranked_claims added the
        disabled-source exclusion; before, a disabled high-priority claim the
        resolver would never materialize could be validated as the winner.
        """
        from django.contrib.contenttypes.models import ContentType

        from apps.catalog.management.commands.validate_catalog import _winning_claims

        disabled = Source.objects.create(
            name="Disabled", source_type="other", priority=999, is_enabled=False
        )
        pm = make_machine_model(name="Win Pin", slug="win-pin")
        Claim.objects.assert_claim(pm, "year", 1997, source=ipdb)
        Claim.objects.assert_claim(pm, "year", 2099, source=disabled)

        ct = ContentType.objects.get_for_model(MachineModel)
        values = {c.value for c in _winning_claims(ct, "year")}
        assert 2099 not in values  # disabled source excluded, despite priority 999
        assert 1997 in values


class TestUnresolvedFKClaims:
    def test_unresolved_system_claim_is_warning(self, db, ipdb, capsys):
        pm = make_machine_model(name="Test", slug="test-model")
        Claim.objects.assert_claim(pm, "system", "nonexistent-sys", source=ipdb)
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "unresolved system claim" in captured.out


class TestUnresolvedCreditClaims:
    def test_missing_person_in_credit_claim(self, db, ipdb, capsys):
        role = CreditRole.objects.create(name="Design", slug="design")
        pm = make_machine_model(name="Test", slug="test-model")
        from apps.catalog.claims import build_relationship_claim

        claim_key, value = build_relationship_claim(
            "credit", {"person": 99999, "role": role.pk}
        )
        Claim.objects.assert_claim(
            pm, "credit", value, source=ipdb, claim_key=claim_key
        )
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "missing person PKs" in captured.out

    def test_missing_role_in_credit_claim(self, db, ipdb, capsys):
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        pm = make_machine_model(name="Test", slug="test-model")
        from apps.catalog.claims import build_relationship_claim

        claim_key, value = build_relationship_claim(
            "credit", {"person": person.pk, "role": 99999}
        )
        Claim.objects.assert_claim(
            pm, "credit", value, source=ipdb, claim_key=claim_key
        )
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "missing role PKs" in captured.out


class TestUncuratedThemes:
    def test_auto_created_themes_noted(self, db, ipdb, flipcommons_source, capsys):
        # Curated theme — has a flipcommons-catalog name claim.
        curated = Theme.objects.create(name="Sports", slug="sports")
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(Theme)
        Claim.objects.create(
            content_type=ct,
            object_id=curated.pk,
            source=flipcommons_source,
            field_name="name",
            claim_key="name",
            value="Sports",
        )

        # Uncurated theme — no flipcommons-catalog claim.
        Theme.objects.create(name="Basebal", slug="basebal")

        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "auto-created" in captured.out
        assert "basebal" in captured.out


class TestGoldenRecords:
    """Test the golden records spot-check system."""

    @pytest.fixture
    def golden_file(self, tmp_path, monkeypatch):
        """Create a temporary golden_records.json and patch the path."""
        import apps.catalog.management.commands.validate_catalog as mod

        path = tmp_path / "golden_records.json"

        def _write(data):
            path.write_text(json.dumps(data))
            monkeypatch.setattr(mod, "GOLDEN_RECORDS_PATH", path)
            return path

        return _write

    def test_golden_model_passes(self, db, golden_file, capsys):
        t = Title.objects.create(
            name="Godzilla", slug="godzilla-stern", opdb_id="GweeP"
        )
        make_machine_model(
            name="Godzilla (Premium)",
            slug="godzilla-premium",
            title=t,
            ipdb_id=6842,
            opdb_id="GweeP-Ml9pZ-ARZoY",
        )
        golden_file(
            {
                "models": [
                    {
                        "slug": "godzilla-premium",
                        "expect": {
                            "name": "Godzilla (Premium)",
                            "title_slug": "godzilla-stern",
                            "ipdb_id": 6842,
                            "opdb_id": "GweeP-Ml9pZ-ARZoY",
                        },
                    }
                ],
                "titles": [],
                "manufacturers": [],
            }
        )
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "golden record(s) passed" in captured.out
        assert "0 error(s)" in captured.out

    def test_golden_model_wrong_field_is_error(self, db, golden_file, capsys):
        make_machine_model(
            name="Godzilla (Premium)",
            slug="godzilla-premium",
            ipdb_id=6842,
        )
        golden_file(
            {
                "models": [
                    {
                        "slug": "godzilla-premium",
                        "expect": {"ipdb_id": 9999},
                    }
                ],
                "titles": [],
                "manufacturers": [],
            }
        )
        with pytest.raises(SystemExit, match="1"):
            call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "ipdb_id=6842" in captured.out
        assert "expected 9999" in captured.out

    def test_golden_model_missing_is_error(self, db, golden_file, capsys):
        golden_file(
            {
                "models": [
                    {
                        "slug": "nonexistent-machine",
                        "expect": {"name": "Nope"},
                    }
                ],
                "titles": [],
                "manufacturers": [],
            }
        )
        with pytest.raises(SystemExit, match="1"):
            call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_golden_title_passes(self, db, golden_file, capsys):
        f = Franchise.objects.create(name="Godzilla", slug="godzilla")
        Title.objects.create(
            name="Godzilla",
            slug="godzilla-stern",
            opdb_id="GweeP",
            franchise=f,
        )
        golden_file(
            {
                "models": [],
                "titles": [
                    {
                        "slug": "godzilla-stern",
                        "expect": {
                            "name": "Godzilla",
                            "opdb_id": "GweeP",
                            "franchise_slug": "godzilla",
                        },
                    }
                ],
                "manufacturers": [],
            }
        )
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "golden record(s) passed" in captured.out

    def test_golden_variant_of_checked(self, db, golden_file, capsys):
        parent = make_machine_model(
            name="Godzilla (Premium)",
            slug="godzilla-premium",
        )
        make_machine_model(
            name="Godzilla (LE)",
            slug="godzilla-le",
            variant_of=parent,
        )
        golden_file(
            {
                "models": [
                    {
                        "slug": "godzilla-le",
                        "expect": {"variant_of_slug": "godzilla-premium"},
                    }
                ],
                "titles": [],
                "manufacturers": [],
            }
        )
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "0 error(s)" in captured.out

    def test_golden_conversion_checked(self, db, golden_file, capsys):
        parent = make_machine_model(name="Eight Ball", slug="eight-ball")
        make_machine_model(
            name="Challenger",
            slug="challenger",
            converted_from=parent,
        )
        golden_file(
            {
                "models": [
                    {
                        "slug": "challenger",
                        "expect": {
                            "converted_from_slug": "eight-ball",
                            "variant_of_slug": None,
                        },
                    }
                ],
                "titles": [],
                "manufacturers": [],
            }
        )
        call_command("validate_catalog")
        captured = capsys.readouterr()
        assert "0 error(s)" in captured.out
