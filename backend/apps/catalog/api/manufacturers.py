"""Manufacturers router — list, detail, and claim-patch endpoints."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, cast

from django.db.models import Count, F, Max, Min, Prefetch, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Query, Router, Schema
from ninja.decorators import decorate_view
from ninja.security import django_auth
from pydantic import TypeAdapter

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.media.helpers import all_media
from apps.media.schemas import UploadedMediaSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..cache import (
    get_cached_response,
    manufacturers_all_key,
    manufacturers_facets_key,
    set_cached_response,
)
from ..models import (
    CorporateEntity,
    CorporateEntityAlias,
    CorporateEntityLocation,
    Credit,
    MachineModel,
    Manufacturer,
    ManufacturerAlias,
    System,
)
from ._manufacturer_facets import (
    FacetOption,
    FilterOptions,
    MfrFilters,
    facet_counts,
    ordered,
    query_count,
)
from ._typing import FacetOptionDict, HasModelCount, HasYearRange, SlugName
from .constants import DEFAULT_PAGE_SIZE
from .edit_claims import execute_claims, plan_scalar_field_claims
from .entity_crud import register_entity_create, register_entity_delete_restore
from .helpers import (
    collect_titles,
    serialize_locations,
)
from .images import (
    extract_image_urls,
    fetch_model_media_map,
    media_prefetch,
    serialize_uploaded_media,
)
from .rich_text import describe
from .schemas import (
    CatalogDetailSchema,
    ClaimPatchSchema,
    CorporateEntityLocationSchema,
    EntityRef,
    FacetOptionSchema,
    RelatedTitleSchema,
    YearBoundsSchema,
)
from .titles import _dedup_facet_dicts


class ManufacturerGridItemSchema(Schema):
    name: str
    slug: str
    model_count: int = 0
    thumbnail_url: str | None = None
    search_text: str | None = None
    locations: list[EntityRef] = []
    year_min: int | None = None
    year_max: int | None = None
    persons: list[EntityRef] = []
    tech_generations: list[EntityRef] = []


_ALL_ADAPTER: TypeAdapter[list[ManufacturerGridItemSchema]] = TypeAdapter(
    list[ManufacturerGridItemSchema]
)


# ---------------------------------------------------------------------------
# Listing page schemas (SSR /manufacturers)
# ---------------------------------------------------------------------------


class ManufacturerCardSchema(Schema):
    """Slim card for the /manufacturers grid and every infinite-scroll page — only
    what ``ManufacturerCard`` renders. No facet arrays (those live on the page
    endpoint's ``filter_options``), so the list path skips the bulk facet queries."""

    name: str
    slug: str
    model_count: int = 0
    thumbnail_url: str | None = None


class ManufacturerListPageSchema(Schema):
    """``{items, count}`` page of cards — the wire shape ``createPaginatedLoader``
    expects (it derives has_more from items.length < count)."""

    items: list[ManufacturerCardSchema]
    count: int


class ManufacturerFilterQuerySchema(Schema):
    """Every /manufacturers filter dimension as query params — one vocabulary end to
    end (URL ⇄ this schema ⇄ ``MfrFilters``). All facets are single-value (no
    titles-style repeated multi-value params)."""

    q: str = ""
    location: str | None = None
    person: str | None = None
    tech_gen: str | None = None
    year_min: int | None = None
    year_max: int | None = None

    def to_filters(self) -> MfrFilters:
        return MfrFilters(
            q=self.q or "",
            location=self.location,
            person=self.person,
            tech_gen=self.tech_gen,
            year_min=self.year_min,
            year_max=self.year_max,
        )


# --- Facet option lists (GET /api/pages/manufacturers) ---

# ``FacetOptionSchema`` (`{public_id, name, count}`) and ``YearBoundsSchema`` are the
# entity-agnostic facet wire types, shared from ``schemas.py`` (see their docstrings
# there) so every listing page emits one OpenAPI component per shape.


class ManufacturerFilterOptionsSchema(Schema):
    location: list[FacetOptionSchema] = []
    person: list[FacetOptionSchema] = []
    tech_gen: list[FacetOptionSchema] = []
    year: YearBoundsSchema = YearBoundsSchema()


class ManufacturerFacetsPageSchema(Schema):
    """The /manufacturers page endpoint payload — facet options plus the query-only
    count (cards come from ``GET /api/manufacturers/``)."""

    filter_options: ManufacturerFilterOptionsSchema
    # Manufacturers matching ``q`` alone, ignoring active facets; null when there is
    # no ``q``. Drives the "create this manufacturer?" prompt.
    query_count: int | None = None


_FACETS_ADAPTER: TypeAdapter[ManufacturerFacetsPageSchema] = TypeAdapter(
    ManufacturerFacetsPageSchema
)


class ManufacturerCorporateEntitySchema(Schema):
    name: str
    public_id: str
    year_start: int | None
    year_end: int | None
    locations: list[CorporateEntityLocationSchema]


class ManufacturerSystemSchema(Schema):
    name: str
    public_id: str


class ManufacturerPersonSchema(Schema):
    name: str
    public_id: str
    roles: list[str] = []


class ManufacturerDetailSchema(CatalogDetailSchema):
    slug: str
    year_start: int | None = None
    year_end: int | None = None
    logo_url: str | None = None
    website: str = ""
    opdb_manufacturer_id: int | None = None
    wikidata_id: str | None = None
    entities: list[ManufacturerCorporateEntitySchema]
    titles: list[RelatedTitleSchema]
    systems: list[ManufacturerSystemSchema]
    persons: list[ManufacturerPersonSchema] = []
    uploaded_media: list[UploadedMediaSchema] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _PersonAccum:
    """Per-person bookkeeping while walking credits in the detail serializer."""

    name: str
    roles: set[str] = field(default_factory=set)


def _serialize_manufacturer_detail(mfr: Manufacturer) -> ManufacturerDetailSchema:
    """Serialize a Manufacturer into the detail response schema.

    Expects *mfr* to have been fetched with prefetch_related for entities,
    non_variant_models, credits, and claims (to_attr="active_claims").
    """
    # Collect persons with roles and compute year range across entities.
    person_roles: dict[str, _PersonAccum] = {}
    year_starts: list[int] = []
    year_ends: list[int] = []

    for e in mfr.entities.all():
        if e.year_start is not None:
            year_starts.append(e.year_start)
        if e.year_end is not None:
            year_ends.append(e.year_end)
        for m in e.models.all():
            for credit in m.credits.all():
                p = credit.person
                if p.public_id not in person_roles:
                    person_roles[p.public_id] = _PersonAccum(name=p.name)
                if credit.role:
                    person_roles[p.public_id].roles.add(credit.role.name)

    persons = sorted(
        (
            ManufacturerPersonSchema(
                name=accum.name, public_id=public_id, roles=sorted(accum.roles)
            )
            for public_id, accum in person_roles.items()
        ),
        key=lambda p: p.name,
    )

    all_models = [m for e in mfr.entities.all() for m in e.models.all()]
    media_by_model = fetch_model_media_map(m.pk for m in all_models)

    return ManufacturerDetailSchema(
        name=mfr.name,
        public_id=mfr.public_id,
        last_modified=mfr.last_modified,
        slug=mfr.slug,
        description=describe(mfr),
        year_start=min(year_starts) if year_starts else None,
        year_end=max(year_ends) if year_ends else None,
        logo_url=mfr.logo_url,
        website=mfr.website,
        opdb_manufacturer_id=mfr.opdb_manufacturer_id,
        wikidata_id=mfr.wikidata_id,
        entities=[
            ManufacturerCorporateEntitySchema(
                name=e.name,
                public_id=e.public_id,
                year_start=e.year_start,
                year_end=e.year_end,
                locations=serialize_locations(e),
            )
            for e in mfr.entities.all()
        ],
        titles=collect_titles(all_models, media_by_model=media_by_model),
        systems=[
            ManufacturerSystemSchema(name=s.name, public_id=s.public_id)
            for s in mfr.systems.all()
        ],
        persons=persons,
        uploaded_media=serialize_uploaded_media(all_media(mfr)),
    )


def _manufacturer_qs() -> QuerySet[Manufacturer]:
    return Manufacturer.objects.active().prefetch_related(
        Prefetch(
            "entities",
            queryset=CorporateEntity.objects.active()
            .prefetch_related(
                Prefetch(
                    "locations",
                    queryset=CorporateEntityLocation.objects.select_related(
                        "location__parent__parent__parent"
                    ),
                ),
                Prefetch(
                    "models",
                    queryset=MachineModel.objects.active()
                    .filter(variant_of__isnull=True)
                    .select_related("technology_generation", "title")
                    .prefetch_related("credits__person", "credits__role")
                    .order_by(F("year").desc(nulls_last=True), "name"),
                ),
            )
            .order_by("year_start"),
        ),
        Prefetch("systems", queryset=System.objects.active().order_by("name")),
        claims_prefetch(),
        media_prefetch(),
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

manufacturers_router = Router(tags=["manufacturers"])


def _page_thumbnails(
    manufacturer_ids: list[int], *, min_rank: int
) -> dict[int, str | None]:
    """Per-manufacturer thumbnail URL, batched over **just this page's** manufacturers.

    Parity with ``/all/`` ([list_all_manufacturers]): the newest active non-variant
    model that has ``extra_data`` (``year`` DESC nulls-last, then ``name``, first-wins),
    then the uploaded-backglass-preferred / ``extra_data`` fallback image at
    ``min_rank`` (the licensing gate that drops below-rank images — so the card is
    audience-variant). Scoped to the sliced ids so the batch can't scan every model in
    the catalog the way ``/all/`` (which has no page to bound) does."""
    if not manufacturer_ids:
        return {}
    thumb_model: dict[int, int] = {}
    for mfr_id, model_id in (
        MachineModel.objects.active()
        .filter(
            variant_of__isnull=True,
            extra_data__isnull=False,
            corporate_entity__manufacturer_id__in=manufacturer_ids,
        )
        .order_by(F("year").desc(nulls_last=True), "name")
        .values_list("corporate_entity__manufacturer_id", "id")
    ):
        thumb_model.setdefault(mfr_id, model_id)
    thumb_models = {
        m.pk: m
        for m in MachineModel.objects.filter(id__in=thumb_model.values()).only(
            "id", "extra_data"
        )
    }
    thumb_media = fetch_model_media_map(thumb_model.values())

    thumbnails: dict[int, str | None] = {}
    for mfr_id, model_id in thumb_model.items():
        tm = thumb_models.get(model_id)
        if tm is None:
            continue
        url, _ = extract_image_urls(
            tm.extra_data or {}, thumb_media.get(tm.pk), min_rank=min_rank
        )
        thumbnails[mfr_id] = url
    return thumbnails


@manufacturers_router.get("/", response=ManufacturerListPageSchema)
def list_manufacturers(
    request: HttpRequest, filters: Query[ManufacturerFilterQuerySchema], page: int = 1
) -> ManufacturerListPageSchema:
    """One page of manufacturer cards for the SSR grid (page 1) and infinite scroll
    (2…N). Slices at SQL via ``ordered`` + LIMIT/OFFSET — only the requested page is
    serialized (never ``list(qs)`` over the whole catalog)."""
    f = filters.to_filters()
    rows = ordered(f)
    count = rows.count()
    size = DEFAULT_PAGE_SIZE
    start = (max(page, 1) - 1) * size
    manufacturers = list(rows[start : start + size])
    min_rank = get_minimum_display_rank()
    thumbnails = _page_thumbnails([m.pk for m in manufacturers], min_rank=min_rank)
    return ManufacturerListPageSchema(
        items=[
            ManufacturerCardSchema(
                name=m.name,
                slug=m.slug,
                model_count=cast(HasModelCount, m).model_count,
                thumbnail_url=thumbnails.get(m.pk),
            )
            for m in manufacturers
        ],
        count=count,
    )


# ---------------------------------------------------------------------------
# Global search — the Manufacturers section of GET /api/pages/search
# ---------------------------------------------------------------------------


class ManufacturerSearchSectionSchema(Schema):
    """The Manufacturers section of the global ``/search`` page: up to 10 cards plus
    a ``has_more`` flag (the section caps at 10; the frontend links to
    ``/manufacturers?q=`` for the rest). ``items`` reuses the listing card so a section
    row matches the ``/manufacturers`` grid exactly."""

    items: list[ManufacturerCardSchema]
    has_more: bool


def manufacturer_search_section(
    q: str, *, min_rank: int
) -> ManufacturerSearchSectionSchema:
    """Top ≤10 manufacturer cards matching ``q``, composing the **ordered** listing
    queryset + card serializer so results match ``/manufacturers?q=`` exactly. Slices
    ``[:11]`` to detect ">10" without a second ``count()``."""
    rows = list(ordered(MfrFilters(q=q))[:11])
    items = rows[:10]
    thumbnails = _page_thumbnails([m.pk for m in items], min_rank=min_rank)
    return ManufacturerSearchSectionSchema(
        items=[
            ManufacturerCardSchema(
                name=m.name,
                slug=m.slug,
                model_count=cast(HasModelCount, m).model_count,
                thumbnail_url=thumbnails.get(m.pk),
            )
            for m in items
        ],
        has_more=len(rows) > 10,
    )


# ---------------------------------------------------------------------------
# Listing page — facet options (GET /api/pages/manufacturers)
# ---------------------------------------------------------------------------


def _facet_option_dicts(options: list[FacetOption]) -> list[FacetOptionDict]:
    return [
        {"public_id": o.public_id, "name": o.name, "count": o.count} for o in options
    ]


def _filter_options_payload(opts: FilterOptions) -> dict[str, object]:
    """``FilterOptions`` → the JSON-able dict the page endpoint returns (and caches).

    Plain dicts (not Schema instances) so the cache's ``json.dumps`` fast path and the
    live path stay byte-equivalent (see ``set_cached_response``)."""
    return {
        "filter_options": {
            "location": _facet_option_dicts(opts.location),
            "person": _facet_option_dicts(opts.person),
            "tech_gen": _facet_option_dicts(opts.tech_gen),
            "year": {"min": opts.year.min, "max": opts.year.max},
        }
    }


def manufacturer_facets_response(filters: MfrFilters) -> HttpResponse:
    """Build the ``/api/pages/manufacturers`` response. The no-filter payload is cached
    (hottest path, static between catalog edits); filtered requests compute live.

    The cache key is audience-scoped and the live branch sets ``Vary: Cookie`` for
    **consistency/insurance**, not because the payload varies by audience: the facet
    counts gate on ``active_status_q`` (status only — active/deleted), carrying no
    ``min_rank``/licensing input, so they are audience-invariant today (only the cards'
    thumbnails are audience-variant). Audience scoping is cheap insurance if a
    licensing-gated input is ever added."""
    if filters == MfrFilters():
        cached = get_cached_response(manufacturers_facets_key())
        if cached is not None:
            return cached
        # Compute only on a miss. The no-filter path has no `q`, so `query_count` is
        # always null here.
        payload = _filter_options_payload(facet_counts(filters))
        payload["query_count"] = None
        return set_cached_response(manufacturers_facets_key(), _FACETS_ADAPTER, payload)
    payload = _filter_options_payload(facet_counts(filters))
    payload["query_count"] = query_count(filters)
    json_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    response = HttpResponse(json_bytes, content_type="application/json")
    response["Vary"] = "Cookie"
    return response


@manufacturers_router.get("/all/", response=list[ManufacturerGridItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_all_manufacturers(
    request: HttpRequest,
) -> HttpResponse | list[dict[str, Any]]:
    """Return every manufacturer with facet data for client-side filtering.

    Performance-critical: uses bulk queries and lookup maps instead of
    deep prefetch + Python iteration.  See ``list_all_titles`` for the
    full explanation of this pattern.
    """
    response = get_cached_response(manufacturers_all_key())
    if response is not None:
        return response

    min_rank = get_minimum_display_rank()

    # --- Main query with annotations ---
    manufacturers = list(
        Manufacturer.objects.active()
        .annotate(
            model_count=Count(
                "entities__models",
                filter=Q(entities__models__variant_of__isnull=True)
                & active_status_q("entities__models"),
            ),
            year_min=Min(
                "entities__models__year",
                filter=Q(entities__models__variant_of__isnull=True)
                & active_status_q("entities__models"),
            ),
            year_max=Max(
                "entities__models__year",
                filter=Q(entities__models__variant_of__isnull=True)
                & active_status_q("entities__models"),
            ),
        )
        .order_by("-model_count")
    )

    # --- Batch thumbnail: newest model with extra_data per manufacturer ---
    mfr_thumb_model: dict[int, int] = {}
    for mfr_id, model_id in (
        MachineModel.objects.active()
        .filter(
            variant_of__isnull=True,
            extra_data__isnull=False,
            corporate_entity__manufacturer__isnull=False,
        )
        .order_by(F("year").desc(nulls_last=True), "name")
        .values_list("corporate_entity__manufacturer_id", "id")
    ):
        if mfr_id not in mfr_thumb_model:
            mfr_thumb_model[mfr_id] = model_id
    thumb_models = {
        m.pk: m
        for m in MachineModel.objects.filter(id__in=mfr_thumb_model.values()).only(
            "id", "extra_data"
        )
    }
    thumb_media = fetch_model_media_map(mfr_thumb_model.values())

    # --- Bulk search text + facet data per manufacturer ---
    mfr_ids = {m.pk for m in manufacturers}

    # Entity names per manufacturer
    mfr_entity_names: dict[int, list[str]] = defaultdict(list)
    mfr_entity_ids: dict[int, list[int]] = defaultdict(list)
    for eid, mfr_id, ename in CorporateEntity.objects.active().values_list(
        "id", "manufacturer_id", "name"
    ):
        if mfr_id in mfr_ids:
            mfr_entity_names[mfr_id].append(ename)
            mfr_entity_ids[mfr_id].append(eid)

    all_entity_ids = {eid for eids in mfr_entity_ids.values() for eid in eids}

    # Aliases per entity → grouped by manufacturer
    entity_to_mfr: dict[int, int] = {}
    for mfr_id, eids in mfr_entity_ids.items():
        for eid in eids:
            entity_to_mfr[eid] = mfr_id

    mfr_ce_alias_names: dict[int, list[str]] = defaultdict(list)
    for eid, aval in CorporateEntityAlias.objects.filter(
        corporate_entity_id__in=all_entity_ids
    ).values_list("corporate_entity_id", "value"):
        mid = entity_to_mfr.get(eid)
        if mid:
            mfr_ce_alias_names[mid].append(aval)

    # Manufacturer's own aliases — must contribute to search_text so the UI's
    # "no results → create?" gate stays aligned with ``assert_name_available``,
    # which walks the ``aliases`` reverse relation and blocks alias-collision
    # creates at the API layer.
    mfr_brand_alias_names: dict[int, list[str]] = defaultdict(list)
    for mid, aval in ManufacturerAlias.objects.filter(
        manufacturer_id__in=mfr_ids
    ).values_list("manufacturer_id", "value"):
        mfr_brand_alias_names[mid].append(aval)

    # Locations per manufacturer (with hierarchy)
    mfr_location_names: dict[int, list[str]] = defaultdict(list)
    mfr_location_refs: dict[int, dict[str, str]] = defaultdict(dict)
    for eid, loc_path, loc_name, p1n, p1p, p2n, p2p, p3n, p3p, p4n, p4p in (
        CorporateEntityLocation.objects.filter(corporate_entity_id__in=all_entity_ids)
        .select_related("location__parent__parent__parent__parent")
        .values_list(
            "corporate_entity_id",
            "location__location_path",
            "location__name",
            "location__parent__name",
            "location__parent__location_path",
            "location__parent__parent__name",
            "location__parent__parent__location_path",
            "location__parent__parent__parent__name",
            "location__parent__parent__parent__location_path",
            "location__parent__parent__parent__parent__name",
            "location__parent__parent__parent__parent__location_path",
        )
    ):
        mid = entity_to_mfr.get(eid)
        if not mid:
            continue
        for name, path in (
            (loc_name, loc_path),
            (p1n, p1p),
            (p2n, p2p),
            (p3n, p3p),
            (p4n, p4p),
        ):
            if name:
                mfr_location_names[mid].append(name)
            if path and name and path not in mfr_location_refs[mid]:
                mfr_location_refs[mid][path] = name

    # Tech generations per manufacturer (via models)
    mfr_tech_gens: dict[int, list[SlugName]] = defaultdict(list)
    for mfr_id, tg_slug, tg_name in (
        MachineModel.objects.active()
        .filter(
            variant_of__isnull=True,
            technology_generation__isnull=False,
            corporate_entity__manufacturer_id__in=mfr_ids,
        )
        .values_list(
            "corporate_entity__manufacturer_id",
            "technology_generation__slug",
            "technology_generation__name",
        )
        .distinct()
    ):
        mfr_tech_gens[mfr_id].append(SlugName(tg_slug, tg_name))

    # Persons per manufacturer (via model credits)
    mfr_persons: dict[int, list[SlugName]] = defaultdict(list)
    for mfr_id, p_slug, p_name in (
        Credit.objects.filter(
            model__variant_of__isnull=True,
            model__corporate_entity__manufacturer_id__in=mfr_ids,
        )
        .values_list(
            "model__corporate_entity__manufacturer_id",
            "person__slug",
            "person__name",
        )
        .distinct()
    ):
        mfr_persons[mfr_id].append(SlugName(p_slug, p_name))

    # --- Assembly ---
    result = []
    for mfr in manufacturers:
        mfr_id = mfr.pk
        model_count = cast(HasModelCount, mfr).model_count
        year_min = cast(HasYearRange, mfr).year_min
        year_max = cast(HasYearRange, mfr).year_max
        search_parts: list[str] = []
        search_parts.extend(mfr_brand_alias_names.get(mfr_id, []))
        search_parts.extend(mfr_entity_names.get(mfr_id, []))
        search_parts.extend(mfr_ce_alias_names.get(mfr_id, []))
        search_parts.extend(mfr_location_names.get(mfr_id, []))

        thumb = None
        tm_id = mfr_thumb_model.get(mfr_id)
        tm = thumb_models.get(tm_id) if tm_id else None
        if tm:
            thumb, _ = extract_image_urls(
                tm.extra_data or {},
                thumb_media.get(tm.pk),
                min_rank=min_rank,
            )

        loc_refs_map = mfr_location_refs.get(mfr_id, {})
        locations = [
            {"public_id": path, "name": name} for path, name in loc_refs_map.items()
        ]

        result.append(
            {
                "name": mfr.name,
                "slug": mfr.slug,
                "model_count": model_count,
                "thumbnail_url": thumb,
                "search_text": (" | ".join(search_parts) if search_parts else None),
                "locations": locations,
                "year_min": year_min,
                "year_max": year_max,
                "persons": _dedup_facet_dicts(mfr_persons.get(mfr_id, [])),
                "tech_generations": _dedup_facet_dicts(mfr_tech_gens.get(mfr_id, [])),
            }
        )
    return set_cached_response(manufacturers_all_key(), _ALL_ADAPTER, result)


@manufacturers_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: ManufacturerDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_manufacturer_claims(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> ManufacturerDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    mfr = get_object_or_404(
        Manufacturer.objects.active(), **{Manufacturer.public_id_field: public_id}
    )

    specs = plan_scalar_field_claims(Manufacturer, data.fields, entity=mfr)

    execute_claims(
        mfr, specs, user=request.user, note=data.note, citation=data.citation
    )

    mfr = get_object_or_404(_manufacturer_qs(), slug=mfr.slug)
    return _serialize_manufacturer_detail(mfr)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------

register_entity_create(
    manufacturers_router,
    Manufacturer,
    detail_qs=_manufacturer_qs,
    serialize_detail=_serialize_manufacturer_detail,
    response_schema=ManufacturerDetailSchema,
)
register_entity_delete_restore(
    manufacturers_router,
    Manufacturer,
    detail_qs=_manufacturer_qs,
    serialize_detail=_serialize_manufacturer_detail,
    response_schema=ManufacturerDetailSchema,
)
