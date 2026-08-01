"""Titles router — the Title resource API: create, claims, lifecycle.

The listing moved to ``games.py`` (``GET /api/games/``): the collection is not
Title-grain, so there is no Title collection endpoint any more."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

from django.db.models import (
    Prefetch,
    Q,
    QuerySet,
)
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.responses import Status
from ninja.security import django_auth

from apps.catalog.engine.naming import MAX_CATALOG_NAME_LENGTH, normalize_catalog_name
from apps.catalog.engine.rich_text import describe
from apps.claim_edit.claim_write import (
    ClaimSpec,
    execute_claims,
    plan_scalar_field_claims,
    raise_form_error,
)
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import is_deleted
from apps.core.schemas import (
    ErrorDetailSchema,
    RateLimitErrorSchema,
    ValidationErrorSchema,
)
from apps.media.helpers import (
    all_media,
    displayed_primary_asset_ids,
    media_prefetch,
)
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
from apps.provenance.schemas import ChangeSetInputSchema

from ..engine.entity_api.create import (
    assert_name_available,
    assert_public_id_available,
    create_entity_with_claims,
    validate_name,
    validate_slug_format,
)
from ..engine.entity_api.delete import (
    SoftDeleteBlockedError,
    count_entity_changesets,
    execute_soft_delete,
    plan_soft_delete,
    serialize_blocking_referrer,
)
from ..models import (
    PRODUCED_SLUG,
    MachineModel,
    MachineModelGameplayFeature,
    ModelRelationship,
    Title,
)
from ._typing import CreditKey, GameplayFeatureAgreement
from .edit_claims import plan_abbreviation_claims
from .helpers import (
    _intersect_facet_sets,
    serialize_credit,
    serialize_title_model,
)
from .images import extract_image_urls, fetch_model_media_map
from .machine_models import (
    ModelDetailSchema,
    _model_detail_qs,
    _serialize_model_detail,
)
from .schemas import (
    LICENSE_STATUS_TO_LITERAL,
    RELATIONSHIP_TYPE_TO_LITERAL,
    AlreadyDeletedSchema,
    CreditSchema,
    EntityCreateInputSchema,
    EntityDetailSchema,
    EntityRef,
    GameplayFeatureRef,
    LicenseStatusLiteral,
    SoftDeleteBlockedSchema,
    TitleClaimPatchSchema,
    TitleDeletePreviewSchema,
    TitleModelSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


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
    production_status: EntityRef | None = None
    display_subtype: EntityRef | None = None
    themes: list[EntityRef] = []
    gameplay_features: list[GameplayFeatureRef] = []
    reward_types: list[EntityRef] = []
    tags: list[EntityRef] = []
    production_quantity: str | None = None


# Lineage relations that can point at a model under a different title. Same-title
# links are filtered out in `_collect_related_titles`. `remake_of` and
# `export_edition_of` are the scalar lineage FKs (variant_of is same-title by
# nature, so it has no cross-title arm); the rest are `ModelRelationship` edge
# types (`RelationshipTypeLiteral` values). Kept a flat literal (not a runtime
# union of `RelationshipTypeLiteral`) so it inlines anonymously in the OpenAPI
# schema like its siblings; a snapshot test locks it to
# `{remake_of, export_edition_of} ∪ RelationshipTypeLiteral` so a new edge type
# can't silently omit its cross-title arm.
CrossTitleRelation = Literal[
    "remake_of",
    "export_edition_of",
    "conversion",
    "conversion_kit",
    "copy",
    "retheme",
]
# The scalar FK attrs `_collect_related_titles` walks with getattr.
_CROSS_TITLE_FK_RELATIONS: tuple[CrossTitleRelation, ...] = (
    "remake_of",
    "export_edition_of",
)


class CrossTitleLinkSchema(Schema):
    """A cross-title lineage relationship contributed by a specific model under
    the current title — a `remake_of` / `export_edition_of` link or a
    `ModelRelationship` edge whose target machine sits under a different
    title."""

    relation: CrossTitleRelation
    other_title: EntityRef
    source_model: EntityRef
    # Meaningful for the edge relations only; remakes carry no license axis.
    license_status: LicenseStatusLiteral = "unknown"


class AggregatedMediaSchema(Schema):
    """A media asset from one of the title's models, with its source model."""

    asset_uuid: str
    category: str | None = None
    is_primary: bool
    uploaded_by_username: str | None = None
    renditions: MediaRenditionsSchema
    source_model: EntityRef


