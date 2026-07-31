"""Catalog row builders shared by the card-grain engine tests.

Create real catalog rows without running the resolver. All taxonomy helpers
get_or_create by slug so the same slug across rows refers to the same value
(the whole point of a facet). Extracted from the Title-grain facet tests when
that module was deleted with the path it pinned.
"""

from __future__ import annotations

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
    LicenseStatus,
    MachineModel,
    Manufacturer,
    ModelRelationship,
    Person,
    ProductionStatus,
    RelationshipType,
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


def _mfr(slug: str) -> CorporateEntity:
    """A CorporateEntity whose manufacturer slug is *slug* (the facet value)."""
    mfr, _ = Manufacturer.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    ce, _ = CorporateEntity.objects.get_or_create(
        slug=f"{slug}-ce",
        defaults={"name": mfr.name, "manufacturer": mfr},
    )
    return ce


def _tech(slug: str) -> TechnologyGeneration:
    obj, _ = TechnologyGeneration.objects.get_or_create(
        slug=slug, defaults={"name": slug.upper()}
    )
    return obj


def _display(slug: str) -> DisplayType:
    obj, _ = DisplayType.objects.get_or_create(
        slug=slug, defaults={"name": slug.upper()}
    )
    return obj


def _system(slug: str) -> System:
    sys_mfr, _ = Manufacturer.objects.get_or_create(
        slug="system-manufacturer", defaults={"name": "System Manufacturer"}
    )
    obj, _ = System.objects.get_or_create(
        slug=slug, defaults={"name": slug.upper(), "manufacturer": sys_mfr}
    )
    return obj


def _display_subtype(slug: str) -> DisplaySubtype:
    """A DisplaySubtype under an auto-created parent DisplayType."""
    obj, _ = DisplaySubtype.objects.get_or_create(
        slug=slug,
        defaults={"name": slug.upper(), "display_type": _display(f"{slug}-parent")},
    )
    return obj


def _subgen(slug: str) -> TechnologySubgeneration:
    """A TechnologySubgeneration under an auto-created parent generation."""
    obj, _ = TechnologySubgeneration.objects.get_or_create(
        slug=slug,
        defaults={
            "name": slug.upper(),
            "technology_generation": _tech(f"{slug}-parent"),
        },
    )
    return obj


def _tag(slug: str) -> Tag:
    obj, _ = Tag.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _cabinet(slug: str) -> Cabinet:
    obj, _ = Cabinet.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _game_format(slug: str) -> GameFormat:
    obj, _ = GameFormat.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _production_status(slug: str) -> ProductionStatus:
    obj, _ = ProductionStatus.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _theme(slug: str, *, parents: tuple[Theme, ...] = ()) -> Theme:
    obj, _ = Theme.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    for p in parents:
        obj.parents.add(p)
    return obj


def _feature(
    slug: str, *, parents: tuple[GameplayFeature, ...] = ()
) -> GameplayFeature:
    obj, _ = GameplayFeature.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    for p in parents:
        obj.parents.add(p)
    return obj


def _reward(slug: str) -> RewardType:
    obj, _ = RewardType.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _person(slug: str) -> Person:
    obj, _ = Person.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _role() -> CreditRole:
    obj, _ = CreditRole.objects.get_or_create(
        slug="design", defaults={"name": "Design", "display_order": 10}
    )
    return obj


def _franchise(slug: str) -> Franchise:
    obj, _ = Franchise.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _series(slug: str) -> Series:
    obj, _ = Series.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _title(name: str, slug: str, **kwargs: object) -> Title:
    return Title.objects.create(name=name, slug=slug, **kwargs)


def _model(
    title: Title,
    slug: str,
    *,
    name: str | None = None,
    manufacturer: str | None = None,
    year: int | None = None,
    tech_gen: str | None = None,
    display_type: str | None = None,
    display_subtype: str | None = None,
    system: str | None = None,
    subgen: str | None = None,
    cabinet: str | None = None,
    game_format: str | None = None,
    production_status: str | None = None,
    player_count: int | None = None,
    themes: tuple[str, ...] = (),
    features: tuple[str, ...] = (),
    reward_types: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    persons: tuple[str, ...] = (),
    variant_of: MachineModel | None = None,
    remake_of: MachineModel | None = None,
    export_edition_of: MachineModel | None = None,
) -> MachineModel:
    m = make_machine_model(
        title=title,
        name=name or slug,
        slug=slug,
        corporate_entity=_mfr(manufacturer) if manufacturer else None,
        year=year,
        technology_generation=_tech(tech_gen) if tech_gen else None,
        display_type=_display(display_type) if display_type else None,
        display_subtype=_display_subtype(display_subtype) if display_subtype else None,
        system=_system(system) if system else None,
        technology_subgeneration=_subgen(subgen) if subgen else None,
        cabinet=_cabinet(cabinet) if cabinet else None,
        game_format=_game_format(game_format) if game_format else None,
        production_status=_production_status(production_status)
        if production_status
        else None,
        player_count=player_count,
        variant_of=variant_of,
        remake_of=remake_of,
        export_edition_of=export_edition_of,
    )
    for s in themes:
        m.themes.add(_theme(s))
    for s in features:
        m.gameplay_features.add(_feature(s))
    for s in reward_types:
        m.reward_types.add(_reward(s))
    for s in tags:
        m.tags.add(_tag(s))
    for s in persons:
        Credit.objects.create(model=m, person=_person(s), role=_role())
    return m


def _edge(
    subject: MachineModel,
    target: MachineModel | None,
    rel_type: RelationshipType,
    *,
    license_status: LicenseStatus = LicenseStatus.UNKNOWN,
    target_label: str = "",
) -> ModelRelationship:
    """A typed relationship edge; ``target=None`` with a *target_label* builds
    the free-text-donor form."""
    return ModelRelationship.objects.create(
        machine_model=subject,
        target_machine=target,
        target_label=target_label,
        relationship_type=rel_type,
        license_status=license_status,
    )
