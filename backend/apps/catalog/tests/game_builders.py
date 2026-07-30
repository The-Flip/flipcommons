"""Catalog row builders shared by the card-grain engine tests.

Create real catalog rows without running the resolver. All taxonomy helpers
get_or_create by slug so the same slug across rows refers to the same value
(the whole point of a facet). Extracted from the Title-grain facet tests when
that module was deleted with the path it pinned.
"""

from __future__ import annotations

from apps.catalog.models import (
    CorporateEntity,
    Credit,
    CreditRole,
    DisplayType,
    Franchise,
    GameplayFeature,
    MachineModel,
    Manufacturer,
    Person,
    RewardType,
    Series,
    System,
    TechnologyGeneration,
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
    system: str | None = None,
    player_count: int | None = None,
    themes: tuple[str, ...] = (),
    features: tuple[str, ...] = (),
    reward_types: tuple[str, ...] = (),
    persons: tuple[str, ...] = (),
    variant_of: MachineModel | None = None,
) -> MachineModel:
    m = make_machine_model(
        title=title,
        name=name or slug,
        slug=slug,
        corporate_entity=_mfr(manufacturer) if manufacturer else None,
        year=year,
        technology_generation=_tech(tech_gen) if tech_gen else None,
        display_type=_display(display_type) if display_type else None,
        system=_system(system) if system else None,
        player_count=player_count,
        variant_of=variant_of,
    )
    for s in themes:
        m.themes.add(_theme(s))
    for s in features:
        m.gameplay_features.add(_feature(s))
    for s in reward_types:
        m.reward_types.add(_reward(s))
    for s in persons:
        Credit.objects.create(model=m, person=_person(s), role=_role())
    return m
