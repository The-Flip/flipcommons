"""Titles router — list, detail, and claims endpoints."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from django.db.models import (
    Count,
    F,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
)
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.pagination import paginate
from ninja.responses import Status
from ninja.security import django_auth
from pydantic import TypeAdapter

from apps.catalog.naming import MAX_CATALOG_NAME_LENGTH, normalize_catalog_name
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.pagination import NamedPageNumberPagination
from apps.core.schemas import (
    ErrorDetailSchema,
    RateLimitErrorSchema,
    ValidationErrorSchema,
)
from apps.media.helpers import all_media
from apps.media.models import EntityMedia
from apps.media.schemas import MediaRenditionsSchema
from apps.media.storage import build_public_url, build_storage_key
from apps.provenance.helpers import claims_prefetch
from apps.provenance.models import ChangeSetAction
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    DELETE_RATE_LIMIT_SPEC,
    EDIT_RATE_LIMIT_SPEC,
    rate_limited,
)
from apps.provenance.schemas import (
    ChangeSetInputSchema,
    ReviewLinkSchema,
)

from ..cache import get_cached_response, set_cached_response, titles_all_key
from ..models import (
    Credit,
    MachineModel,
    MachineModelGameplayFeature,
    Title,
    TitleAbbreviation,
)
from ._typing import CreditKey, GameplayFeatureAgreement, SlugName
from .constants import DEFAULT_PAGE_SIZE
from .edit_claims import (
    ClaimSpec,
    execute_claims,
    plan_abbreviation_claims,
    plan_scalar_field_claims,
    raise_form_error,
)
from .entity_create import (
    assert_name_available,
    assert_public_id_available,
    create_entity_with_claims,
    validate_name,
    validate_slug_format,
)
from .helpers import (
    _intersect_facet_sets,
    serialize_credit,
    serialize_title_machine,
)
from .images import extract_image_urls, fetch_model_media_map, media_prefetch
from .machine_models import (
    ModelDetailSchema,
    _model_detail_qs,
    _serialize_model_detail,
)
from .rich_text import describe
from .schemas import (
    AlreadyDeletedSchema,
    CatalogDetailSchema,
    CreditSchema,
    EntityCreateInputSchema,
    EntityRef,
    GameplayFeatureRef,
    SoftDeleteBlockedSchema,
    TitleClaimPatchSchema,
    TitleDeletePreviewSchema,
    TitleModelSchema,
)
from .soft_delete import (
    SoftDeleteBlockedError,
    count_entity_changesets,
    execute_soft_delete,
    plan_soft_delete,
    serialize_blocking_referrer,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TitleListItemSchema(Schema):
    name: str
    slug: str
    abbreviations: list[str] = []
    model_count: int = 0
    manufacturer: EntityRef | None = None
    year: int | None = None
    thumbnail_url: str | None = None
    # Facet data — aggregated from non-variant models
    tech_generations: list[EntityRef] = []
    display_types: list[EntityRef] = []
    player_counts: list[int] = []
    systems: list[EntityRef] = []
    themes: list[EntityRef] = []
    gameplay_features: list[EntityRef] = []
    reward_types: list[EntityRef] = []
    persons: list[EntityRef] = []
    franchise: EntityRef | None = None
    series: EntityRef | None = None
    year_min: int | None = None
    year_max: int | None = None
    ipdb_rating_max: float | None = None


_ALL_ADAPTER: TypeAdapter[list[TitleListItemSchema]] = TypeAdapter(
    list[TitleListItemSchema]
)


class AgreedSpecsSchema(Schema):
    """Spec fields where all child models of a title agree on the value."""

    technology_generation: EntityRef | None = None
    technology_subgeneration: EntityRef | None = None
    display_type: EntityRef | None = None
    player_count: int | None = None
    flipper_count: int | None = None
    system: EntityRef | None = None
    cabinet: EntityRef | None = None
    game_format: EntityRef | None = None
    display_subtype: EntityRef | None = None
    themes: list[EntityRef] = []
    gameplay_features: list[GameplayFeatureRef] = []
    reward_types: list[EntityRef] = []
    tags: list[EntityRef] = []
    production_quantity: str | None = None


class CrossTitleLinkSchema(Schema):
    """A cross-title relationship (converted_from / remake_of) contributed by
    a specific model under the current title."""

    relation: str
    other_title: EntityRef
    source_model: EntityRef


class AggregatedMediaSchema(Schema):
    """A media asset from one of the title's models, with its source model."""

    asset_uuid: str
    category: str | None = None
    is_primary: bool
    uploaded_by_username: str | None = None
    renditions: MediaRenditionsSchema
    source_model: EntityRef


class TitleDetailSchema(CatalogDetailSchema):
    slug: str
    opdb_id: str | None = None
    fandom_page_id: int | None = None
    abbreviations: list[str] = []
    needs_review: bool = False
    needs_review_notes: str = ""
    review_links: list[ReviewLinkSchema] = []
    hero_image_url: str | None = None
    franchise: EntityRef | None = None
    machines: list[TitleModelSchema]
    series: EntityRef | None = None
    credits: list[CreditSchema] = []
    agreed_specs: AgreedSpecsSchema = AgreedSpecsSchema()
    related_titles: list[CrossTitleLinkSchema] = []
    media: list[AggregatedMediaSchema] = []
    model_detail: ModelDetailSchema | None = None


