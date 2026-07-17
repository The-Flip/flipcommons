"""Tests for on_delete behaviour across catalog ForeignKeys.

Verifies two invariants:
1. PROTECT — deleting a shared/independent entity that is still referenced
   raises ``ProtectedError``.
2. CASCADE — deleting an owner-side record cascades to its owned children
   (aliases, through-table rows, etc.).
"""

from __future__ import annotations

import pytest
from django.db.models import ProtectedError

from apps.catalog.models import (
    Cabinet,
    CorporateEntity,
    Credit,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    Franchise,
    GameFormat,
    GameplayFeature,
    Location,
    MachineModelGameplayFeature,
    MachineModelRewardType,
    MachineModelTag,
    MachineModelTheme,
    Manufacturer,
    Person,
    RewardType,
    Series,
    System,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mfr(db):
    return Manufacturer.objects.create(name="Williams", slug="williams")


@pytest.fixture
def corp(db, mfr):
    return CorporateEntity.objects.create(
        name="Williams Electronics", slug="williams-electronics", manufacturer=mfr
    )


@pytest.fixture
def tech_gen(db):
    return TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")


@pytest.fixture
def tech_sub(db, tech_gen):
    return TechnologySubgeneration.objects.create(
        name="Integrated", slug="integrated", technology_generation=tech_gen
    )


@pytest.fixture
def display_type(db):
    return DisplayType.objects.create(name="DMD", slug="dmd")


@pytest.fixture
def display_subtype(db, display_type):
    return DisplaySubtype.objects.create(
        name="Standard DMD", slug="standard-dmd", display_type=display_type
    )


@pytest.fixture
def cabinet(db):
    return Cabinet.objects.create(name="Floor", slug="floor")


@pytest.fixture
def game_format(db):
    return GameFormat.objects.create(name="Pinball", slug="pinball")


@pytest.fixture
def franchise(db):
    return Franchise.objects.create(name="Star Wars", slug="star-wars")


@pytest.fixture
def series(db):
    return Series.objects.create(name="Classic Line", slug="classic-line")


@pytest.fixture
def title(db, franchise, series):
    return Title.objects.create(
        name="Star Wars",
        slug="star-wars",
        franchise=franchise,
        series=series,
    )


@pytest.fixture
def system(db, mfr, tech_sub):
    return System.objects.create(
        name="WPC", slug="wpc", manufacturer=mfr, technology_subgeneration=tech_sub
    )


@pytest.fixture
def theme(db):
    return Theme.objects.create(name="Sci-Fi", slug="sci-fi")


@pytest.fixture
def gameplay_feature(db):
    return GameplayFeature.objects.create(name="Multiball", slug="multiball")


@pytest.fixture
def reward_type(db):
    return RewardType.objects.create(name="Replay", slug="replay")


@pytest.fixture
def tag(db):
    return Tag.objects.create(name="Widebody", slug="widebody")


@pytest.fixture
def person(db):
    return Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")


@pytest.fixture
def credit_role(db):
    return CreditRole.objects.create(name="Design", slug="design")


@pytest.fixture
def machine(
    db,
    corp,
    title,
    tech_gen,
    tech_sub,
    display_type,
    display_subtype,
    cabinet,
    game_format,
    system,
):
    return make_machine_model(
        name="Medieval Madness",
        slug="medieval-madness",
        corporate_entity=corp,
        title=title,
        technology_generation=tech_gen,
        technology_subgeneration=tech_sub,
        display_type=display_type,
        display_subtype=display_subtype,
        cabinet=cabinet,
        game_format=game_format,
        system=system,
    )


# ---------------------------------------------------------------------------
# PROTECT — shared/independent entities block deletion when referenced
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProtectBlocksDeletion:
    """Deleting a referenced shared entity raises ProtectedError."""

    def test_title_protected(self, machine, title):
        with pytest.raises(ProtectedError):
            title.delete()

    def test_corporate_entity_protected(self, machine, corp):
        with pytest.raises(ProtectedError):
            corp.delete()

    def test_technology_generation_protected(self, machine, tech_gen):
        with pytest.raises(ProtectedError):
            tech_gen.delete()

    def test_technology_subgeneration_protected(self, machine, tech_sub):
        with pytest.raises(ProtectedError):
            tech_sub.delete()

    def test_display_type_protected(self, machine, display_type):
        with pytest.raises(ProtectedError):
            display_type.delete()

    def test_display_subtype_protected(self, machine, display_subtype):
        with pytest.raises(ProtectedError):
            display_subtype.delete()

    def test_cabinet_protected(self, machine, cabinet):
        with pytest.raises(ProtectedError):
            cabinet.delete()

    def test_game_format_protected(self, machine, game_format):
        with pytest.raises(ProtectedError):
            game_format.delete()

    def test_system_protected(self, machine, system):
        with pytest.raises(ProtectedError):
            system.delete()

    def test_franchise_protected(self, title, franchise):
        with pytest.raises(ProtectedError):
            franchise.delete()

    def test_series_protected(self, title, series):
        with pytest.raises(ProtectedError):
            series.delete()

    def test_manufacturer_protected_by_corporate_entity(self, corp, mfr):
        with pytest.raises(ProtectedError):
            mfr.delete()

    def test_manufacturer_protected_by_system(self, system, mfr):
        with pytest.raises(ProtectedError):
            mfr.delete()

    def test_variant_of_protected(self, machine):
        variant = make_machine_model(name="MM LE", slug="mm-le", variant_of=machine)
        with pytest.raises(ProtectedError):
            machine.delete()
        variant.delete()  # cleanup reference first

    def test_remake_of_protected(self, machine):
        remake = make_machine_model(
            name="MM Remake", slug="mm-remake", remake_of=machine
        )
        with pytest.raises(ProtectedError):
            machine.delete()
        remake.delete()

    def test_location_parent_protected(self, db):
        parent = Location.objects.create(name="USA", slug="usa", location_path="usa")
        Location.objects.create(
            name="California",
            slug="california",
            location_path="usa/california",
            parent=parent,
        )
        with pytest.raises(ProtectedError):
            parent.delete()

    def test_person_protected_by_credit(self, machine, person, credit_role):
        Credit.objects.create(model=machine, person=person, role=credit_role)
        with pytest.raises(ProtectedError):
            person.delete()

    def test_gameplay_feature_protected_by_link(self, machine, gameplay_feature):
        MachineModelGameplayFeature.objects.create(
            machinemodel=machine, gameplayfeature=gameplay_feature
        )
        with pytest.raises(ProtectedError):
            gameplay_feature.delete()

    def test_theme_protected_by_link(self, machine, theme):
        MachineModelTheme.objects.create(machinemodel=machine, theme=theme)
        with pytest.raises(ProtectedError):
            theme.delete()

    def test_reward_type_protected_by_link(self, machine, reward_type):
        MachineModelRewardType.objects.create(
            machinemodel=machine, rewardtype=reward_type
        )
        with pytest.raises(ProtectedError):
            reward_type.delete()

    def test_tag_protected_by_link(self, machine, tag):
        MachineModelTag.objects.create(machinemodel=machine, tag=tag)
        with pytest.raises(ProtectedError):
            tag.delete()


# ---------------------------------------------------------------------------
# CASCADE — owner-side deletes cascade to owned children
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCascadeOwnerSide:
    """Deleting an owner cascades to its owned children."""

    def test_machine_delete_cascades_credits(self, machine, person, credit_role):
        Credit.objects.create(model=machine, person=person, role=credit_role)
        machine.delete()
        assert not Credit.objects.filter(person=person).exists()

    def test_machine_delete_cascades_gameplay_features(self, machine, gameplay_feature):
        MachineModelGameplayFeature.objects.create(
            machinemodel=machine, gameplayfeature=gameplay_feature
        )
        machine.delete()
        assert not MachineModelGameplayFeature.objects.exists()
        # The feature itself still exists
        assert GameplayFeature.objects.filter(pk=gameplay_feature.pk).exists()

    def test_machine_delete_cascades_themes(self, machine, theme):
        MachineModelTheme.objects.create(machinemodel=machine, theme=theme)
        machine.delete()
        assert not MachineModelTheme.objects.exists()
        assert Theme.objects.filter(pk=theme.pk).exists()

    def test_machine_delete_cascades_reward_types(self, machine, reward_type):
        MachineModelRewardType.objects.create(
            machinemodel=machine, rewardtype=reward_type
        )
        machine.delete()
        assert not MachineModelRewardType.objects.exists()
        assert RewardType.objects.filter(pk=reward_type.pk).exists()

    def test_machine_delete_cascades_tags(self, machine, tag):
        MachineModelTag.objects.create(machinemodel=machine, tag=tag)
        machine.delete()
        assert not MachineModelTag.objects.exists()
        assert Tag.objects.filter(pk=tag.pk).exists()

    def test_tech_gen_cascades_subgen_when_unreferenced(self, db):
        """Taxonomy hierarchy CASCADE works when nothing else references children."""
        gen = TechnologyGeneration.objects.create(name="Orphan Gen", slug="orphan-gen")
        TechnologySubgeneration.objects.create(
            name="Orphan Sub", slug="orphan-sub", technology_generation=gen
        )
        gen.delete()
        assert not TechnologySubgeneration.objects.filter(slug="orphan-sub").exists()

    def test_tech_gen_cascade_blocked_transitively(self, machine, tech_gen):
        """Cascade from TechGen → TechSubgen is blocked by MachineModel PROTECT."""
        with pytest.raises(ProtectedError):
            tech_gen.delete()


# ---------------------------------------------------------------------------
# PROTECT entities are deletable once unreferenced
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProtectAllowsUnreferencedDeletion:
    """Shared entities can be deleted once nothing references them."""

    def test_unreferenced_title_deletable(self, db, franchise):
        t = Title.objects.create(name="Orphan", slug="orphan", franchise=franchise)
        t.delete()
        assert not Title.objects.filter(slug="orphan").exists()

    def test_unreferenced_theme_deletable(self, theme):
        theme.delete()
        assert not Theme.objects.filter(slug="sci-fi").exists()

    def test_unreferenced_manufacturer_deletable(self, db):
        m = Manufacturer.objects.create(name="Orphan", slug="orphan-mfr")
        m.delete()
        assert not Manufacturer.objects.filter(slug="orphan-mfr").exists()
