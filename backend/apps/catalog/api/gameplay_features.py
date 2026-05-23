"""Gameplay features router — list, detail, and claims endpoints."""

from __future__ import annotations

from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.security import django_auth

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.media.helpers import all_media
from apps.media.schemas import UploadedMediaSchema
from apps.provenance.helpers import active_claims, claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, check_and_record
from apps.provenance.schemas import RichTextSchema

from ..models import GameplayFeature
from ._counts import bulk_title_counts_via_models
from .edit_claims import (
    execute_claims,
    plan_alias_claims,
    plan_parent_claims,
    raise_form_error,
    validate_scalar_fields,
)
from .entity_crud import register_entity_create, register_entity_delete_restore
from .images import media_prefetch, serialize_uploaded_media
from .rich_text import build_rich_text
from .schemas import (
    EntityRef,
    HierarchyClaimPatchSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GameplayFeatureListItemSchema(Schema):
    name: str
    slug: str
    aliases: list[str] = []
    title_count: int = 0
    parent_slugs: list[str] = []


class GameplayFeatureDetailSchema(Schema):
    name: str
    slug: str
    description: RichTextSchema = RichTextSchema()
    aliases: list[str] = []
    parents: list[EntityRef] = []
    children: list[EntityRef] = []
    uploaded_media: list[UploadedMediaSchema] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detail_qs() -> QuerySet[GameplayFeature]:
    return GameplayFeature.objects.active().prefetch_related(
        Prefetch("parents", queryset=GameplayFeature.objects.active()),
        Prefetch("children", queryset=GameplayFeature.objects.active()),
        "aliases",
        claims_prefetch(),
        media_prefetch(),
    )


def _serialize_detail(feature: GameplayFeature) -> GameplayFeatureDetailSchema:
    return GameplayFeatureDetailSchema(
        name=feature.name,
        slug=feature.slug,
        description=build_rich_text(feature, "description", active_claims(feature)),
        aliases=[a.value for a in feature.aliases.all()],
        parents=[EntityRef(name=p.name, slug=p.slug) for p in feature.parents.all()],
        children=[
            EntityRef(name=c.name, slug=c.slug)
            for c in feature.children.order_by("name")
        ],
        uploaded_media=serialize_uploaded_media(all_media(feature)),
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

gameplay_features_router = Router(tags=["gameplay-features"])


@gameplay_features_router.get("/", response=list[GameplayFeatureListItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_gameplay_features(
    request: HttpRequest,
) -> list[GameplayFeatureListItemSchema]:
    features = list(
        GameplayFeature.objects.active().prefetch_related(
            Prefetch("children", queryset=GameplayFeature.objects.active()),
            Prefetch("parents", queryset=GameplayFeature.objects.active()),
            "aliases",
        )
    )

    children_map: dict[int, list[int]] = {
        f.pk: [c.pk for c in f.children.all()] for f in features
    }
    counts = bulk_title_counts_via_models(
        [f.pk for f in features],
        "gameplay_features",
        children_map=children_map,
    )
    features.sort(key=lambda f: (-counts.get(f.pk, 0), f.name.lower()))

    return [
        GameplayFeatureListItemSchema(
            name=f.name,
            slug=f.slug,
            aliases=[a.value for a in f.aliases.all()],
            title_count=counts.get(f.pk, 0),
            parent_slugs=[p.slug for p in f.parents.all()],
        )
        for f in features
    ]


@gameplay_features_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: GameplayFeatureDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
def patch_gameplay_feature_claims(
    request: HttpRequest, public_id: str, data: HierarchyClaimPatchSchema
) -> GameplayFeatureDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    check_and_record(request.user, EDIT_RATE_LIMIT_SPEC)

    if not data.fields and data.parents is None and data.aliases is None:
        raise_form_error("No changes provided.")

    feature = get_object_or_404(
        GameplayFeature.objects.active(),
        **{GameplayFeature.public_id_field: public_id},
    )

    specs = validate_scalar_fields(GameplayFeature, data.fields, entity=feature)

    if data.parents is not None:
        specs.extend(
            plan_parent_claims(
                feature,
                set(data.parents),
                model_class=GameplayFeature,
                claim_field_name="gameplay_feature_parent",
            )
        )

    if data.aliases is not None:
        specs.extend(
            plan_alias_claims(
                feature,
                data.aliases,
                claim_field_name="gameplay_feature_alias",
            )
        )

    if not specs:
        raise_form_error("No changes provided.")

    execute_claims(
        feature,
        specs,
        user=request.user,
        note=data.note,
        citation=data.citation,
    )

    feature = get_object_or_404(_detail_qs(), slug=feature.slug)
    return _serialize_detail(feature)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------

register_entity_create(
    gameplay_features_router,
    GameplayFeature,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_detail,
    response_schema=GameplayFeatureDetailSchema,
)
register_entity_delete_restore(
    gameplay_features_router,
    GameplayFeature,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_detail,
    response_schema=GameplayFeatureDetailSchema,
)
