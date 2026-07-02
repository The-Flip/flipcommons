"""Systems router — list, detail, and claims endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, cast

from django.db import models
from django.db.models import Count, F, Max, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.params.functions import Query as QueryParam
from ninja.responses import Status
from ninja.security import django_auth
from pydantic import Field

from apps.catalog.engine.naming import normalize_catalog_name
from apps.catalog.engine.rich_text import describe
from apps.claim_edit.claim_write import (
    ClaimSpec,
    execute_claims,
    plan_scalar_field_claims,
)
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.exceptions import StructuredValidationError
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    EDIT_RATE_LIMIT_SPEC,
    rate_limited,
)

from ..engine.entity_api.create import (
    assert_name_available,
    assert_public_id_available,
    create_entity_with_claims,
    validate_name,
    validate_slug_format,
)
from ..engine.entity_api.delete import register_entity_delete_restore
from ..engine.entity_api.listing import paginated_list_response
from ..engine.query.constants import NameQuery, PageParam
from ..models import MachineModel, Manufacturer, System
from ._typing import HasModelCount
from .images import extract_image_urls, fetch_model_media_map
from .schemas import (
    ClaimPatchSchema,
    EntityCreateInputSchema,
    EntityDetailSchema,
    EntityRef,
    RelatedTitleSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SystemListItemSchema(Schema):
    """A system in list results."""

    name: str = Field(description="The system's display name.")
    slug: str = Field(description="The system's URL slug.")
    manufacturer: EntityRef = Field(description="The manufacturer of this system.")
    model_count: int = Field(0, description="Number of machine models on this system.")


class SystemListSchema(Schema):
    """A page of systems: ``items`` holds this page's rows; ``count`` is the total
    number of matching systems across all pages."""

    items: list[SystemListItemSchema]
    count: int


class SystemCreateSchema(EntityCreateInputSchema):
    manufacturer_slug: str


class SystemDetailSchema(EntityDetailSchema):
    slug: str
    manufacturer: EntityRef
    technology_subgeneration: EntityRef | None = None
    titles: list[RelatedTitleSchema]
    sibling_systems: list[EntityRef] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _system_detail_qs() -> QuerySet[System]:
    return (
        System.objects.active()
        .select_related("manufacturer", "technology_subgeneration")
        .prefetch_related(
            claims_prefetch(),
            Prefetch(
                "machine_models",
                queryset=MachineModel.objects.active()
                .filter(variant_of__isnull=True)
                .select_related("corporate_entity__manufacturer", "title")
                .order_by(F("year").desc(nulls_last=True), "name"),
            ),
        )
    )


@dataclass
class _RelatedTitleAccum:
    name: str
    public_id: str
    year: int | None
    manufacturer_name: str | None
    thumbnail_url: str | None


def _serialize_system_detail(system: System) -> SystemDetailSchema:
    min_rank = get_minimum_display_rank()
    models_list = list(system.machine_models.all())
    media_by_model = fetch_model_media_map(m.pk for m in models_list)
    accum: dict[str, _RelatedTitleAccum] = {}
    for m in models_list:
        if m.title is None:
            continue
        key = m.title.slug
        thumbnail_url = extract_image_urls(
            m.extra_data or {}, media_by_model.get(m.pk), min_rank=min_rank
        )[0]
        if key not in accum:
            mfr = (
                m.corporate_entity.manufacturer
                if m.corporate_entity and m.corporate_entity.manufacturer
                else None
            )
            accum[key] = _RelatedTitleAccum(
                name=m.title.name,
                public_id=m.title.public_id,
                year=m.year,
                manufacturer_name=mfr.name if mfr else None,
                thumbnail_url=thumbnail_url,
            )
        elif accum[key].thumbnail_url is None and thumbnail_url:
            accum[key].thumbnail_url = thumbnail_url
    titles = [
        RelatedTitleSchema(
            name=a.name,
            public_id=a.public_id,
            year=a.year,
            manufacturer_name=a.manufacturer_name,
            thumbnail_url=a.thumbnail_url,
        )
        for a in accum.values()
    ]

    sibling_systems: list[EntityRef] = []
    if system.manufacturer:
        sibling_systems = [
            EntityRef(name=row["name"], public_id=row["slug"])
            for row in System.objects.active()
            .filter(manufacturer=system.manufacturer)
            .exclude(pk=system.pk)
            .annotate(latest_year=Max("machine_models__year"))
            .order_by(F("latest_year").desc(nulls_last=True), "name")
            .values("name", "slug")
        ]

    return SystemDetailSchema(
        name=system.name,
        public_id=system.public_id,
        last_modified=system.last_modified,
        slug=system.slug,
        description=describe(system),
        manufacturer=EntityRef(
            name=system.manufacturer.name,
            public_id=system.manufacturer.public_id,
        ),
        technology_subgeneration=(
            EntityRef(
                name=system.technology_subgeneration.name,
                public_id=system.technology_subgeneration.public_id,
            )
            if system.technology_subgeneration
            else None
        ),
        titles=titles,
        sibling_systems=sibling_systems,
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

systems_router = Router(tags=["systems"])


def _system_list_qs() -> QuerySet[System]:
    return (
        System.objects.active()
        .select_related("manufacturer")
        .annotate(
            model_count=Count(
                "machine_models",
                filter=Q(machine_models__variant_of__isnull=True)
                & active_status_q("machine_models"),
            )
        )
        .order_by("name")
    )


def _serialize_system_row(
    system: System, thumbnail: str | None = None
) -> SystemListItemSchema:
    return SystemListItemSchema(
        name=system.name,
        slug=system.slug,
        manufacturer=EntityRef(
            name=system.manufacturer.name, public_id=system.manufacturer.public_id
        ),
        model_count=cast(HasModelCount, system).model_count,
    )


@systems_router.get("/", response=SystemListSchema)
def list_systems(
    request: HttpRequest,
    q: NameQuery = "",
    manufacturer: Annotated[
        str | None,
        QueryParam(
            None,
            description=(
                "Manufacturer slug (see `GET /api/manufacturers/`). Narrows to "
                "systems from this manufacturer."
            ),
        ),
    ] = None,
    page: PageParam = 1,
) -> SystemListSchema:
    """Systems, paginated. Filter by manufacturer or search with ``q``. Ordered
    alphabetically."""
    qs = _system_list_qs()
    if manufacturer:
        qs = qs.filter(manufacturer__slug=manufacturer)
    result = paginated_list_response(
        qs,
        q=q,
        ordering=("name", "pk"),
        page=page,
        serialize_row=_serialize_system_row,
    )
    return SystemListSchema(items=result.items, count=result.total)


@systems_router.get("/all/", response=list[SystemListItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_all_systems(request: HttpRequest) -> list[SystemListItemSchema]:
    """Every system with its machine count, alphabetical and unpaginated."""
    # Reuses the paginated handler's queryset and row serializer so the two
    # presentations can't drift.
    return [_serialize_system_row(s) for s in _system_list_qs()]


@systems_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: SystemDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_system_claims(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> SystemDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    system = get_object_or_404(
        System.objects.active(), **{System.public_id_field: public_id}
    )
    specs = plan_scalar_field_claims(System, data.fields, entity=system)

    execute_claims(
        system, specs, user=request.user, note=data.note, citations=data.citations
    )

    system = get_object_or_404(_system_detail_qs(), slug=system.slug)
    return _serialize_system_detail(system)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------


@systems_router.post(
    "/",
    auth=django_auth,
    response={
        201: SystemDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_CREATE)
@rate_limited(CREATE_RATE_LIMIT_SPEC)
def create_system(
    request: HttpRequest, data: SystemCreateSchema
) -> Status[SystemDetailSchema]:
    """Create a new System.

    Required fields: ``name``, ``slug``, ``manufacturer_slug``. Optional
    ``technology_subgeneration`` is deferred to edit rather than required for
    minimum-viable create.

    Bespoke (rather than ``register_entity_create``) because System has a
    required non-URL-nested FK (manufacturer) which the shared registrar
    doesn't express. Uses the same building blocks.
    """
    name_field = System._meta.get_field("name")
    assert isinstance(name_field, models.Field)
    assert name_field.max_length is not None
    name = validate_name(data.name, max_length=name_field.max_length)
    slug = validate_slug_format(data.slug)

    manufacturer_slug = (data.manufacturer_slug or "").strip()
    if not manufacturer_slug:
        raise StructuredValidationError(
            message="Manufacturer is required.",
            field_errors={"manufacturer_slug": "Manufacturer is required."},
        )
    manufacturer = (
        Manufacturer.objects.active()
        .filter(**{Manufacturer.public_id_field: manufacturer_slug})
        .first()
    )
    if manufacturer is None:
        raise StructuredValidationError(
            message="Manufacturer not found.",
            field_errors={"manufacturer_slug": "Manufacturer not found."},
        )

    # ``include_deleted=True`` is load-bearing: ``System.name`` is
    # ``unique=True`` at the DB level, so a name that collides with a
    # soft-deleted System would otherwise pass the active-only pre-check
    # and trip the DB unique constraint, which
    # ``create_entity_with_claims`` misreports as a slug collision.
    assert_name_available(
        System,
        name,
        normalize=normalize_catalog_name,
        friendly_label="system",
        include_deleted=True,
    )
    assert_public_id_available(System, slug)

    create_entity_with_claims(
        System,
        row_kwargs={
            "name": name,
            "slug": slug,
            "status": "active",
            "manufacturer": manufacturer,
        },
        claim_specs=[
            ClaimSpec(field_name="name", value=name),
            ClaimSpec(field_name="slug", value=slug),
            ClaimSpec(field_name="status", value="active"),
            # FK claim value is the parent's public_id (defaults to slug;
            # path-shaped for models that override ``public_id_field``).
            ClaimSpec(field_name="manufacturer", value=manufacturer.public_id),
        ],
        user=request.user,
        note=data.note,
        citations=data.citations,
    )

    created = get_object_or_404(_system_detail_qs(), slug=slug)
    return Status(201, _serialize_system_detail(created))


register_entity_delete_restore(
    systems_router,
    System,
    detail_qs=_system_detail_qs,
    serialize_detail=_serialize_system_detail,
    response_schema=SystemDetailSchema,
)
