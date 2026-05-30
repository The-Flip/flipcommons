"""Themes router — list, detail, and claims endpoints."""

from __future__ import annotations

from django.db.models import F, Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.security import django_auth

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..models import MachineModel, Theme
from ._counts import bulk_title_counts_via_models
from .edit_claims import (
    execute_claims,
    plan_alias_claims,
    plan_parent_claims,
    raise_form_error,
    validate_scalar_fields,
)
from .entity_crud import register_entity_create, register_entity_delete_restore
from .helpers import serialize_title_machine
from .images import fetch_model_media_map
from .rich_text import describe
from .schemas import (
    CatalogDetailSchema,
    EntityRef,
    HierarchyClaimPatchSchema,
    TitleModelSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ThemeListItemSchema(Schema):
    name: str
    slug: str
    aliases: list[str] = []
    title_count: int = 0
    parent_slugs: list[str] = []


class ThemeDetailSchema(CatalogDetailSchema):
    slug: str
    aliases: list[str] = []
    parents: list[EntityRef] = []
    children: list[EntityRef] = []
    machines: list[TitleModelSchema]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detail_qs() -> QuerySet[Theme]:
    return Theme.objects.active().prefetch_related(
        Prefetch("parents", queryset=Theme.objects.active()),
        Prefetch("children", queryset=Theme.objects.active()),
        "aliases",
        claims_prefetch(),
        Prefetch(
            "machine_models",
            queryset=MachineModel.objects.active()
            .filter(variant_of__isnull=True)
            .select_related("corporate_entity__manufacturer", "technology_generation")
            .order_by(F("year").desc(nulls_last=True), "name"),
        ),
    )


def _serialize_detail(theme: Theme) -> ThemeDetailSchema:
    min_rank = get_minimum_display_rank()
    machines_list = list(theme.machine_models.all())
    media_by_model = fetch_model_media_map(pm.pk for pm in machines_list)
    return ThemeDetailSchema(
        name=theme.name,
        public_id=theme.public_id,
        last_modified=theme.last_modified,
        slug=theme.slug,
        description=describe(theme),
        aliases=[a.value for a in theme.aliases.all()],
        parents=[
            EntityRef(name=t.name, public_id=t.public_id) for t in theme.parents.all()
        ],
        children=[
            EntityRef(name=t.name, public_id=t.public_id)
            for t in theme.children.order_by("name")
        ],
        machines=[
            serialize_title_machine(
                pm, min_rank=min_rank, media_by_model=media_by_model
            )
            for pm in machines_list
        ],
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

themes_router = Router(tags=["themes"])


@themes_router.get("/", response=list[ThemeListItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_themes(request: HttpRequest) -> list[ThemeListItemSchema]:
    themes = list(
        Theme.objects.active().prefetch_related(
            Prefetch("parents", queryset=Theme.objects.active()),
            Prefetch("children", queryset=Theme.objects.active()),
            "aliases",
        )
    )
    children_map: dict[int, list[int]] = {
        t.pk: [c.pk for c in t.children.all()] for t in themes
    }
    counts = bulk_title_counts_via_models(
        [t.pk for t in themes],
        "themes",
        children_map=children_map,
    )
    themes.sort(key=lambda t: (-counts.get(t.pk, 0), t.name.lower()))
    return [
        ThemeListItemSchema(
            name=t.name,
            slug=t.slug,
            aliases=[a.value for a in t.aliases.all()],
            title_count=counts.get(t.pk, 0),
            parent_slugs=[p.slug for p in t.parents.all()],
        )
        for t in themes
    ]


@themes_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: ThemeDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_theme_claims(
    request: HttpRequest, public_id: str, data: HierarchyClaimPatchSchema
) -> ThemeDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    if not data.fields and data.parents is None and data.aliases is None:
        raise_form_error("No changes provided.")

    theme = get_object_or_404(
        Theme.objects.active(), **{Theme.public_id_field: public_id}
    )

    specs = validate_scalar_fields(Theme, data.fields, entity=theme)

    if data.parents is not None:
        specs.extend(
            plan_parent_claims(
                theme,
                set(data.parents),
                model_class=Theme,
                claim_field_name="theme_parent",
            )
        )

    if data.aliases is not None:
        specs.extend(
            plan_alias_claims(
                theme,
                data.aliases,
                claim_field_name="theme_alias",
            )
        )

    if not specs:
        raise_form_error("No changes provided.")

    execute_claims(
        theme, specs, user=request.user, note=data.note, citation=data.citation
    )

    theme = get_object_or_404(_detail_qs(), slug=theme.slug)
    return _serialize_detail(theme)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------

register_entity_create(
    themes_router,
    Theme,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_detail,
    response_schema=ThemeDetailSchema,
)
register_entity_delete_restore(
    themes_router,
    Theme,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_detail,
    response_schema=ThemeDetailSchema,
)
