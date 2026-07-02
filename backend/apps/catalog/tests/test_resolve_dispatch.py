"""Tests for resolve_after_mutation() dispatch and alias auto-discovery."""

import pytest

from apps.catalog.engine.aliases import discover_alias_types
from apps.catalog.models import (
    CorporateEntity,
    GameplayFeature,
    Location,
    Manufacturer,
    Person,
    RewardType,
    TechnologyGeneration,
    Theme,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import ClaimControlledModel
from apps.provenance.resolution import resolve_after_mutation
from apps.provenance.test_factories import make_claim, make_ingest_source
from apps.provenance.validation import get_relationship_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def source(db):
    return make_ingest_source(name="Test Source", source_type="editorial", priority=100)


@pytest.fixture
def theme(db):
    return Theme.objects.create(name="Placeholder Theme", slug="placeholder-theme")


@pytest.fixture
def title(db):
    return Title.objects.create(name="Placeholder Title", slug="placeholder-title")


@pytest.fixture
def manufacturer(db):
    return Manufacturer.objects.create(name="Placeholder Mfr", slug="placeholder-mfr")


@pytest.fixture
def pm(db):
    return make_machine_model(name="Placeholder", slug="placeholder")


# ---------------------------------------------------------------------------
# Auto-discovery tests
# ---------------------------------------------------------------------------


class TestDiscoverAliasTypes:
    def test_discovers_all_seven_alias_types(self):
        result = discover_alias_types()
        assert len(result) == 7

    def test_known_types_present(self):
        # Full (parent_model, claim_field) pairs — catches typos AND
        # misdeclarations like the right claim_field on the wrong class.
        expected: set[tuple[type[ClaimControlledModel], str]] = {
            (Theme, "theme_alias"),
            (Manufacturer, "manufacturer_alias"),
            (Person, "person_alias"),
            (GameplayFeature, "gameplay_feature_alias"),
            (RewardType, "reward_type_alias"),
            (CorporateEntity, "corporate_entity_alias"),
            (Location, "location_alias"),
        }
        assert {
            (at.parent_model, at.claim_field) for at in discover_alias_types()
        } == expected

    def test_subclass_without_alias_claim_field_fails_at_creation(self):
        """AliasModel.__init_subclass__ must fire at class definition, not
        defer to discovery. Regression guard: ``_meta.abstract`` is unreliable
        inside ``__init_subclass__`` (Django rewrites it post-hoc), and a
        previous version's abstract short-circuit silently skipped the check.
        """
        from django.db import models

        from apps.catalog.models import AliasModel

        with pytest.raises(TypeError, match="alias_claim_field"):

            class BrokenAlias(AliasModel):
                theme = models.ForeignKey(
                    Theme,
                    on_delete=models.CASCADE,
                    related_name="broken_aliases_test",
                )

                class Meta(AliasModel.Meta):
                    app_label = "catalog"


class TestLiteralSchemasAutoPopulated:
    def test_contains_abbreviation(self):
        schema = get_relationship_schema("abbreviation")
        assert schema is not None

    def test_contains_all_alias_types(self):
        for at in discover_alias_types():
            schema = get_relationship_schema(at.claim_field)
            assert schema is not None
            # The alias value-key is named "alias_value" and participates in
            # the claim_key under the identity label "alias".
            alias_value_spec = next(
                (s for s in schema.value_keys if s.name == "alias_value"),
                None,
            )
            assert alias_value_spec is not None
            assert alias_value_spec.identity == "alias"
            assert alias_value_spec.scalar_type is str
            assert alias_value_spec.required is True


# ---------------------------------------------------------------------------
# resolve_after_mutation() routing tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMachineModelRouting:
    def test_scalars_resolved(self, pm, source):
        ss = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        make_claim(pm, "name", "Test Machine", ingest_source=source)
        make_claim(pm, "technology_generation", "solid-state", ingest_source=source)

        resolve_after_mutation(pm, field_names=["name", "technology_generation"])

        pm.refresh_from_db()
        assert pm.name == "Test Machine"
        assert pm.technology_generation == ss

    def test_m2m_resolved(self, pm, source):
        make_claim(pm, "name", "Test Machine", ingest_source=source)
        theme = Theme.objects.create(name="Adventure", slug="adventure")
        ck, val = build_relationship_claim("theme", {"theme": theme.pk})
        make_claim(pm, "theme", val, ingest_source=source, claim_key=ck)

        resolve_after_mutation(pm, field_names=["name", "theme"])

        assert theme in pm.themes.all()


@pytest.mark.django_db
class TestScalarResolution:
    def test_entity_scalars(self, theme, source):
        make_claim(theme, "name", "Updated Theme", ingest_source=source)

        resolve_after_mutation(theme, field_names=["name"])

        theme.refresh_from_db()
        assert theme.name == "Updated Theme"


@pytest.mark.django_db
class TestAliasDispatch:
    def test_theme_alias(self, theme, source):
        ck, val = build_relationship_claim("theme_alias", {"alias_value": "test-alias"})
        make_claim(theme, "theme_alias", val, ingest_source=source, claim_key=ck)

        resolve_after_mutation(theme, field_names=["theme_alias"])

        assert theme.aliases.filter(value="test-alias").exists()

    def test_manufacturer_alias(self, manufacturer, source):
        ck, val = build_relationship_claim(
            "manufacturer_alias", {"alias_value": "mfr-alias"}
        )
        make_claim(
            manufacturer, "manufacturer_alias", val, ingest_source=source, claim_key=ck
        )

        resolve_after_mutation(manufacturer, field_names=["manufacturer_alias"])

        assert manufacturer.aliases.filter(value="mfr-alias").exists()


@pytest.mark.django_db
class TestParentDispatch:
    def test_theme_parent(self, source):
        parent_theme = Theme.objects.create(name="Parent", slug="parent")
        child_theme = Theme.objects.create(name="Child", slug="child")

        ck, val = build_relationship_claim("theme_parent", {"parent": parent_theme.pk})
        make_claim(child_theme, "theme_parent", val, ingest_source=source, claim_key=ck)

        resolve_after_mutation(child_theme, field_names=["theme_parent"])

        assert parent_theme in child_theme.parents.all()


@pytest.mark.django_db
class TestCustomDispatch:
    def test_abbreviation(self, title, source):
        make_claim(title, "name", title.name, ingest_source=source)
        ck, val = build_relationship_claim("abbreviation", {"value": "TST"})
        make_claim(title, "abbreviation", val, ingest_source=source, claim_key=ck)

        resolve_after_mutation(title, field_names=["abbreviation"])

        assert title.abbreviations.filter(value="TST").exists()


@pytest.mark.django_db
class TestEntityTypeGuard:
    def test_mismatched_alias_namespace_ignored(self, manufacturer, source):
        """theme_alias on a Manufacturer should not call the Theme alias resolver."""
        resolve_after_mutation(manufacturer, field_names=["theme_alias"])
        # No error, no side effects — the namespace is silently skipped.

    def test_mismatched_custom_namespace_ignored(self, theme, source):
        """abbreviation on a Theme should not call the Title abbreviation resolver."""
        resolve_after_mutation(theme, field_names=["abbreviation"])


@pytest.mark.django_db
class TestFieldNamesNone:
    def test_resolves_scalars(self, theme, source):
        make_claim(theme, "name", "Fallback Theme", ingest_source=source)

        resolve_after_mutation(theme, field_names=None)

        theme.refresh_from_db()
        assert theme.name == "Fallback Theme"

    def test_resolves_aliases(self, theme, source):
        ck, val = build_relationship_claim(
            "theme_alias", {"alias_value": "fallback-alias"}
        )
        make_claim(theme, "theme_alias", val, ingest_source=source, claim_key=ck)

        resolve_after_mutation(theme, field_names=None)

        assert theme.aliases.filter(value="fallback-alias").exists()
