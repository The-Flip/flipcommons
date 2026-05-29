"""Shared utility functions for catalog API endpoints."""

from __future__ import annotations

from collections.abc import Iterable

from apps.core.licensing import get_minimum_display_rank
from apps.core.types import JsonData
from apps.media.models import EntityMedia

from ..models import (
    CorporateEntity,
    Credit,
    GameplayFeature,
    Location,
    MachineModel,
    Title,
)
from .images import extract_image_urls
from .schemas import (
    CorporateEntityLocationAncestorRef,
    CorporateEntityLocationSchema,
    CreditSchema,
    EntityRef,
    RelatedTitleSchema,
    TitleModelSchema,
    TitleModelVariantSchema,
    TitleRef,
)

# ---------------------------------------------------------------------------
# Generic serialization helpers
# ---------------------------------------------------------------------------


def serialize_credit(credit: Credit) -> CreditSchema:
    """Serialize a Credit row into a CreditSchema."""
    return CreditSchema(
        person=EntityRef(name=credit.person.name, public_id=credit.person.public_id),
        role=credit.role.slug,
        role_display=credit.role.name,
        role_sort_order=credit.role.display_order,
    )


def _intersect_facet_sets(
    models: Iterable[MachineModel], relation_name: str
) -> list[EntityRef]:
    """Return the intersection of a public_id/name M2M across all *models*.

    Each model's related set is collected as ``frozenset((public_id, name))``.
    Only public_ids present on **every** model are included.
    Returns ``[]`` when any model has an empty set or models disagree.
    """
    sets = [
        frozenset((obj.public_id, obj.name) for obj in getattr(m, relation_name).all())
        for m in models
    ]
    if not sets or not all(sets):
        return []
    common = sets[0]
    for s in sets[1:]:
        common &= s
    return (
        [EntityRef(public_id=pid, name=n) for pid, n in sorted(common)]
        if common
        else []
    )


def serialize_title_ref(
    title: Title,
    *,
    min_rank: int | None = None,
    media_by_model: dict[int, list[EntityMedia]] | None = None,
) -> TitleRef:
    """Serialize a Title for use in franchise/series listing context.

    Expects *title* to have prefetched ``machine_models`` (with
    corporate_entity__manufacturer) and ``abbreviations``, plus an
    annotated ``model_count``.
    """
    thumbnail_url = None
    manufacturer_name = None
    year = None
    first = next(iter(title.machine_models.all()), None)
    if first is not None:
        media = media_by_model.get(first.pk) if media_by_model else None
        thumbnail_url, _ = extract_image_urls(
            first.extra_data or {}, media, min_rank=min_rank
        )
        manufacturer_name = (
            first.corporate_entity.manufacturer.name
            if first.corporate_entity and first.corporate_entity.manufacturer
            else None
        )
        year = first.year
    return TitleRef(
        name=title.name,
        public_id=title.public_id,
        abbreviations=[a.value for a in title.abbreviations.all()],
        # model_count is a queryset .annotate() attribute, not on Title itself.
        model_count=getattr(title, "model_count", 0),
        manufacturer_name=manufacturer_name,
        year=year,
        thumbnail_url=thumbnail_url,
    )


def collect_titles(
    models: Iterable[MachineModel],
    *,
    include_manufacturer: bool = False,
    media_by_model: dict[int, list[EntityMedia]] | None = None,
) -> list[RelatedTitleSchema]:
    """Group models by title into a deduplicated title list.

    Pass ``media_by_model`` (built by :func:`fetch_model_media_map`) so card
    thumbnails reflect uploaded backglass; omit it to fall back to
    ``extra_data`` only.
    """
    min_rank = get_minimum_display_rank()
    titles: dict[str, RelatedTitleSchema] = {}
    for m in models:
        if m.title is None:
            continue
        media = media_by_model.get(m.pk) if media_by_model else None
        key = m.title.slug
        if key not in titles:
            thumbnail_url = extract_image_urls(
                m.extra_data or {}, media, min_rank=min_rank
            )[0]
            manufacturer_name = None
            if include_manufacturer:
                mfr = (
                    m.corporate_entity.manufacturer
                    if m.corporate_entity and m.corporate_entity.manufacturer
                    else None
                )
                manufacturer_name = mfr.name if mfr else None
            titles[key] = RelatedTitleSchema(
                name=m.title.name,
                public_id=m.title.public_id,
                year=m.year,
                thumbnail_url=thumbnail_url,
                manufacturer_name=manufacturer_name,
            )
        elif titles[key].thumbnail_url is None:
            thumbnail_url = extract_image_urls(
                m.extra_data or {}, media, min_rank=min_rank
            )[0]
            if thumbnail_url:
                titles[key].thumbnail_url = thumbnail_url
    return sorted(titles.values(), key=lambda t: (t.year is None, -(t.year or 0)))


