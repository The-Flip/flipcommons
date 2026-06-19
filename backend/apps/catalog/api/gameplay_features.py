"""Gameplay features router — list, detail, and claims endpoints."""

from __future__ import annotations

from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.security import django_auth
from pydantic import Field

from apps.claim_edit.claim_write import (
    execute_claims,
    raise_form_error,
    validate_scalar_fields,
)
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.media.helpers import all_media, media_prefetch
from apps.media.schemas import UploadedMediaSchema
from apps.media.selectors import serialize_uploaded_media
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..engine.entity_api.create import register_entity_create
from ..engine.entity_api.delete import register_entity_delete_restore
from ..engine.entity_api.listing import _apply_list_q
from ..engine.query.constants import DEFAULT_PAGE_SIZE, NameAliasQuery, PageParam
from ..models import GameplayFeature
from ._counts import bulk_title_counts_via_models
from .edit_claims import plan_alias_claims, plan_parent_claims
from .rich_text import describe
from .schemas import (
    EntityDetailSchema,
    EntityRef,
    HierarchyClaimPatchSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GameplayFeatureListItemSchema(Schema):
    """A gameplay feature in list results."""

    name: str = Field(description="The feature's display name.")
    slug: str = Field(description="The feature's URL slug.")
    aliases: list[str] = Field(
        [], description="Alternative names this feature is also known by."
    )
    title_count: int = Field(
        0,
        description="Number of titles with this feature, including its sub-features.",
    )
    parent_slugs: list[str] = Field(
        [], description="Slugs of this feature's parent features in the hierarchy."
    )


class GameplayFeatureListSchema(Schema):
    """A page of gameplay features: ``items`` holds this page's rows; ``count`` is the
    total number of matching gameplay features across all pages."""

    items: list[GameplayFeatureListItemSchema]
    count: int


class GameplayFeatureDetailSchema(EntityDetailSchema):
    slug: str
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
        public_id=feature.public_id,
        last_modified=feature.last_modified,
        slug=feature.slug,
        description=describe(feature),
        aliases=[a.value for a in feature.aliases.all()],
        parents=[
            EntityRef(name=p.name, public_id=p.public_id) for p in feature.parents.all()
        ],
        children=[
            EntityRef(name=c.name, public_id=c.public_id)
            for c in feature.children.order_by("name")
        ],
        uploaded_media=serialize_uploaded_media(all_media(feature)),
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

gameplay_features_router = Router(tags=["gameplay-features"])


def _serialize_gameplay_feature_row(
    feature: GameplayFeature, title_count: int
) -> GameplayFeatureListItemSchema:
    return GameplayFeatureListItemSchema(
        name=feature.name,
        slug=feature.slug,
        aliases=[a.value for a in feature.aliases.all()],
        title_count=title_count,
        parent_slugs=[p.slug for p in feature.parents.all()],
    )


def _gameplay_feature_rollup(
    features: list[GameplayFeature],
) -> dict[int, int]:
    """The hierarchical ``title_count`` rollup over *features*: each feature's count
    unions its whole descendant subtree's titles via ``children_map`` (not a SQL
    column), deduped."""
    children_map: dict[int, list[int]] = {
        f.pk: [c.pk for c in f.children.all()] for f in features
    }
    return bulk_title_counts_via_models(
        [f.pk for f in features],
        "gameplay_features",
        children_map=children_map,
    )


def _active_gameplay_features() -> list[GameplayFeature]:
    return list(
        GameplayFeature.objects.active().prefetch_related(
            Prefetch("children", queryset=GameplayFeature.objects.active()),
            Prefetch("parents", queryset=GameplayFeature.objects.active()),
            "aliases",
        )
    )


@gameplay_features_router.get("/", response=GameplayFeatureListSchema)
def list_gameplay_features(
    request: HttpRequest, q: NameAliasQuery = "", page: PageParam = 1
) -> GameplayFeatureListSchema:
    """Gameplay features, paginated. Search with ``q``. Ordered by title count, then
    alphabetically.

    Title counts roll up the feature hierarchy: a feature's count reflects its whole
    descendant set, not just itself. ``q`` selects which rows show, but does not
    narrow the counts."""
    # The ``-title_count`` sort is the hierarchical ``children_map`` rollup, not a
    # SQL column, so this handler does its own compute-sort-slice over the full
    # active set rather than going through ``paginated_list_response``'s SQL slice.
    active = _active_gameplay_features()
    counts = _gameplay_feature_rollup(active)

    if q.strip():
        matched_pks = set(
            _apply_list_q(GameplayFeature.objects.active(), q).values_list(
                "pk", flat=True
            )
        )
        matched = [f for f in active if f.pk in matched_pks]
    else:
        # No search → every active feature shows; skip the extra pk query (the
        # dominant page-1 SSR path), since ``active`` already holds them all.
        matched = active
    # ``pk`` tiebreak after (-count, name) so offset pages are stable.
    matched.sort(key=lambda f: (-counts.get(f.pk, 0), f.name.lower(), f.pk))

    start = (max(page, 1) - 1) * DEFAULT_PAGE_SIZE
    rows = matched[start : start + DEFAULT_PAGE_SIZE]
    return GameplayFeatureListSchema(
        items=[_serialize_gameplay_feature_row(f, counts.get(f.pk, 0)) for f in rows],
        count=len(matched),
    )


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
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_gameplay_feature_claims(
    request: HttpRequest, public_id: str, data: HierarchyClaimPatchSchema
) -> GameplayFeatureDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
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
