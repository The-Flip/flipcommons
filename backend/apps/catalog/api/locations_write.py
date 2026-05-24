"""Locations write router — create, edit (PATCH-claims), delete, restore.

Read routes live in :mod:`.locations` (mounted under ``/api/pages/locations/``)
because the Location detail is a page-shaped payload (children, ancestors,
manufacturers). Write routes live here, mounted under ``/api/locations/``,
and follow the resource-shaped CRUD wiring every other catalog entity uses.

Two create routes:

* ``POST /api/locations/`` — top-level country, accepts ``divisions``.
* ``POST /api/locations/{parent_public_id:path}/children/`` — child of any tier;
  the server derives ``location_type`` from the country ancestor's
  ``divisions``.

PATCH-claims is bespoke (no shared factory yet). ``parent`` / ``slug`` /
``location_type`` are immutable — rejected here (route-level) and at the
model level once ``immutable_after_create`` lands. ``divisions`` is
only meaningful on country rows and is rejected with a field-level 422
when sent against any other tier.

Delete / restore use the shared :func:`register_entity_delete_restore`
factory with ``parent_field="parent"`` and ``child_related_name="children"``;
active direct child Locations block delete (universal catalog rule), and
active CorporateEntityLocation referrers block via the model's
``soft_delete_usage_blockers``.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.security import django_auth
from pydantic import ConfigDict, field_validator

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited
from apps.provenance.schemas import ChangeSetInputSchema

from ..models import CatalogModel, Location
from ..services.location_paths import (
    compute_location_path,
    derive_child_location_type,
)
from .edit_claims import (
    ClaimSpec,
    StructuredValidationError,
    execute_claims,
    plan_alias_claims,
    raise_form_error,
    validate_scalar_fields,
)
from .entity_crud import (
    CreateExtras,
    register_entity_create,
    register_entity_delete_restore,
)
from .locations import LocationDetailSchema, _get_location_detail
from .schemas import EntityCreateInputSchema

# ---------------------------------------------------------------------------
# Detail re-serialization
# ---------------------------------------------------------------------------
#
# Create / restore / PATCH all return the standard ``LocationDetailSchema``
# payload. ``_get_location_detail`` reads the cached tree, which the claim
# resolver invalidates on commit, so the freshly-written entity is visible.


def _detail_qs() -> QuerySet[Location]:
    """Active-Location queryset to satisfy the factory contract.

    ``register_entity_create`` / ``register_entity_delete_restore`` re-fetch
    the entity through ``detail_qs`` and pass it to ``serialize_detail``.
    Location's serializer below then ignores the row and resolves the
    cached tree by ``location_path`` instead — the entity itself is only
    used for its ``location_path`` attribute. The factory's re-fetch is a
    vestigial DB hit (~1 indexed row); accepted as the cost of staying on
    the shared factory until the contract gets a "skip refetch" hook.
    """
    return Location.objects.active()


def _serialize_location_detail(loc: Location) -> LocationDetailSchema:
    return _get_location_detail(loc.location_path)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def _validate_divisions(value: list[str]) -> list[str]:
    if not value:
        raise ValueError("divisions must be a non-empty list")
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("each division must be a string")
        stripped = item.strip()
        if not stripped:
            raise ValueError("divisions cannot contain blank entries")
        cleaned.append(stripped)
    return cleaned


class LocationTopLevelCreateSchema(EntityCreateInputSchema):
    """Body for top-level country create.

    ``extra='forbid'`` rejects any client-supplied ``location_type`` (or
    other unknown field) at the schema layer before any handler code runs.
    """

    model_config = ConfigDict(extra="forbid")

    divisions: list[str]

    @field_validator("divisions")
    @classmethod
    def _check_divisions(cls, value: list[str]) -> list[str]:
        return _validate_divisions(value)


class LocationChildCreateSchema(EntityCreateInputSchema):
    """Body for child create.

    Server derives ``location_type`` from the parent chain; clients may
    not supply it (or ``divisions``) — ``extra='forbid'``.
    """

    model_config = ConfigDict(extra="forbid")


class LocationPatchClaimSchema(ChangeSetInputSchema):
    """PATCH body for Location claim edits.

    ``divisions`` is only meaningful on country rows; the handler rejects
    it with a field-level 422 when the resolved row's ``location_type``
    is not ``"country"``. This matches the route-level rejection of
    ``parent``, ``slug``, and ``location_type`` (immutable after create)
    rather than splitting into per-tier schemas — the dispatch layer
    bought clearer OpenAPI shapes at a high implementation cost
    (permissive base + manual re-validate + custom error remapping) and
    the codebase already has handler-level field rejection as a
    convention.
    """

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any] = {}
    aliases: list[str] | None = None
    divisions: list[str] | None = None

    @field_validator("divisions")
    @classmethod
    def _check_divisions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _validate_divisions(value)


# Fields that must never appear in a PATCH ``fields`` payload — Location's
# parent / slug / location_type are immutable after create. Once model-level
# immutable-field metadata exists, this set should come from the model and the
# explicit guard below can go away.
_IMMUTABLE_FIELDS = frozenset({"parent", "slug", "location_type"})


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Single resource-shaped router mounted at ``/api/locations/``. The
# read-side ``locations_router`` lives separately under
# ``/api/pages/locations/`` because Location's detail is a page payload.
locations_write_router = Router(tags=["private"])


# ---------------------------------------------------------------------------
# Create — top-level country
# ---------------------------------------------------------------------------


def _top_level_scope(_data: EntityCreateInputSchema, _parent: CatalogModel | None) -> Q:
    # Country tier: name / slug uniqueness is scoped to root-level rows
    # (matches the partial UNIQUE constraints with ``parent IS NULL``).
    return Q(parent__isnull=True)


def _top_level_extras(
    data: EntityCreateInputSchema, _parent: CatalogModel | None
) -> CreateExtras:
    assert isinstance(data, LocationTopLevelCreateSchema)
    divisions = data.divisions
    return CreateExtras(
        row_kwargs={
            "location_type": "country",
            "divisions": divisions,
            "location_path": compute_location_path(None, data.slug),
        },
        claim_specs=[
            ClaimSpec(field_name="location_type", value="country"),
            ClaimSpec(field_name="divisions", value=divisions),
        ],
    )


register_entity_create(
    locations_write_router,
    Location,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_location_detail,
    response_schema=LocationDetailSchema,
    body_schema=LocationTopLevelCreateSchema,
    scope_filter_builder=_top_level_scope,
    extra_create_fields_builder=_top_level_extras,
)


# ---------------------------------------------------------------------------
# Create — child location
# ---------------------------------------------------------------------------


def _child_scope(_data: EntityCreateInputSchema, parent: CatalogModel | None) -> Q:
    # Child tier: name / slug uniqueness is scoped to siblings (matches
    # the partial UNIQUE constraints with ``parent IS NOT NULL``).
    assert parent is not None
    return Q(parent=parent)


def _child_extras(
    data: EntityCreateInputSchema, parent: CatalogModel | None
) -> CreateExtras:
    assert parent is not None
    assert isinstance(parent, Location)
    location_type = derive_child_location_type(parent)
    return CreateExtras(
        row_kwargs={
            "location_type": location_type,
            "location_path": compute_location_path(parent, data.slug),
        },
        claim_specs=[ClaimSpec(field_name="location_type", value=location_type)],
    )


register_entity_create(
    locations_write_router,
    Location,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_location_detail,
    response_schema=LocationDetailSchema,
    parent_field="parent",
    parent_model=Location,
    route_suffix="children",
    body_schema=LocationChildCreateSchema,
    scope_filter_builder=_child_scope,
    extra_create_fields_builder=_child_extras,
    # Disambiguate from the top-level country create above on the
    # same router; default ``location_create`` would collide.
    op_id_suffix="_child",
)


# ---------------------------------------------------------------------------
# PATCH claims — bespoke (no shared factory yet)
# ---------------------------------------------------------------------------


@locations_write_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: LocationDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_location_claims(
    request: HttpRequest, public_id: str, data: LocationPatchClaimSchema
) -> LocationDetailSchema:
    """Apply per-field claims, alias diffs, and (country-only) divisions.

    The PATCH route accepts ``name`` edits via ``data.fields`` even though
    the frontend in this PR does not surface them (no ``NameEditor``
    registered, since slug is immutable). ``name`` is editable on the
    model — just not yet exposed in the UI. Do not "tighten" by removing
    it; that's tracked in a follow-up that teaches ``NameEditor`` a
    name-only mode.
    """
    loc = get_object_or_404(
        Location.objects.active(), **{Location.public_id_field: public_id}
    )

    fields = data.fields
    immutable_in_payload = sorted(set(fields) & _IMMUTABLE_FIELDS)
    if immutable_in_payload:
        raise StructuredValidationError(
            message=(
                f"Fields not editable on Location: {', '.join(immutable_in_payload)}."
            ),
            field_errors={
                f: f"{f} is not editable after create." for f in immutable_in_payload
            },
        )
    if "divisions" in fields:
        # ``divisions`` rides on its own top-level body field; reject it
        # inside ``fields`` rather than allow two paths to write the
        # same claim.
        raise StructuredValidationError(
            message="divisions belongs at the top level, not inside fields.",
            field_errors={"divisions": "Send divisions at the top level."},
        )
    if data.divisions is not None and loc.location_type != "country":
        raise StructuredValidationError(
            message="divisions is only editable on countries.",
            field_errors={
                "divisions": (
                    "divisions is only editable on countries; this location "
                    f"is a {loc.location_type}."
                )
            },
        )

    specs = validate_scalar_fields(Location, fields, entity=loc)

    if data.aliases is not None:
        specs.extend(
            plan_alias_claims(
                loc,
                data.aliases,
                claim_field_name="location_alias",
            )
        )

    if data.divisions is not None:
        specs.append(ClaimSpec(field_name="divisions", value=data.divisions))

    if not specs:
        raise_form_error("No changes provided.")

    execute_claims(
        loc, specs, user=request.user, note=data.note, citation=data.citation
    )

    return _get_location_detail(loc.location_path)


# ---------------------------------------------------------------------------
# Delete / restore
# ---------------------------------------------------------------------------

register_entity_delete_restore(
    locations_write_router,
    Location,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_location_detail,
    response_schema=LocationDetailSchema,
    parent_field="parent",
    child_related_name="children",
)