def _location_ancestors(loc: Location) -> list[CorporateEntityLocationAncestorRef]:
    """Return ancestor locations from immediate parent up to root, in order."""
    ancestors: list[CorporateEntityLocationAncestorRef] = []
    current = loc.parent
    while current is not None:
        ancestors.append(
            CorporateEntityLocationAncestorRef(
                display_name=current.short_name or current.name,
                public_id=current.location_path,
            )
        )
        current = current.parent
    return ancestors


def serialize_locations(
    entity: CorporateEntity,
) -> list[CorporateEntityLocationSchema]:
    """Serialize CorporateEntityLocation rows with ancestor chains."""
    return [
        CorporateEntityLocationSchema(
            public_id=cel.location.location_path,
            location_type=cel.location.location_type,
            display_name=cel.location.short_name or cel.location.name,
            ancestors=_location_ancestors(cel.location),
        )
        for cel in entity.locations.all()
    ]


def _extract_variant_features(extra_data: JsonData) -> list[str]:
    """Return variant feature list from extra_data variant_features claim."""
    features = extra_data.get("opdb.variant_features")
    if not features or not isinstance(features, list):
        return []
    return [str(f) for f in features]


def _get_feature_descendant_slugs(slug: str) -> set[str]:
    """Return *slug* plus all transitive child feature slugs.

    Two queries: one for all features, one for the children M2M.  The BFS
    then runs entirely in Python.  For a leaf feature this returns {slug}.
    For an unknown slug it still returns {slug} (the filter just won't match).
    """
    features = list(
        GameplayFeature.objects.prefetch_related("children").only("pk", "slug")
    )
    children_map: dict[str, list[str]] = {
        f.slug: [c.slug for c in f.children.all()] for f in features
    }
    result: set[str] = {slug}
    stack = [slug]
    while stack:
        current = stack.pop()
        for child_slug in children_map.get(current, []):
            if child_slug not in result:
                result.add(child_slug)
                stack.append(child_slug)
    return result


def serialize_title_machine(
    pm: MachineModel,
    *,
    min_rank: int | None = None,
    media_by_model: dict[int, list[EntityMedia]] | None = None,
) -> TitleModelSchema:
    """Serialize a MachineModel for use in title/theme/system machine lists."""
    if min_rank is None:
        min_rank = get_minimum_display_rank()

    pm_media = media_by_model.get(pm.pk) if media_by_model else None
    thumbnail_url, _ = extract_image_urls(
        pm.extra_data or {}, pm_media, min_rank=min_rank
    )

    # Include variants only when prefetched to avoid N+1 queries.
    variant_qs = (
        pm.variants.all()
        if "variants" in getattr(pm, "_prefetched_objects_cache", {})
        else []
    )
    variants = [
        TitleModelVariantSchema(
            name=v.name,
            public_id=v.public_id,
            year=v.year,
            thumbnail_url=extract_image_urls(
                v.extra_data or {},
                media_by_model.get(v.pk) if media_by_model else None,
                min_rank=min_rank,
            )[0],
        )
        for v in variant_qs
    ]

    mfr = (
        pm.corporate_entity.manufacturer
        if pm.corporate_entity and pm.corporate_entity.manufacturer
        else None
    )
    return TitleModelSchema(
        name=pm.name,
        public_id=pm.public_id,
        year=pm.year,
        manufacturer=EntityRef(name=mfr.name, public_id=mfr.public_id) if mfr else None,
        technology_generation_name=(
            pm.technology_generation.name if pm.technology_generation else None
        ),
        thumbnail_url=thumbnail_url,
        variants=variants,
    )
