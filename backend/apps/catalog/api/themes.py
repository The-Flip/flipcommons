"""Themes router — list, detail, and claims endpoints."""

from __future__ import annotations

from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.security import django_auth
from pydantic import Field

from apps.catalog.engine.rich_text import describe
from apps.claim_edit.claim_write import (
    execute_claims,
    raise_form_error,
    validate_scalar_fields,
)
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..engine.entity_api.create import register_entity_create
from ..engine.entity_api.delete import register_entity_delete_restore
from ..engine.entity_api.listing import _apply_list_q
from ..engine.query.constants import DEFAULT_PAGE_SIZE, NameAliasQuery, PageParam
from ..models import Theme
from ._counts import bulk_title_counts_via_models
from .edit_claims import plan_alias_claims, plan_parent_claims
from .games import GameListSchema
from .schemas import (
    EntityDetailSchema,
    EntityRef,
    HierarchyClaimPatchSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ThemeListItemSchema(Schema):
    """A theme in list results."""

    name: str = Field(description="The theme's display name.")
    slug: str = Field(description="The theme's URL slug.")
    aliases: list[str] = Field(
        [], description="Alternative names this theme is also known by."
    )
    title_count: int = Field(
        0, description="Number of titles with this theme, including its sub-themes."
    )
    parent_slugs: list[str] = Field(
        [], description="Slugs of this theme's parent themes in the hierarchy."
    )


class ThemeListSchema(Schema):
    """A page of themes: ``items`` holds this page's rows; ``count`` is the total
    number of matching themes across all pages."""

    items: list[ThemeListItemSchema]
    count: int


class ThemeDetailSchema(EntityDetailSchema):
    """The theme record — the response of create, delete/restore and the
    claims PATCH (what a section editor receives after a save). The read-only
    detail page's payload is :class:`ThemeDetailPageSchema`."""

    slug: str
    aliases: list[str] = []
    parents: list[EntityRef] = []
    children: list[EntityRef] = []


class ThemeDetailPageSchema(ThemeDetailSchema):
    """The theme detail-page payload: the record plus page 1 of its games —
    the listing pinned to ``theme=<slug>`` (descendants included, rolled up).
    Mutation responses stay :class:`ThemeDetailSchema`; only the page endpoint
    carries the embedded listing."""

    games: GameListSchema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detail_qs() -> QuerySet[Theme]:
    return Theme.objects.active().prefetch_related(
        Prefetch("parents", queryset=Theme.objects.active()),
        Prefetch("children", queryset=Theme.objects.active()),
        "aliases",
        claims_prefetch(),
    )


def _serialize_detail(theme: Theme) -> ThemeDetailSchema:
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
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

themes_router = Router()


def _serialize_theme_row(theme: Theme, title_count: int) -> ThemeListItemSchema:
    return ThemeListItemSchema(
        name=theme.name,
        slug=theme.slug,
        aliases=[a.value for a in theme.aliases.all()],
        title_count=title_count,
        parent_slugs=[p.slug for p in theme.parents.all()],
    )


def _active_themes() -> list[Theme]:
    return list(
        Theme.objects.active().prefetch_related(
            Prefetch("parents", queryset=Theme.objects.active()),
            Prefetch("children", queryset=Theme.objects.active()),
            "aliases",
        )
    )


def _theme_rollup(themes: list[Theme]) -> dict[int, int]:
    """The hierarchical ``title_count`` rollup over *themes*: each theme's count unions
    its whole descendant subtree's titles via ``children_map`` (not a SQL column),
    deduped."""
    children_map: dict[int, list[int]] = {
        t.pk: [c.pk for c in t.children.all()] for t in themes
    }
    return bulk_title_counts_via_models(
        [t.pk for t in themes],
        "themes",
        children_map=children_map,
    )


@themes_router.get("/", response=ThemeListSchema)
def list_themes(
    request: HttpRequest, q: NameAliasQuery = "", page: PageParam = 1
) -> ThemeListSchema:
    """Themes, paginated. Search with ``q``. Ordered by title count, then
    alphabetically.

    Title counts roll up the theme hierarchy: a theme's count reflects its whole
    descendant set, not just itself. ``q`` selects which rows show, but does not
    narrow the counts."""
    # The ``-title_count`` sort is the hierarchical ``children_map`` rollup, not a
    # SQL column, so this handler does its own compute-sort-slice over the full
    # active set rather than going through ``paginated_list_response``'s SQL slice.
    active = _active_themes()
    counts = _theme_rollup(active)

    if q.strip():
        matched_pks = set(
            _apply_list_q(Theme.objects.active(), q).values_list("pk", flat=True)
        )
        matched = [t for t in active if t.pk in matched_pks]
    else:
        # No search → every active theme shows; skip the extra pk query (the
        # dominant page-1 SSR path), since ``active`` already holds them all.
        matched = active
    # ``pk`` tiebreak after (-count, name) so offset pages are stable.
    matched.sort(key=lambda t: (-counts.get(t.pk, 0), t.name.lower(), t.pk))

    start = (max(page, 1) - 1) * DEFAULT_PAGE_SIZE
    rows = matched[start : start + DEFAULT_PAGE_SIZE]
    return ThemeListSchema(
        items=[_serialize_theme_row(t, counts.get(t.pk, 0)) for t in rows],
        count=len(matched),
    )


@themes_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: ThemeDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
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

    specs = validate_scalar_fields(
        Theme, data.fields, entity=theme, inline_citations=data.inline_citations
    )

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
        theme,
        specs,
        user=request.user,
        note=data.note,
        citations=data.citations,
        inline_citations=data.inline_citations,
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