class TitleDetailSchema(EntityDetailSchema):
    slug: str
    opdb_id: str | None = None
    fandom_page_id: int | None = None
    abbreviations: list[str] = []
    hero_image_url: str | None = None
    franchise: EntityRef | None = None
    models: list[TitleModelSchema]
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

    # Agree like every other spec field: all models must share the same status,
    # any null vetoes (a null status is unknown, not a value to agree with).
    # Then best-effort suppress ``produced`` — an all-``produced`` title shows
    # nothing, the assumed default. Backend suppression is safe here — this
    # schema is read-only/derived, not editor-consumed.
    production_status = _ref_for("production_status")
    if production_status is not None and production_status.public_id == PRODUCED_SLUG:
        production_status = None

    return AgreedSpecsSchema(
        technology_generation=_ref_for("technology_generation"),
        technology_subgeneration=_ref_for("technology_subgeneration"),
        display_type=_ref_for("display_type"),
        system=_ref_for("system"),
        cabinet=_ref_for("cabinet"),
        game_format=_ref_for("game_format"),
        production_status=production_status,
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
    """Collect cross-title lineage links (see ``CrossTitleRelation``).

    For each model under *current_title* whose lineage FK (``remake_of``,
    ``export_edition_of``) or ``ModelRelationship`` edge points to a model
    under a *different* title,
    emit one entry per link with the relation kind, the other title, and the
    source model under the current title.  Same-title relations (LE→Pro
    conversion, within-title remakes) are excluded — they are not cross-title
    content.  Label-target edges are skipped: an unseeded donor has no title to
    link.  Two edges of the same kind and license landing on two machines of
    the same other title collapse to one entry — the line would read
    identically, and the per-edge connective is deliberately unmodeled.
    """
    items: list[CrossTitleLinkSchema] = []
    for m in models:
        for attr in _CROSS_TITLE_FK_RELATIONS:
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
        seen_edge_lines: set[tuple[str, str, int]] = set()
        for edge in m.relationships.all():
            target = edge.target_machine
            if target is None or target.title_id is None:
                continue
            if target.title_id == current_title.pk:
                continue
            line_key = (edge.relationship_type, edge.license_status, target.title_id)
            if line_key in seen_edge_lines:
                continue
            seen_edge_lines.add(line_key)
            items.append(
                CrossTitleLinkSchema(
                    relation=RELATIONSHIP_TYPE_TO_LITERAL[edge.relationship_type],
                    other_title=EntityRef(
                        public_id=target.title.public_id, name=target.title.name
                    ),
                    source_model=EntityRef(public_id=m.public_id, name=m.name),
                    license_status=LICENSE_STATUS_TO_LITERAL[edge.license_status],
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
        rows = all_media(m)
        primary_ids = displayed_primary_asset_ids(rows)
        for em in rows:
            items.append(
                AggregatedMediaSchema(
                    asset_uuid=str(em.asset.uuid),
                    category=em.category,
                    is_primary=em.asset_id in primary_ids,
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
        rows = all_media(model)
        primary_ids = displayed_primary_asset_ids(rows)
        backglass = [
            em
            for em in rows
            if em.category == "backglass" and em.asset_id in primary_ids
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
    models = [
        serialize_title_model(pm, min_rank=min_rank, media_by_model=media_by_model)
        for pm in model_objs
    ]
    series = (
        EntityRef(name=title.series.name, public_id=title.series.public_id)
        if title.series
        else None
    )
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
    if len(models) == 1 and not models[0].variants:
        pm = _model_detail_qs().get(slug=models[0].public_id)
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
        hero_image_url=hero_image_url,
        franchise=(
            EntityRef(public_id=title.franchise.public_id, name=title.franchise.name)
            if title.franchise
            else None
        ),
        models=models,
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
        queryset=MachineModel.first_model_candidates()
        .select_related(
            "corporate_entity__manufacturer",
            "technology_generation",
            "technology_subgeneration",
            "display_type",
            "display_subtype",
            "system",
            "cabinet",
            "game_format",
            "production_status",
            "remake_of__title",
            "export_edition_of__title",
        )
        .prefetch_related(
            "themes",
            "gameplay_features",
            # Cross-title links read each edge's target title; join it here so
            # `_collect_related_titles` stays query-free.
            Prefetch(
                "relationships",
                queryset=ModelRelationship.objects.select_related(
                    "target_machine__title"
                ),
            ),
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
            # Live variants only: a soft-deleted variant (its delete is never
            # blocked) must not render a card linking its 404.
            Prefetch("variants", queryset=MachineModel.objects.active()),
            media_prefetch(),
        ),
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

titles_router = Router()


@titles_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: TitleDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
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
        plan_scalar_field_claims(
            Title, data.fields, entity=title, inline_citations=data.inline_citations
        )
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
        citations=data.citations,
        inline_citations=data.inline_citations,
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
        citations=data.citations,
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
            # FK claim values store the target's PK — immune to slug renames.
            ClaimSpec(field_name="title", value=title.pk),
        ],
        user=request.user,
        note=data.note,
        citations=data.citations,
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
            title, user=request.user, note=data.note, citations=data.citations
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
    if not is_deleted(title.status):
        return Status(422, ErrorDetailSchema(detail="Title is not deleted."))

    execute_claims(
        title,
        [ClaimSpec(field_name="status", value="active")],
        user=request.user,
        action=ChangeSetAction.EDIT,
        note=data.note,
        citations=data.citations,
    )

    refreshed = get_object_or_404(_detail_qs(), **{Title.public_id_field: public_id})
    return _serialize_title_detail(refreshed)
