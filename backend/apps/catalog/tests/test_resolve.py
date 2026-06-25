import pytest
from django.utils import timezone

from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityLocation,
    Location,
    Manufacturer,
    System,
    TechnologyGeneration,
    Theme,
    Title,
)
from apps.catalog.resolve import (
    resolve_all_themes,
    resolve_machine_models,
    resolve_model,
)
from apps.catalog.resolve._relationships import resolve_all_corporate_entity_locations
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim


@pytest.fixture
def ipdb(db):
    return Source.objects.create(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def opdb(db):
    return Source.objects.create(name="OPDB", source_type="database", priority=20)


@pytest.fixture
def editorial(db):
    return Source.objects.create(
        name="The Flip Editorial", source_type="editorial", priority=100
    )


@pytest.fixture
def pm(db):
    return make_machine_model(name="Placeholder", slug="placeholder")


class TestResolveModel:
    def test_basic_resolution(self, pm, ipdb):
        ss = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        make_claim(pm, "name", "Medieval Madness", source=ipdb)
        make_claim(pm, "year", 1997, source=ipdb)
        make_claim(pm, "technology_generation", "solid-state", source=ipdb)

        resolved = resolve_model(pm)
        assert resolved.name == "Medieval Madness"
        assert resolved.year == 1997
        assert resolved.technology_generation == ss

    def test_higher_priority_wins(self, pm, ipdb, editorial):
        make_claim(pm, "name", "Test Game", source=ipdb)
        make_claim(pm, "year", 1996, source=ipdb)
        make_claim(pm, "year", 1997, source=editorial)

        resolved = resolve_model(pm)
        assert resolved.year == 1997  # editorial has higher priority

    def test_same_priority_latest_wins(self, pm, ipdb, opdb):
        make_claim(pm, "name", "IPDB Name", source=ipdb)
        make_claim(pm, "name", "OPDB Name", source=opdb)

        resolved = resolve_model(pm)
        assert resolved.name == "OPDB Name"

    def test_extra_data_catchall(self, pm, ipdb):
        make_claim(pm, "name", "Test Game", source=ipdb)
        make_claim(pm, "model_number", "20021", source=ipdb)

        resolved = resolve_model(pm)
        assert resolved.extra_data["model_number"] == "20021"

    def test_abbreviation_relationship_claim(self, pm, ipdb):
        from apps.provenance.claims import build_relationship_claim

        make_claim(pm, "name", "Test Game", source=ipdb)
        claim_key, value = build_relationship_claim("abbreviation", {"value": "MM"})
        make_claim(pm, "abbreviation", value, source=ipdb, claim_key=claim_key)

        resolved = resolve_model(pm)
        assert list(resolved.abbreviations.values_list("value", flat=True)) == ["MM"]

    def test_int_coercion(self, pm, ipdb):
        make_claim(pm, "name", "Test Game", source=ipdb)
        make_claim(pm, "year", "1997", source=ipdb)
        make_claim(pm, "player_count", "4", source=ipdb)

        resolved = resolve_model(pm)
        assert resolved.year == 1997
        assert resolved.player_count == 4

    def test_decimal_coercion(self, pm, ipdb):
        from decimal import Decimal

        make_claim(pm, "name", "Test Game", source=ipdb)
        make_claim(pm, "ipdb_rating", "8.75", source=ipdb)

        resolved = resolve_model(pm)
        assert resolved.ipdb_rating == Decimal("8.75")

    def test_empty_string_coercion(self, pm, ipdb):
        make_claim(pm, "name", "Test Game", source=ipdb)
        make_claim(pm, "year", "", source=ipdb)
        resolved = resolve_model(pm)
        assert resolved.year is None

    def test_invalid_int_coercion_rejected_at_claim_boundary(self, pm, ipdb):
        """Invalid values are now rejected by assert_claim validation."""
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="must be an integer"):
            make_claim(pm, "year", "not-a-number", source=ipdb)

    def test_stale_values_cleared_on_re_resolve(self, pm, ipdb):
        make_claim(pm, "name", "Test Game", source=ipdb)
        make_claim(pm, "year", 1997, source=ipdb)
        make_claim(pm, "player_count", 4, source=ipdb)
        resolve_model(pm)
        assert pm.year == 1997
        assert pm.player_count == 4

        # Deactivate only year and player_count claims, keep name active.
        pm.claims.filter(
            is_active=True, field_name__in=["year", "player_count"]
        ).update(is_active=False)
        resolve_model(pm)
        pm.refresh_from_db()
        assert pm.year is None
        assert pm.player_count is None
        assert pm.extra_data == {}

    def test_mixed_fields_and_extra_data(self, pm, ipdb, editorial):
        make_claim(pm, "name", "The Addams Family", source=ipdb)
        make_claim(pm, "year", 1992, source=ipdb)
        make_claim(pm, "toys", "Thing hand, bookcase", source=ipdb)
        make_claim(pm, "fun_facts", "A seminal game.", source=editorial)

        resolved = resolve_model(pm)
        assert resolved.name == "The Addams Family"
        assert resolved.year == 1992
        assert resolved.extra_data["toys"] == "Thing hand, bookcase"
        assert resolved.extra_data["fun_facts"] == "A seminal game."