class TitleDeleteResponseSchema(Schema):
    changeset_id: int
    affected_titles: list[str]
    affected_models: list[str]


def _assert_title_name_available(name: str, *, exclude_pk: int | None = None) -> None:
    """Title-specific shim over :func:`assert_name_available`.

    Kept as a thin wrapper so existing call sites (the rename path in
    :func:`patch_title_claims`) read clearly. Title name collisions are
    global: there is no narrower scope than "the whole catalog of active
    titles."
    """
    assert_name_available(
        Title,
        name,
        normalize=normalize_catalog_name,
        exclude_pk=exclude_pk,
        friendly_label="title",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dedup_facet_refs(items: Iterable[SlugName]) -> list[EntityRef]:
    """Deduplicate {slug, name} pairs preserving insertion order."""
    seen: set[str] = set()
    result: list[EntityRef] = []
    for slug, name in items:
        if slug and slug not in seen:
            seen.add(slug)
            result.append(EntityRef(public_id=slug, name=name))
    return result


def _dedup_facet_dicts(
    items: Iterable[SlugName],
) -> list[dict[str, str]]:
    """Like :func:`_dedup_facet_refs` but emits plain dicts.

    Used by the cached ``/all/`` endpoints, whose responses are serialized
    via :func:`set_cached_response`'s ``json.dumps`` fast path — Pydantic
    Schema instances are not JSON-serializable there.
    """
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for slug, name in items:
        if slug and slug not in seen:
            seen.add(slug)
            out.append({"public_id": slug, "name": name})
    return out


def _serialize_title_list(
    title: Title,
    *,
    min_rank: int | None = None,
    media_by_model: dict[int, list[EntityMedia]] | None = None,
) -> TitleListItemSchema:
    thumbnail_url: str | None = None
    manufacturer: EntityRef | None = None
    year: int | None = None
    machines = list(title.machine_models.all())

    # Collect facet data from all non-variant models
    tech_gen_pairs: list[SlugName] = []
    display_type_pairs: list[SlugName] = []
    player_counts_set: set[int] = set()
    system_pairs: list[SlugName] = []
    theme_pairs: list[SlugName] = []
    gameplay_feature_pairs: list[SlugName] = []
    reward_type_pairs: list[SlugName] = []
    person_pairs: list[SlugName] = []
    years: list[int] = []
    ratings: list[float] = []

    for m in machines:
        if m.technology_generation:
            tech_gen_pairs.append(
                SlugName(m.technology_generation.slug, m.technology_generation.name)
            )
        if m.display_type:
            display_type_pairs.append(
                SlugName(m.display_type.slug, m.display_type.name)
            )
        if m.player_count is not None:
            player_counts_set.add(m.player_count)
        if m.system:
            system_pairs.append(SlugName(m.system.slug, m.system.name))
        for theme in m.themes.all():
            theme_pairs.append(SlugName(theme.slug, theme.name))
        for gf in m.gameplay_features.all():
            gameplay_feature_pairs.append(SlugName(gf.slug, gf.name))
        for rt in m.reward_types.all():
            reward_type_pairs.append(SlugName(rt.slug, rt.name))
        for credit in m.credits.all():
            person_pairs.append(SlugName(credit.person.slug, credit.person.name))
        if m.year is not None:
            years.append(m.year)
        if m.ipdb_rating is not None:
            ratings.append(float(m.ipdb_rating))

    if machines:
        first = machines[0]
        media = media_by_model.get(first.pk) if media_by_model else None
        thumbnail_url, _ = extract_image_urls(
            first.extra_data or {}, media, min_rank=min_rank
        )
        mfr = (
            first.corporate_entity.manufacturer
            if first.corporate_entity and first.corporate_entity.manufacturer
            else None
        )
        manufacturer = (
            EntityRef(public_id=mfr.public_id, name=mfr.name) if mfr else None
        )
        year = first.year

    # Franchise and Series (both FKs on Title)
    franchise: EntityRef | None = None
    if title.franchise:
        franchise = EntityRef(
            public_id=title.franchise.public_id, name=title.franchise.name
        )
    series: EntityRef | None = None
    if title.series:
        series = EntityRef(public_id=title.series.public_id, name=title.series.name)

    return TitleListItemSchema(
        name=title.name,
        slug=title.slug,
        abbreviations=[a.value for a in title.abbreviations.all()],
        # model_count is a queryset .annotate() attribute, not on Title itself.
        model_count=getattr(title, "model_count", 0),
        manufacturer=manufacturer,
        year=year,
        thumbnail_url=thumbnail_url,
        tech_generations=_dedup_facet_refs(tech_gen_pairs),
        display_types=_dedup_facet_refs(display_type_pairs),
        player_counts=sorted(player_counts_set),
        systems=_dedup_facet_refs(system_pairs),
        themes=_dedup_facet_refs(theme_pairs),
        gameplay_features=_dedup_facet_refs(gameplay_feature_pairs),
        reward_types=_dedup_facet_refs(reward_type_pairs),
        persons=_dedup_facet_refs(person_pairs),
        franchise=franchise,
        series=series,
        year_min=min(years) if years else None,
        year_max=max(years) if years else None,
        ipdb_rating_max=max(ratings) if ratings else None,
    )


def _build_review_links(title: Title) -> list[ReviewLinkSchema]:
    """Build external/internal review links for a needs_review title."""
    links: list[ReviewLinkSchema] = []

    # Related titles by name match (only OPDB-backed ones).
    base_name = re.sub(r"\s*\([^)]*\)\s*$", "", title.name).strip()
    related = (
        Title.objects.active()
        .filter(Q(name__iexact=title.name) | Q(name__iexact=base_name))
        .exclude(pk=title.pk)
        .exclude(opdb_id__isnull=True)
    )
    for rt in related:
        links.append(ReviewLinkSchema(label=rt.name, url=f"/titles/{rt.slug}"))
        links.append(
            ReviewLinkSchema(
                label=f"OPDB {rt.opdb_id}",
                url=f"https://opdb.org/machines/{rt.opdb_id}",
            )
        )

    return links


def _agreed_value[T](
    models: Sequence[MachineModel],
    accessor: Callable[[MachineModel], T | None],
) -> T | None:
    """Return a value if *every* model agrees, else None.

    *accessor* is called with each model and should return the value (or None
    if the model has no data for this field).  The value is only returned when
    **all** models produce the same non-None result; if any model returns None
    or disagrees the result is None.
    """
    values = [accessor(m) for m in models]
    if not values or any(v is None for v in values):
        return None
    first = values[0]
    return first if all(v == first for v in values) else None


def _compute_agreed_specs(models: Sequence[MachineModel]) -> AgreedSpecsSchema:
    """Return spec fields that all *models* agree on."""

    def _fk_pair(m: MachineModel, attr: str) -> tuple[str, str] | None:
        obj = getattr(m, attr, None)
        return (obj.name, obj.public_id) if obj else None

    def _ref_for(attr: str) -> EntityRef | None:
        def accessor(m: MachineModel) -> tuple[str, str] | None:
            return _fk_pair(m, attr)

        val = _agreed_value(models, accessor)
        return EntityRef(name=val[0], public_id=val[1]) if val else None

    # Themes: only roll up when every model has the same set.
    theme_sets = [
        frozenset((t.public_id, t.name) for t in m.themes.all()) for m in models
    ]
    themes: list[EntityRef] = []
    if (
        theme_sets
        and all(ts for ts in theme_sets)
        and all(ts == theme_sets[0] for ts in theme_sets)
    ):
        themes = [EntityRef(name=n, public_id=pid) for pid, n in sorted(theme_sets[0])]

    # Gameplay features: intersection across all models (with count agreement).
    gf_maps: list[dict[str, GameplayFeatureAgreement]] = []
    for m in models:
        gf_map: dict[str, GameplayFeatureAgreement] = {}
        for t in m.machinemodelgameplayfeature_set.all():
            gf_map[t.gameplayfeature.public_id] = GameplayFeatureAgreement(
                t.gameplayfeature.name, t.count
            )
        gf_maps.append(gf_map)

    gameplay_features: list[GameplayFeatureRef] = []
    if gf_maps and all(gf_maps):
        common_public_ids = set(gf_maps[0])
        for gf_map in gf_maps[1:]:
            common_public_ids &= set(gf_map)
        if common_public_ids:
            for public_id in sorted(common_public_ids):
                name = gf_maps[0][public_id].name
                counts = [gf_map[public_id].count for gf_map in gf_maps]
                count = counts[0] if all(c == counts[0] for c in counts) else None
                gameplay_features.append(
                    GameplayFeatureRef(public_id=public_id, name=name, count=count)
                )

    pq = _agreed_value(models, lambda m: m.production_quantity or None)

    return AgreedSpecsSchema(
        technology_generation=_ref_for("technology_generation"),
        technology_subgeneration=_ref_for("technology_subgeneration"),
        display_type=_ref_for("display_type"),
        system=_ref_for("system"),
        cabinet=_ref_for("cabinet"),
        game_format=_ref_for("game_format"),
        display_subtype=_ref_for("display_subtype"),
        player_count=_agreed_value(models, lambda m: m.player_count),
        flipper_count=_agreed_value(models, lambda m: m.flipper_count),
        production_quantity=pq or None,
        themes=themes,
        gameplay_features=gameplay_features,
        reward_types=_intersect_facet_sets(models, "reward_types"),
        tags=_intersect_facet_sets(models, "tags"),
    )


def _collect_related_titles(
    models: Sequence[MachineModel], current_title: Title
) -> list[CrossTitleLinkSchema]:
    """Collect cross-title ``converted_from`` / ``remake_of`` links.

    For each model under *current_title* that has a ``converted_from`` or
    ``remake_of`` pointing to a model under a *different* title, emit one
    entry per link with the relation kind, the other title, and the source
    model under the current title.  Same-title relations (LE→Pro conversion,
    within-title remakes) are excluded — they are not cross-title content.
    """
    items: list[CrossTitleLinkSchema] = []
    for m in models:
        for attr in ("converted_from", "remake_of"):
            other = getattr(m, attr, None)
            if other is None or other.title_id is None:
                continue
            if other.title_id == current_title.pk:
                continue
            items.append(
                CrossTitleLinkSchema(
                    relation=attr,
                    other_title=EntityRef(
                        public_id=other.title.public_id, name=other.title.name
                    ),
                    source_model=EntityRef(public_id=m.public_id, name=m.name),
                )
            )
    return items


def _collect_aggregated_media(
    models: Sequence[MachineModel],
) -> list[AggregatedMediaSchema]:
    """Collect uploaded media across all *models* (union), labeled with
    the source model each item came from."""
    items: list[AggregatedMediaSchema] = []
    for m in models:
        source_ref = EntityRef(public_id=m.public_id, name=m.name)
        for em in all_media(m):
            items.append(
                AggregatedMediaSchema(
                    asset_uuid=str(em.asset.uuid),
                    category=em.category,
                    is_primary=em.is_primary,
                    uploaded_by_username=(
                        em.asset.uploaded_by.username if em.asset.uploaded_by else None
                    ),
                    renditions=MediaRenditionsSchema(
                        thumb=build_public_url(
                            build_storage_key(em.asset.uuid, "thumb")
                        ),
                        display=build_public_url(
                            build_storage_key(em.asset.uuid, "display")
                        ),
                    ),
                    source_model=source_ref,
                )
            )
    return items


def _select_title_hero_image_url(
    models: Sequence[MachineModel], *, min_rank: int
) -> str | None:
    """Return the title hero — uploaded backglass on any model wins, else
    the earliest model's third-party image."""
    for model in models:
        backglass = [
            em
            for em in all_media(model)
            if em.category == "backglass" and em.is_primary
        ]
        if backglass:
            _, hero = extract_image_urls(
                model.extra_data or {}, backglass, min_rank=min_rank
            )
            if hero:
                return hero

    if not models:
        return None

    # No uploaded primary backglass on any model — fall through to the
    # earliest model's third-party image.
    _, hero_image_url = extract_image_urls(
        models[0].extra_data or {}, None, min_rank=min_rank
    )
    return hero_image_url


def _serialize_title_detail(title: Title) -> TitleDetailSchema:
    min_rank = get_minimum_display_rank()
    model_objs = list(title.machine_models.all())
    variant_ids: list[int] = []
    for pm in model_objs:
        if "variants" in getattr(pm, "_prefetched_objects_cache", {}):
            variant_ids.extend(v.pk for v in pm.variants.all())
    media_by_model = fetch_model_media_map([pm.pk for pm in model_objs] + variant_ids)
    machines = [
        serialize_title_machine(pm, min_rank=min_rank, media_by_model=media_by_model)
        for pm in model_objs
    ]
    series = (
        EntityRef(name=title.series.name, public_id=title.series.public_id)
        if title.series
        else None
    )
    review_links = _build_review_links(title) if title.needs_review else []

    hero_image_url = _select_title_hero_image_url(model_objs, min_rank=min_rank)

    # Credits that appear on every model (intersection, not union).
    credit_sets = []
    credit_data: dict[CreditKey, CreditSchema] = {}
    for pm in model_objs:
        model_keys: set[CreditKey] = set()
        for c in pm.credits.all():
            key = CreditKey(c.person.slug, c.role.slug)
            model_keys.add(key)
            credit_data.setdefault(key, serialize_credit(c))
        credit_sets.append(model_keys)

    if credit_sets:
        common_keys = credit_sets[0]
        for s in credit_sets[1:]:
            common_keys &= s
        credits = [v for k, v in credit_data.items() if k in common_keys]
    else:
        credits = []

    # Agreed specs across all models.
    agreed_specs = (
        _compute_agreed_specs(model_objs) if model_objs else AgreedSpecsSchema()
    )

    # Cross-title links and aggregated media (union across all models).
    related_titles = _collect_related_titles(model_objs, title)
    media = _collect_aggregated_media(model_objs)

    # For single-model titles with no variants, include full model detail inline.
    model_detail: ModelDetailSchema | None = None
    if len(machines) == 1 and not machines[0].variants:
        pm = _model_detail_qs().get(slug=machines[0].public_id)
        model_detail = _serialize_model_detail(pm)

    return TitleDetailSchema(
        name=title.name,
        public_id=title.public_id,
        last_modified=title.last_modified,
        slug=title.slug,
        opdb_id=title.opdb_id,
        fandom_page_id=title.fandom_page_id,
        abbreviations=[a.value for a in title.abbreviations.all()],
        description=describe(title),
        needs_review=title.needs_review,
        needs_review_notes=title.needs_review_notes,
        review_links=review_links,
        hero_image_url=hero_image_url,
        franchise=(
            EntityRef(public_id=title.franchise.public_id, name=title.franchise.name)
            if title.franchise
            else None
        ),
        machines=machines,
        series=series,
        credits=credits,
        agreed_specs=agreed_specs,
        related_titles=related_titles,
        media=media,
        model_detail=model_detail,
    )


def _title_models_prefetch() -> Prefetch[str, Any, str]:
    return Prefetch(
        "machine_models",
        queryset=MachineModel.objects.active()
        .filter(variant_of__isnull=True)
        .select_related(
            "corporate_entity__manufacturer",
            "technology_generation",
            "technology_subgeneration",
            "display_type",
            "display_subtype",
            "system",
            "cabinet",
            "game_format",
            "converted_from__title",
            "remake_of__title",
        )
        .prefetch_related(
            "themes",
            "gameplay_features",
            Prefetch(
                "machinemodelgameplayfeature_set",
                queryset=MachineModelGameplayFeature.objects.select_related(
                    "gameplayfeature"
                ),
            ),
            "reward_types",
            "tags",
            "credits__person",
            "credits__role",
            "variants",
            media_prefetch(),
        )
        .order_by("year", "name"),
    )


def _detail_qs() -> QuerySet[Title]:
    prefetches: list[str | Prefetch[Any, Any, Any]] = [
        _title_models_prefetch(),
        "abbreviations",
        claims_prefetch(),
    ]
    return (
        Title.objects.active()
        .select_related("franchise", "series")
        .prefetch_related(*prefetches)
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

titles_router = Router(tags=["titles"])


class TitleListPagination(NamedPageNumberPagination):
    response_name = "TitleListSchema"


@titles_router.get("/", response=list[TitleListItemSchema])
@paginate(TitleListPagination, page_size=DEFAULT_PAGE_SIZE)
def list_titles(request: HttpRequest, display: str = "") -> list[TitleListItemSchema]:
    qs = Title.objects.active().annotate(
        model_count=Count(
            "machine_models",
            filter=Q(machine_models__variant_of__isnull=True)
            & active_status_q("machine_models"),
        )
    )
    if display:
        qs = qs.filter(machine_models__display_type__slug=display).distinct()
    qs = (
        qs.select_related("franchise", "series")
        .prefetch_related(_title_models_prefetch(), "abbreviations")
        .order_by("name")
    )
    min_rank = get_minimum_display_rank()
    titles = list(qs)
    media_by_model = fetch_model_media_map(
        first.pk
        for t in titles
        if (first := next(iter(t.machine_models.all()), None)) is not None
    )
    return [
        _serialize_title_list(t, min_rank=min_rank, media_by_model=media_by_model)
        for t in titles
    ]


@titles_router.get("/all/", response=list[TitleListItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_all_titles(request: HttpRequest) -> HttpResponse:
    """Return every title with facet data for client-side filtering.

    Performance-critical: this serializes ~6k titles with facet arrays
    aggregated from ~7k machine models.  The result is cached indefinitely
    and invalidated on data changes, so cold-cache rebuild speed matters.

    Strategy (instead of prefetch + ORM iteration):
    1. Annotate scalar card fields (manufacturer, year) via correlated
       subqueries so the DB does the work in one SQL statement.
    2. Use ``values_list`` instead of full ORM object instantiation to
       avoid Python-side hydration overhead for thousands of rows.
    3. Fetch M2M facet data (themes, features, credits, etc.) via bulk
       queries on through tables into ``dict`` lookup maps.
    4. Assemble the response dicts from the lookup maps.

    This reduces cold-cache rebuild from ~3.5s to ~0.5s locally
    (~30s to ~5s on production hardware).
    """
    response = get_cached_response(titles_all_key())
    if response is not None:
        return response

    # Cached once for the entire rebuild — avoids ~6k Constance DB lookups.
    min_rank = get_minimum_display_rank()

    # "First model" = earliest non-variant model by (year, name), used to
    # derive the title's display manufacturer, year, and thumbnail.
    first_model = (
        MachineModel.objects.filter(title=OuterRef("pk"), variant_of__isnull=True)
        .active()
        .order_by("year", "name")
    )
    title_rows = list(
        Title.objects.active()
        .annotate(
            model_count=Count(
                "machine_models",
                filter=Q(machine_models__variant_of__isnull=True)
                & active_status_q("machine_models"),
            ),
            latest_year=Max(
                "machine_models__year",
                filter=Q(machine_models__variant_of__isnull=True),
            ),
            primary_mfr_slug=Subquery(
                first_model.values("corporate_entity__manufacturer__slug")[:1]
            ),
            primary_mfr_name=Subquery(
                first_model.values("corporate_entity__manufacturer__name")[:1]
            ),
            primary_year=Subquery(first_model.values("year")[:1]),
            primary_model_id=Subquery(first_model.values("pk")[:1]),
            year_min=Min(
                "machine_models__year",
                filter=Q(machine_models__variant_of__isnull=True),
            ),
            ipdb_rating_max=Max(
                "machine_models__ipdb_rating",
                filter=Q(machine_models__variant_of__isnull=True),
            ),
            franchise_slug=F("franchise__slug"),
            franchise_name=F("franchise__name"),
            series_slug=F("series__slug"),
            series_name=F("series__name"),
        )
        .values_list(
            "id",
            "name",
            "slug",
            "model_count",
            "latest_year",
            "primary_mfr_slug",
            "primary_mfr_name",
            "primary_year",
            "primary_model_id",
            "year_min",
            "ipdb_rating_max",
            "franchise_slug",
            "franchise_name",
            "series_slug",
            "series_name",
            named=True,
        )
        .order_by(F("latest_year").desc(nulls_last=True), "name")
    )

    # --- Batch thumbnail fetch ---
    primary_model_ids = [r.primary_model_id for r in title_rows if r.primary_model_id]
    media_by_model = fetch_model_media_map(primary_model_ids)
    thumb_data: dict[int, str | None] = {}
    for mid, extra_data in MachineModel.objects.filter(
        id__in=primary_model_ids
    ).values_list("id", "extra_data"):
        thumb, _ = extract_image_urls(
            extra_data or {}, media_by_model.get(mid), min_rank=min_rank
        )
        thumb_data[mid] = thumb

    # --- Bulk abbreviations and series ---
    title_ids = [r.id for r in title_rows]

    title_abbrevs: dict[int, list[str]] = defaultdict(list)
    for tid, value in TitleAbbreviation.objects.filter(
        title_id__in=title_ids
    ).values_list("title_id", "value"):
        title_abbrevs[tid].append(value)

    # --- Bulk facet queries via through tables ---
    model_qs = MachineModel.objects.filter(
        title__isnull=False, variant_of__isnull=True
    ).active()

    title_model_map: dict[int, list[int]] = defaultdict(list)
    model_ids: set[int] = set()
    for title_id, model_id in model_qs.values_list("title_id", "id"):
        title_model_map[title_id].append(model_id)
        model_ids.add(model_id)

    model_tech_gen: dict[int, SlugName] = {}
    for mid, slug, name in model_qs.filter(
        technology_generation__isnull=False
    ).values_list("id", "technology_generation__slug", "technology_generation__name"):
        model_tech_gen[mid] = SlugName(slug, name)

    model_display: dict[int, SlugName] = {}
    for mid, slug, name in model_qs.filter(display_type__isnull=False).values_list(
        "id", "display_type__slug", "display_type__name"
    ):
        model_display[mid] = SlugName(slug, name)

    model_system: dict[int, SlugName] = {}
    for mid, slug, name in model_qs.filter(system__isnull=False).values_list(
        "id", "system__slug", "system__name"
    ):
        model_system[mid] = SlugName(slug, name)

    model_player_count: dict[int, int | None] = {}
    for mid, pc in model_qs.values_list("id", "player_count"):
        model_player_count[mid] = pc

    model_themes: dict[int, list[SlugName]] = defaultdict(list)
    for mid, slug, name in MachineModel.themes.through.objects.filter(
        machinemodel_id__in=model_ids
    ).values_list("machinemodel_id", "theme__slug", "theme__name"):
        model_themes[mid].append(SlugName(slug, name))

    model_gf: dict[int, list[SlugName]] = defaultdict(list)
    for mid, slug, name in MachineModel.gameplay_features.through.objects.filter(
        machinemodel_id__in=model_ids
    ).values_list(
        "machinemodel_id",
        "gameplayfeature__slug",
        "gameplayfeature__name",
    ):
        model_gf[mid].append(SlugName(slug, name))

    model_rt: dict[int, list[SlugName]] = defaultdict(list)
    for mid, slug, name in MachineModel.reward_types.through.objects.filter(
        machinemodel_id__in=model_ids
    ).values_list("machinemodel_id", "rewardtype__slug", "rewardtype__name"):
        model_rt[mid].append(SlugName(slug, name))

    model_persons: dict[int, list[SlugName]] = defaultdict(list)
    for mid, slug, name in Credit.objects.filter(model_id__in=model_ids).values_list(
        "model_id", "person__slug", "person__name"
    ):
        model_persons[mid].append(SlugName(slug, name))

    # --- Assembly ---
    # Build dicts directly (not TitleListItemSchema instances). The cache
    # stores JSON bytes, so handing Schemas to ``json.dumps`` would force a
    # round-trip via ``model_dump`` — exactly what the cache exists to avoid.
    # ``set_cached_response`` validates this dict shape against the response
    # Schema in DEBUG mode to catch drift; the prod path is raw ``json.dumps``.
    def _ref_dict(
        public_id: str | None, name: str | None
    ) -> dict[str, str | None] | None:
        return {"public_id": public_id, "name": name} if public_id else None

    result: list[dict[str, Any]] = []
    for r in title_rows:
        tid = r.id
        mids = title_model_map.get(tid, [])

        result.append(
            {
                "name": r.name,
                "slug": r.slug,
                "abbreviations": title_abbrevs.get(tid, []),
                "model_count": r.model_count,
                "manufacturer": _ref_dict(r.primary_mfr_slug, r.primary_mfr_name),
                "year": r.primary_year,
                "thumbnail_url": thumb_data.get(r.primary_model_id),
                "tech_generations": _dedup_facet_dicts(
                    model_tech_gen[mid] for mid in mids if mid in model_tech_gen
                ),
                "display_types": _dedup_facet_dicts(
                    model_display[mid] for mid in mids if mid in model_display
                ),
                "player_counts": sorted(
                    {
                        count
                        for mid in mids
                        if (count := model_player_count.get(mid)) is not None
                    }
                ),
                "systems": _dedup_facet_dicts(
                    model_system[mid] for mid in mids if mid in model_system
                ),
                "themes": _dedup_facet_dicts(
                    p for mid in mids for p in model_themes.get(mid, [])
                ),
                "gameplay_features": _dedup_facet_dicts(
                    p for mid in mids for p in model_gf.get(mid, [])
                ),
                "reward_types": _dedup_facet_dicts(
                    p for mid in mids for p in model_rt.get(mid, [])
                ),
                "persons": _dedup_facet_dicts(
                    p for mid in mids for p in model_persons.get(mid, [])
                ),
                "franchise": _ref_dict(r.franchise_slug, r.franchise_name),
                "series": _ref_dict(r.series_slug, r.series_name),
                "year_min": r.year_min,
                "year_max": r.latest_year,
                "ipdb_rating_max": (
                    float(r.ipdb_rating_max) if r.ipdb_rating_max else None
                ),
            }
        )
    return set_cached_response(titles_all_key(), _ALL_ADAPTER, result)


@titles_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: TitleDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_title_claims(
    request: HttpRequest, public_id: str, data: TitleClaimPatchSchema
) -> TitleDetailSchema:
    """Assert title-owned claims and return the refreshed title detail."""
    if not data.fields and data.abbreviations is None:
        raise_form_error("No changes provided.")

    title = get_object_or_404(
        Title.objects.active().prefetch_related("abbreviations"),
        **{Title.public_id_field: public_id},
    )

    # Name collisions are not DB-enforced (title names are not unique), so
    # renames must be checked against the same normalized-name rule the
    # create endpoint uses. Without this, a user could rename one title to
    # collide with another and bypass the invariant the create flow
    # establishes.
    if data.fields.get("name"):
        _assert_title_name_available(data.fields["name"], exclude_pk=title.pk)

    specs = (
        plan_scalar_field_claims(Title, data.fields, entity=title)
        if data.fields
        else []
    )

    if data.abbreviations is not None:
        specs.extend(plan_abbreviation_claims(title, data.abbreviations))

    if not specs:
        raise_form_error("No changes provided.")

    execute_claims(
        title,
        specs,
        user=request.user,
        action=ChangeSetAction.EDIT,
        note=data.note,
        citation=data.citation,
    )

    title = get_object_or_404(_detail_qs(), **{Title.public_id_field: title.public_id})
    return _serialize_title_detail(title)


@titles_router.post(
    "/",
    auth=django_auth,
    response={
        201: TitleDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_CREATE)
@rate_limited(CREATE_RATE_LIMIT_SPEC)
def create_title(
    request: HttpRequest, data: EntityCreateInputSchema
) -> Status[TitleDetailSchema]:
    """Create a new Title from a user-supplied name and slug.

    Writes a user ChangeSet with ``action=create`` and three claims — name,
    slug, and ``status="active"``. The status claim is written explicitly
    (rather than relying on the row default) so that Undo semantics and
    future delete flows have a symmetric claim to invert.

    Rate-limited per user. Staff bypass.
    """
    name = validate_name(data.name, max_length=MAX_CATALOG_NAME_LENGTH)
    slug = validate_slug_format(data.slug)
    _assert_title_name_available(name)
    assert_public_id_available(Title, slug)

    create_entity_with_claims(
        Title,
        row_kwargs={"name": name, "slug": slug, "status": "active"},
        claim_specs=[
            ClaimSpec(field_name="name", value=name),
            ClaimSpec(field_name="slug", value=slug),
            ClaimSpec(field_name="status", value="active"),
        ],
        user=request.user,
        note=data.note,
        citation=data.citation,
    )

    created = get_object_or_404(_detail_qs(), **{Title.public_id_field: slug})
    return Status(201, _serialize_title_detail(created))


@titles_router.post(
    "/{path:title_public_id}/models/",
    auth=django_auth,
    response={
        201: ModelDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_CREATE)
@rate_limited(CREATE_RATE_LIMIT_SPEC)
def create_model(
    request: HttpRequest, title_public_id: str, data: EntityCreateInputSchema
) -> Status[ModelDetailSchema]:
    """Create a new MachineModel under an existing Title.

    Writes a user ChangeSet with ``action=create`` and four claims — name,
    slug, ``status="active"``, and ``title`` (FK-by-slug). The title claim
    is explicit so that the model carries the same provenance for its
    parent as every other field.

    Rate-limited per user; shares the ``create`` bucket with Title Create.
    Staff bypass. Name collisions are scoped to the parent Title: two
    titles can legitimately share a model name (e.g. "Pro"). Slug
    uniqueness is global — the ``/models/{public_id}`` URL pattern requires it.
    """
    title = get_object_or_404(
        Title.objects.active(), **{Title.public_id_field: title_public_id}
    )

    name = validate_name(data.name, max_length=MAX_CATALOG_NAME_LENGTH)
    slug = validate_slug_format(data.slug)

    assert_name_available(
        MachineModel,
        name,
        normalize=normalize_catalog_name,
        scope_filter=Q(title_id=title.pk),
        friendly_label="model",
    )
    assert_public_id_available(MachineModel, slug)

    create_entity_with_claims(
        MachineModel,
        row_kwargs={
            "name": name,
            "slug": slug,
            "title": title,
            "status": "active",
        },
        claim_specs=[
            ClaimSpec(field_name="name", value=name),
            ClaimSpec(field_name="slug", value=slug),
            ClaimSpec(field_name="status", value="active"),
            # Title FK claim value uses the parent's public_id (defaults to
            # slug for slug-keyed models). Shape matches ingest's
            # MODEL_CLAIM_FIELDS["title"] ← entry["title_slug"] convention.
            ClaimSpec(field_name="title", value=title.public_id),
        ],
        user=request.user,
        note=data.note,
        citation=data.citation,
    )

    pm = get_object_or_404(_model_detail_qs(), **{MachineModel.public_id_field: slug})
    return Status(201, _serialize_model_detail(pm))


# ---------------------------------------------------------------------------
# Delete / restore
# ---------------------------------------------------------------------------


@titles_router.get(
    "/{path:public_id}/delete-preview/",
    auth=django_auth,
    response=TitleDeletePreviewSchema,
    tags=["private"],
)
def title_delete_preview(
    request: HttpRequest, public_id: str
) -> TitleDeletePreviewSchema:
    """Return the impact summary used by the delete confirmation screen.

    Includes counts for active child models and user ChangeSets that touch
    the title or any of its active models, plus any blocking referrers so
    the UI can refuse the action before it's attempted.
    """
    title = get_object_or_404(
        Title.objects.active(), **{Title.public_id_field: public_id}
    )
    plan = plan_soft_delete(title)
    # All entities in the plan are the ones we'd hide. Exclude the root Title
    # when counting Models; the response calls each out separately.
    model_pks = [e.pk for e in plan.entities_to_delete if isinstance(e, MachineModel)]
    # Skip the ChangeSet count query when blocked — the UI hides the impact
    # summary in that branch, so the number is never displayed.
    changeset_count = (
        0 if plan.is_blocked else count_entity_changesets(*plan.entities_to_delete)
    )
    return TitleDeletePreviewSchema(
        name=title.name,
        slug=title.slug,
        active_model_count=len(model_pks),
        changeset_count=changeset_count,
        blocked_by=[serialize_blocking_referrer(b) for b in plan.blockers],
    )


@titles_router.post(
    "/{path:public_id}/delete/",
    auth=django_auth,
    response={
        200: TitleDeleteResponseSchema,
        422: SoftDeleteBlockedSchema | AlreadyDeletedSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_DELETE)
@rate_limited(DELETE_RATE_LIMIT_SPEC)
def delete_title(
    request: HttpRequest, public_id: str, data: ChangeSetInputSchema
) -> TitleDeleteResponseSchema | Status[SoftDeleteBlockedSchema | AlreadyDeletedSchema]:
    """Soft-delete a Title and cascade to its active MachineModels.

    Writes a single user ChangeSet with ``action=delete`` containing one
    ``status=deleted`` claim per affected entity. Rate-limited per user on
    the ``delete`` bucket (5/day; staff bypass). Blocks with 422 when an
    active PROTECT referrer outside the cascade tree would be left
    dangling; the response body lists the referrers so the UI can explain.
    """
    title = get_object_or_404(
        Title.objects.active(), **{Title.public_id_field: public_id}
    )
    try:
        changeset, deleted = execute_soft_delete(
            title, user=request.user, note=data.note, citation=data.citation
        )
    except SoftDeleteBlockedError as exc:
        return Status(
            422,
            SoftDeleteBlockedSchema(
                detail="Cannot delete: active references would be left dangling.",
                blocked_by=[serialize_blocking_referrer(b) for b in exc.blockers],
            ),
        )

    if changeset is None:
        # Already soft-deleted; shouldn't happen because of the .active()
        # fetch above, but guard anyway.
        return Status(422, AlreadyDeletedSchema(detail="Title is already deleted."))

    affected_titles = [e.slug for e in deleted if isinstance(e, Title)]
    affected_models = [e.slug for e in deleted if isinstance(e, MachineModel)]
    return TitleDeleteResponseSchema(
        changeset_id=changeset.pk,
        affected_titles=affected_titles,
        affected_models=affected_models,
    )


@titles_router.post(
    "/{path:public_id}/restore/",
    auth=django_auth,
    response={
        200: TitleDetailSchema,
        422: ErrorDetailSchema,
        404: ErrorDetailSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_CREATE)
@rate_limited(CREATE_RATE_LIMIT_SPEC)
def restore_title(
    request: HttpRequest, public_id: str, data: ChangeSetInputSchema
) -> TitleDetailSchema | Status[ErrorDetailSchema]:
    """Write a fresh ``status=active`` claim on a soft-deleted Title.

    This is the "Restore" path (distinct from Undo, which inverts a
    specific delete ChangeSet). Restore does NOT bring child Models back —
    they keep their ``status=deleted`` claims until individually restored
    or the original delete ChangeSet is undone. Shares the ``create``
    rate-limit bucket (Restore is semantically a re-create).
    """
    # Bypass .active() — we're looking for soft-deleted titles.
    title = get_object_or_404(Title, **{Title.public_id_field: public_id})
    if title.status != "deleted":
        return Status(422, ErrorDetailSchema(detail="Title is not deleted."))

    execute_claims(
        title,
        [ClaimSpec(field_name="status", value="active")],
        user=request.user,
        action=ChangeSetAction.EDIT,
        note=data.note,
        citation=data.citation,
    )

    refreshed = get_object_or_404(_detail_qs(), **{Title.public_id_field: public_id})
    return _serialize_title_detail(refreshed)
