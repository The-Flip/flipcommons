"""Manufacturers router — list, detail, and claim-patch endpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Annotated, cast

from django.db.models import F, Min, Prefetch, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema
from ninja.params.functions import Query as QueryParam
from ninja.security import django_auth
from pydantic import Field, TypeAdapter

from apps.catalog.engine.rich_text import describe
from apps.claim_edit.claim_write import execute_claims, plan_scalar_field_claims
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.media.helpers import media_prefetch
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..cache import (
    get_cached_response,
    manufacturers_facets_key,
    set_cached_response,
)
from ..engine.entity_api.create import register_entity_create
from ..engine.entity_api.delete import register_entity_delete_restore
from ..engine.entity_api.own_media import own_media
from ..engine.query.constants import DEFAULT_PAGE_SIZE
from ..models import (
    CorporateEntity,
    CorporateEntityLocation,
    MachineModel,
    Manufacturer,
    OperatingStatus,
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
from ._typing import FacetOptionDict, HasModelCount
from .helpers import (
    collect_titles,
    model_year_bounds,
    serialize_locations,
)
from .images import (
    extract_image_urls,
    fetch_model_media_map,
)
from .schemas import (
    ClaimPatchSchema,
    CorporateEntityLocationSchema,
    EntityDetailSchema,
    FacetOptionSchema,
    OwnMediaSchema,
    RelatedTitleSchema,
    YearBoundsSchema,
)

# ---------------------------------------------------------------------------
# Listing page schemas (SSR /manufacturers)
# ---------------------------------------------------------------------------


class ManufacturerCardSchema(Schema):
    """A manufacturer in list results: name, slug, model count and a thumbnail."""

    # Slim by design — only the fields list rows render. Facet arrays live on the
    # page endpoint's ``filter_options``, so the list path skips the bulk facet
    # queries.
    name: str = Field(description="The manufacturer's display name.")
    slug: str = Field(description="The manufacturer's URL slug.")
    model_count: int = Field(
        0, description="Number of machine models from this manufacturer."
    )
    thumbnail_url: str | None = Field(
        None, description="URL of a thumbnail image, if available."
    )


class ManufacturerListPageSchema(Schema):
    """A page of manufacturers: ``items`` holds this page's rows; ``count`` is the
    total number of matching manufacturers across all pages."""

    items: list[ManufacturerCardSchema]
    count: int


class ManufacturerFilterQuerySchema(Schema):
    """Every /manufacturers filter dimension as query params — one vocabulary end to
    end (URL ⇄ this schema ⇄ ``MfrFilters``). All facets are single-value (no
    titles-style repeated multi-value params)."""

    q: str = Field(
        "",
        description=(
            "Free-text search. Accent- and case-insensitive substring match against "
            "the manufacturer's name and aliases, plus the names and aliases of its "
            "corporate entities and their locations."
        ),
    )
    location: str | None = Field(
        None,
        description=(
            "Location path. Also matches manufacturers located anywhere beneath it."
        ),
    )
    person: str | None = Field(
        None,
        description=(
            "Person slug (see `GET /api/people/`). Matches manufacturers whose "
            "machines this person is credited on."
        ),
    )
    tech_gen: str | None = Field(
        None,
        description=(
            "Technology-generation slug (see `GET /api/technology-generations/`)."
        ),
    )
    year_min: int | None = Field(
        None, description="Earliest machine production year, inclusive."
    )
    year_max: int | None = Field(
        None, description="Latest machine production year, inclusive."
    )

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
    year_of_first_model: int | None
    year_of_last_model: int | None
    operating_status: OperatingStatus
    locations: list[CorporateEntityLocationSchema]


class ManufacturerSystemSchema(Schema):
    name: str
    public_id: str


class ManufacturerPersonSchema(Schema):
    name: str
    public_id: str
    roles: list[str] = []


class ManufacturerDetailSchema(EntityDetailSchema, OwnMediaSchema):
    slug: str
    year_of_first_model: int | None = None
    year_of_last_model: int | None = None
    operating_status: OperatingStatus = OperatingStatus.UNKNOWN
    logo_url: str | None = None
    website: str = ""
    opdb_manufacturer_id: int | None = None
    wikidata_id: str | None = None
    entities: list[ManufacturerCorporateEntitySchema]
    titles: list[RelatedTitleSchema]
    systems: list[ManufacturerSystemSchema]
    persons: list[ManufacturerPersonSchema] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _PersonAccum:
    """Per-person bookkeeping while walking credits in the detail serializer."""

    name: str
    roles: set[str] = field(default_factory=set)


def _serialize_mfr_entity(e: CorporateEntity) -> ManufacturerCorporateEntitySchema:
    """One corporate entity in the manufacturer detail's ``entities`` list.

    Expects ``e.models`` prefetched to non-variant active models (see
    ``_manufacturer_qs``)."""
    bounds = model_year_bounds(e.models.all())
    return ManufacturerCorporateEntitySchema(
        name=e.name,
        public_id=e.public_id,
        year_of_first_model=bounds.first,
        year_of_last_model=bounds.last,
        operating_status=OperatingStatus(e.operating_status),
        locations=serialize_locations(e),
    )


@own_media(Manufacturer)
def _serialize_manufacturer_detail(mfr: Manufacturer) -> ManufacturerDetailSchema:
    """Serialize a Manufacturer into the detail response schema.

    Expects *mfr* to have been fetched with prefetch_related for entities,
    non_variant_models, credits, and claims (to_attr="active_claims").
    """
    # Collect persons with roles across all entities' model credits.
    person_roles: dict[str, _PersonAccum] = {}

    for e in mfr.entities.all():
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
    mfr_bounds = model_year_bounds(all_models)

    return ManufacturerDetailSchema(
        name=mfr.name,
        public_id=mfr.public_id,
        last_modified=mfr.last_modified,
        slug=mfr.slug,
        description=describe(mfr),
        year_of_first_model=mfr_bounds.first,
        year_of_last_model=mfr_bounds.last,
        operating_status=OperatingStatus.rollup(
            e.operating_status for e in mfr.entities.all()
        ),
        logo_url=mfr.logo_url,
        website=mfr.website,
        opdb_manufacturer_id=mfr.opdb_manufacturer_id,
        wikidata_id=mfr.wikidata_id,
        entities=[_serialize_mfr_entity(e) for e in mfr.entities.all()],
        titles=collect_titles(all_models, media_by_model=media_by_model),
        systems=[
            ManufacturerSystemSchema(name=s.name, public_id=s.public_id)
            for s in mfr.systems.all()
        ],
        persons=persons,
    )


def _manufacturer_qs() -> QuerySet[Manufacturer]:
    return Manufacturer.objects.active().prefetch_related(
        Prefetch(
            "entities",
            # Order companies by when they began producing (earliest active,
            # non-variant model year), undated makers last — mirroring the
            # production-derived range now shown for each. The Min filter matches
            # the prefetched ``models`` scope so the sort key equals the displayed
            # ``year_of_first_model``.
            queryset=CorporateEntity.objects.active()
            .annotate(
                _first_model_year=Min(
                    "models__year",
                    filter=Q(models__variant_of__isnull=True)
                    & active_status_q("models"),
                )
            )
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
            .order_by(F("_first_model_year").asc(nulls_last=True), "name"),
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
    """Per-manufacturer thumbnail URL, batched over *manufacturer_ids*.

    Picks the newest active non-variant model that has ``extra_data`` (``year`` DESC
    nulls-last, then ``name``, first-wins), then the uploaded-backglass-preferred /
    ``extra_data`` fallback image at ``min_rank`` (the licensing gate that drops
    below-rank images — so the card is audience-variant). Scoped to the given ids so
    the batch can't scan every model in the catalog."""
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
    request: HttpRequest,
    filters: Query[ManufacturerFilterQuerySchema],
    page: Annotated[int, QueryParam(1, description="Page number, 1-based.")] = 1,
) -> ManufacturerListPageSchema:
    """Manufacturers, paginated. Narrow with the filters and the search (``q``).
    Ordered by model count, then alphabetically.

    All filters combine with AND."""
    # Sliced at SQL via ``ordered`` + LIMIT/OFFSET so only the requested page is
    # serialized — never ``list(qs)`` over the whole catalog.
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