@pytest.mark.django_db
class TestResolveAll:
    def test_basic(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        ss = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        pm1 = make_machine_model(name="P1", slug="p1")
        pm2 = make_machine_model(name="P2", slug="p2")
        pm3 = make_machine_model(name="P3", slug="p3")

        make_claim(pm1, "name", "Medieval Madness", source=ipdb)
        make_claim(pm1, "year", 1997, source=ipdb)
        make_claim(pm2, "name", "The Addams Family", source=ipdb)
        make_claim(pm3, "name", "Twilight Zone", source=ipdb)
        make_claim(pm3, "technology_generation", "solid-state", source=ipdb)

        before = timezone.now()
        count = resolve_machine_models()
        assert count == 3

        pm1.refresh_from_db()
        pm2.refresh_from_db()
        pm3.refresh_from_db()
        assert pm1.name == "Medieval Madness"
        assert pm1.year == 1997
        assert pm2.name == "The Addams Family"
        assert pm3.name == "Twilight Zone"
        assert pm3.technology_generation == ss

        assert pm1.updated_at >= before
        assert pm2.updated_at >= before
        assert pm3.updated_at >= before

    def test_matches_resolve_model(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        opdb = Source.objects.create(
            name="OPDB", slug="opdb", source_type="database", priority=20
        )
        title = Title.objects.create(
            opdb_id="G1111", name="Medieval Madness", slug="mm"
        )
        make_claim(title, "name", "Medieval Madness", source=ipdb)
        TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")

        pm_bulk = make_machine_model(name="P1", slug="p1", title=title)
        pm_single = make_machine_model(name="P2", slug="p2", title=title)

        from apps.provenance.claims import build_relationship_claim

        abbr_key, abbr_val = build_relationship_claim("abbreviation", {"value": "MM"})

        for pm in (pm_bulk, pm_single):
            make_claim(pm, "name", "Medieval Madness", source=ipdb)
            make_claim(pm, "year", 1997, source=opdb)
            make_claim(pm, "title", title.slug, source=opdb)
            make_claim(pm, "abbreviation", abbr_val, source=ipdb, claim_key=abbr_key)
            make_claim(pm, "technology_generation", "solid-state", source=ipdb)

        resolve_model(pm_single)
        pm_single.refresh_from_db()

        resolve_machine_models()
        pm_bulk.refresh_from_db()

        assert pm_bulk.name == pm_single.name
        assert pm_bulk.year == pm_single.year
        assert pm_bulk.title_id == pm_single.title_id
        assert pm_bulk.technology_generation_id == pm_single.technology_generation_id
        assert pm_bulk.extra_data == pm_single.extra_data

    def test_opdb_conflict(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        pm_a = make_machine_model(name="Alpha", slug="alpha")
        pm_b = make_machine_model(name="Beta", slug="beta")

        make_claim(pm_a, "name", "Alpha", source=ipdb)
        make_claim(pm_b, "name", "Beta", source=ipdb)
        make_claim(pm_a, "opdb_id", "GCONFLICT-M1", source=ipdb)
        make_claim(pm_b, "opdb_id", "GCONFLICT-M1", source=ipdb)

        resolve_machine_models()
        pm_a.refresh_from_db()
        pm_b.refresh_from_db()

        assert pm_a.opdb_id == "GCONFLICT-M1"
        assert pm_b.opdb_id is None

    def test_stale_values_cleared(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        pm = make_machine_model(name="P1", slug="p1")

        make_claim(pm, "name", "P1", source=ipdb)
        make_claim(pm, "year", 1997, source=ipdb)
        make_claim(pm, "player_count", 4, source=ipdb)
        resolve_machine_models()
        pm.refresh_from_db()
        assert pm.year == 1997
        assert pm.player_count == 4

        # Deactivate only year and player_count claims, keep name active.
        pm.claims.filter(
            is_active=True, field_name__in=["year", "player_count"]
        ).update(is_active=False)
        resolve_machine_models()
        pm.refresh_from_db()
        assert pm.year is None
        assert pm.player_count is None
        assert pm.extra_data == {}

    def test_query_count(self, django_assert_max_num_queries):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        for i in range(5):
            pm = make_machine_model(name=f"Model {i}", slug=f"model-{i}")
            make_claim(pm, "name", f"Resolved {i}", source=ipdb)
            make_claim(pm, "year", 2000 + i, source=ipdb)

        with django_assert_max_num_queries(185):
            resolve_machine_models()


@pytest.mark.django_db
class TestResolveThemes:
    def test_basic_theme_resolution(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        pm = make_machine_model(name="P1", slug="p1")
        horror = Theme.objects.create(name="Horror", slug="horror")
        licensed = Theme.objects.create(name="Licensed", slug="licensed")

        for theme in (horror, licensed):
            claim_key, value = build_relationship_claim("theme", {"theme": theme.pk})
            make_claim(pm, "theme", value, source=ipdb, claim_key=claim_key)

        resolve_all_themes(subject_ids={pm.pk})
        assert set(pm.themes.values_list("slug", flat=True)) == {
            "horror",
            "licensed",
        }

    def test_theme_exists_false_dispute(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        editorial = Source.objects.create(
            name="Editorial", source_type="editorial", priority=100
        )
        pm = make_machine_model(name="P1", slug="p1")
        horror = Theme.objects.create(name="Horror", slug="horror")

        # IPDB says horror, editorial disputes it.
        claim_key, value = build_relationship_claim("theme", {"theme": horror.pk})
        make_claim(pm, "theme", value, source=ipdb, claim_key=claim_key)
        _, dispute_value = build_relationship_claim(
            "theme", {"theme": horror.pk}, exists=False
        )
        make_claim(pm, "theme", dispute_value, source=editorial, claim_key=claim_key)

        resolve_all_themes(subject_ids={pm.pk})
        assert pm.themes.count() == 0

    def test_stale_themes_cleared(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        pm = make_machine_model(name="P1", slug="p1")
        horror = Theme.objects.create(name="Horror", slug="horror")

        claim_key, value = build_relationship_claim("theme", {"theme": horror.pk})
        make_claim(pm, "theme", value, source=ipdb, claim_key=claim_key)
        resolve_all_themes(subject_ids={pm.pk})
        assert pm.themes.count() == 1

        # Deactivate claim, re-resolve — themes should be empty.
        pm.claims.filter(is_active=True).update(is_active=False)
        resolve_all_themes(subject_ids={pm.pk})
        assert pm.themes.count() == 0

    def test_bulk_theme_resolution(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        pm1 = make_machine_model(name="P1", slug="p1")
        pm2 = make_machine_model(name="P2", slug="p2")
        sports = Theme.objects.create(name="Sports", slug="sports")
        baseball = Theme.objects.create(name="Baseball", slug="baseball")

        make_claim(pm1, "name", "P1", source=ipdb)
        make_claim(pm2, "name", "P2", source=ipdb)

        for pm, themes in [(pm1, [sports, baseball]), (pm2, [sports])]:
            for theme in themes:
                claim_key, value = build_relationship_claim(
                    "theme", {"theme": theme.pk}
                )
                make_claim(pm, "theme", value, source=ipdb, claim_key=claim_key)

        resolve_machine_models()
        assert set(pm1.themes.values_list("slug", flat=True)) == {
            "sports",
            "baseball",
        }
        assert set(pm2.themes.values_list("slug", flat=True)) == {"sports"}


@pytest.mark.django_db
class TestResolveSystem:
    def test_system_claim_sets_fk(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        mfr, _ = Manufacturer.objects.get_or_create(
            slug="williams", defaults={"name": "Williams"}
        )
        system = System.objects.create(
            name="Williams WPC-95", slug="wpc-95", manufacturer=mfr
        )
        pm = make_machine_model(name="Medieval Madness", slug="medieval-madness")
        make_claim(pm, "name", "Medieval Madness", source=ipdb)
        make_claim(pm, "system", "wpc-95", source=ipdb)

        resolve_model(pm)
        pm.refresh_from_db()
        assert pm.system == system

    def test_unknown_system_slug_logs_warning_no_fk(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        pm = make_machine_model(name="Mystery Machine", slug="mystery-machine")
        make_claim(pm, "name", "Mystery Machine", source=ipdb)
        make_claim(pm, "system", "nonexistent-slug", source=ipdb)

        resolve_model(pm)
        pm.refresh_from_db()
        assert pm.system is None

    def test_stale_system_cleared(self):
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        mfr, _ = Manufacturer.objects.get_or_create(
            slug="williams", defaults={"name": "Williams"}
        )
        system = System.objects.create(
            name="Williams WPC-95", slug="wpc-95", manufacturer=mfr
        )
        pm = make_machine_model(
            name="Medieval Madness", slug="medieval-madness", system=system
        )
        # Name claim but no system claim — system should be cleared after resolve.
        make_claim(pm, "name", "Medieval Madness", source=ipdb)
        resolve_model(pm)
        pm.refresh_from_db()
        assert pm.system is None


@pytest.mark.django_db
class TestResolveCorporateEntityLocations:
    def _make_ce(self, slug):
        mfr = Manufacturer.objects.create(name=slug, slug=slug)
        return CorporateEntity.objects.create(name=slug, slug=slug, manufacturer=mfr)

    def _make_location(self, path):
        return Location.objects.create(
            location_path=path,
            slug=path.rsplit("/", 1)[-1],
            name=path,
            location_type="city",
        )

    def _assert_location(self, source, ce, loc):
        claim_key, value = build_relationship_claim("location", {"location": loc.pk})
        make_claim(ce, "location", value, source=source, claim_key=claim_key)

    def test_creates_cel_from_active_claim(self, db):
        source = Source.objects.create(name="PB", source_type="editorial", priority=300)
        ce = self._make_ce("williams")
        loc = self._make_location("usa/il/chicago")
        self._assert_location(source, ce, loc)

        resolve_all_corporate_entity_locations()

        assert CorporateEntityLocation.objects.filter(
            corporate_entity=ce, location=loc
        ).exists()

    def test_deletes_stale_cel_when_claim_deactivated(self, db):
        source = Source.objects.create(name="PB", source_type="editorial", priority=300)
        ce = self._make_ce("williams")
        loc = self._make_location("usa/il/chicago")
        self._assert_location(source, ce, loc)
        resolve_all_corporate_entity_locations()
        assert CorporateEntityLocation.objects.filter(corporate_entity=ce).count() == 1

        ce.claims.filter(is_active=True).update(is_active=False)
        resolve_all_corporate_entity_locations()

        assert not CorporateEntityLocation.objects.filter(corporate_entity=ce).exists()

    def test_retraction_claim_does_not_create_cel(self, db):
        source = Source.objects.create(name="PB", source_type="editorial", priority=300)
        ce = self._make_ce("williams")
        loc = self._make_location("usa/il/chicago")
        claim_key, value = build_relationship_claim(
            "location", {"location": loc.pk}, exists=False
        )
        make_claim(ce, "location", value, source=source, claim_key=claim_key)

        resolve_all_corporate_entity_locations()

        assert not CorporateEntityLocation.objects.filter(
            corporate_entity=ce, location=loc
        ).exists()

    def test_retraction_claim_removes_existing_cel(self, db):
        source = Source.objects.create(name="PB", source_type="editorial", priority=300)
        ce = self._make_ce("williams")
        loc = self._make_location("usa/il/chicago")
        self._assert_location(source, ce, loc)
        resolve_all_corporate_entity_locations()
        assert CorporateEntityLocation.objects.filter(corporate_entity=ce).count() == 1

        claim_key, value = build_relationship_claim(
            "location", {"location": loc.pk}, exists=False
        )
        make_claim(ce, "location", value, source=source, claim_key=claim_key)
        resolve_all_corporate_entity_locations()

        assert not CorporateEntityLocation.objects.filter(corporate_entity=ce).exists()

    def test_handles_multiple_ces(self, db):
        source = Source.objects.create(name="PB", source_type="editorial", priority=300)
        ce1 = self._make_ce("williams")
        ce2 = self._make_ce("bally")
        loc1 = self._make_location("usa/il/chicago")
        loc2 = self._make_location("usa/il/elk-grove-village")
        self._assert_location(source, ce1, loc1)
        self._assert_location(source, ce2, loc2)

        resolve_all_corporate_entity_locations()

        assert CorporateEntityLocation.objects.count() == 2

    def test_high_priority_retraction_beats_low_priority_assertion(self, db):
        """A higher-priority exists=False claim wins over a lower-priority
        exists=True claim on the same (CE, location) pair — winner-take-all by
        source priority, uniform with the other relationship resolvers (cf.
        test_theme_exists_false_dispute)."""
        ipdb = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        editorial = Source.objects.create(
            name="Editorial", source_type="editorial", priority=100
        )
        ce = self._make_ce("williams")
        loc = self._make_location("usa/il/chicago")

        # Low-priority source asserts the location, high-priority source retracts it.
        self._assert_location(ipdb, ce, loc)
        claim_key, value = build_relationship_claim(
            "location", {"location": loc.pk}, exists=False
        )
        make_claim(ce, "location", value, source=editorial, claim_key=claim_key)

        resolve_all_corporate_entity_locations()

        assert not CorporateEntityLocation.objects.filter(corporate_entity=ce).exists()


@pytest.mark.django_db
class TestResolveEntitySlugConflictGuard:
    def test_slug_change_not_reverted_when_slug_field_not_unique(self):
        """resolve_entity must not silently revert a slug change when the
        model's slug field is not globally unique (e.g. Location, where
        slug is unique-per-location_path only).
        """
        from apps.catalog.resolve._entities import resolve_entity

        editorial = Source.objects.create(
            name="The Flip Editorial", source_type="editorial", priority=100
        )
        usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
        il = Location.objects.create(
            location_path="usa/il", slug="il", name="Illinois", parent=usa
        )
        oh = Location.objects.create(
            location_path="usa/oh", slug="oh", name="Ohio", parent=usa
        )
        Location.objects.create(
            location_path="usa/il/springfield",
            slug="springfield",
            name="Springfield",
            parent=il,
        )
        target = Location.objects.create(
            location_path="usa/oh/oldslug",
            slug="oldslug",
            name="Oldslug",
            parent=oh,
        )

        make_claim(target, "slug", "springfield", source=editorial)
        make_claim(target, "name", "Springfield", source=editorial)

        # Bypass the dispatcher so the bug is reachable directly.
        resolve_entity(target)
        target.refresh_from_db()

        assert target.slug == "springfield"
