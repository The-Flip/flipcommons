"""People router — list, detail, create, delete, restore, and claim-patch endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from django.db import models
from django.db.models import Count, F, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
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
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q, is_deleted
from apps.core.schemas import (
    ErrorDetailSchema,
    RateLimitErrorSchema,
    ValidationErrorSchema,
)
from apps.media.helpers import media_prefetch
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
from ..engine.entity_api.listing import _apply_list_q, paginated_list_response
from ..engine.entity_api.own_media import own_media
from ..engine.query.constants import NameAliasQuery, PageParam
from ..models import Credit, MachineModel, Person
from ._search_sections import tiered_search_rows
from ._typing import HasCreditCount
from .games import GameListSchema
from .images import (
    extract_image_urls,
    fetch_model_media_map,
)
from .schemas import (
    AlreadyDeletedSchema,
    ClaimPatchSchema,
    DeleteResponseSchema,
    EntityCreateInputSchema,
    EntityDetailSchema,
    OwnMediaSchema,
    PersonDeletePreviewSchema,
    PersonSoftDeleteBlockedSchema,
)


class PersonCardSchema(Schema):
    """A person in list results."""

    name: str = Field(description="The person's display name.")
    slug: str = Field(description="The person's URL slug.")
    aliases: list[str] = Field(
        [], description="Alternative names this person is also known by."
    )
    credit_count: int = Field(
        0, description="Number of catalog credits attributed to this person."
    )
    thumbnail_url: str | None = Field(
        None, description="URL of a thumbnail image, if available."
    )


class PersonDetailSchema(EntityDetailSchema, OwnMediaSchema):
    """The person record — the response of the mutation endpoints. The
    read-only detail page's payload is :class:`PersonDetailPageSchema`."""

    slug: str
    birth_year: int | None = None
    birth_month: int | None = None
    birth_day: int | None = None
    death_year: int | None = None
    death_month: int | None = None
    death_day: int | None = None
    birth_place: str | None = None
    nationality: str | None = None
    photo_url: str | None = None
    wikidata_id: str | None = None


class PersonDetailPageSchema(PersonDetailSchema):
    """The detail-page payload: the record plus page 1 of its games — the
    listing pinned to ``person=<slug>``, each card annotated with the person's
    roles on that record. Liveness comes with the listing: credits on deleted
    Models (which the old accumulator carded) no longer surface."""

    games: GameListSchema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@own_media(Person)
def _serialize_person_detail(person: Person) -> PersonDetailSchema:
    """Serialize a Person into the detail response schema.

    Expects *person* fetched with claims (to_attr="active_claims") and media
    prefetched.
    """
    return PersonDetailSchema(
        name=person.name,
        public_id=person.public_id,
        last_modified=person.last_modified,
        slug=person.slug,
        description=describe(person),
        birth_year=person.birth_year,
        birth_month=person.birth_month,
        birth_day=person.birth_day,
        death_year=person.death_year,
        death_month=person.death_month,
        death_day=person.death_day,
        birth_place=person.birth_place,
        nationality=person.nationality,
        photo_url=person.photo_url,
        wikidata_id=person.wikidata_id,
    )


def _person_qs() -> QuerySet[Person]:
    return Person.objects.active().prefetch_related(claims_prefetch(), media_prefetch())


def _people_thumbnails(person_pks: Sequence[int]) -> dict[int, str | None]:
    """Newest-credited-model image per person, batched over *person_pks*.

    The single thumbnail source for the paginated ``GET /`` list (via the core's
    ``ThumbnailProvider`` over one page's pks) and the global search section, so the two
    presentations can't drift. Picks the newest credited model carrying ``extra_data``
    per person, then extracts its display image at the current min rank. No
    active-status filter on the credit's model, by design.
    """
    if not person_pks:
        return {}
    min_rank = get_minimum_display_rank()
    person_thumb_model: dict[int, int] = {}
    for person_id, model_id in (
        Credit.objects.filter(
            person_id__in=person_pks,
            model__isnull=False,
            model__extra_data__isnull=False,
        )
        .order_by(F("model__year").desc(nulls_last=True))
        .values_list("person_id", "model_id")
    ):
        if person_id not in person_thumb_model:
            person_thumb_model[person_id] = model_id
    thumb_models = {
        m.pk: m
        for m in MachineModel.objects.filter(
            id__in=set(person_thumb_model.values())
        ).only("id", "extra_data")
    }
    thumb_media = fetch_model_media_map(person_thumb_model.values())
    result: dict[int, str | None] = {}
    for pid in person_pks:
        tm_id = person_thumb_model.get(pid)
        tm = thumb_models.get(tm_id) if tm_id else None
        if tm is None:
            result[pid] = None
            continue
        thumb, _ = extract_image_urls(
            tm.extra_data or {}, thumb_media.get(tm.pk), min_rank=min_rank
        )
        result[pid] = thumb or None
    return result


def _person_list_qs() -> QuerySet[Person]:
    """Active people annotated with total credit count, most-credited first — the base
    queryset shared by the paginated ``GET /`` list and the search section. Callers
    append a ``pk`` tiebreak for a stable total order before slicing."""
    return (
        Person.objects.active()
        .annotate(credit_count=Count("credits"))
        .prefetch_related("aliases")
        .order_by("-credit_count", "name")
    )


def _serialize_person_row(
    person: Person, thumbnail: str | None = None
) -> PersonCardSchema:
    return PersonCardSchema(
        name=person.name,
        slug=person.slug,
        aliases=[a.value for a in person.aliases.all()],
        credit_count=cast(HasCreditCount, person).credit_count,
        thumbnail_url=thumbnail,
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

people_router = Router(tags=["people"])


class PersonListSchema(Schema):
    """A page of people: ``items`` holds this page's rows; ``count`` is the total
    number of matching people across all pages."""

    items: list[PersonCardSchema]
    count: int


@people_router.get("/", response=PersonListSchema)
def list_people(
    request: HttpRequest, q: NameAliasQuery = "", page: PageParam = 1
) -> PersonListSchema:
    """People, paginated. Search with ``q``. Ordered by credit count, then
    alphabetically."""
    result = paginated_list_response(
        _person_list_qs(),
        q=q,
        ordering=("-credit_count", "name", "pk"),
        page=page,
        serialize_row=_serialize_person_row,
        thumbnail_provider=_people_thumbnails,
    )
    return PersonListSchema(items=result.items, count=result.total)


class PersonSearchSectionSchema(Schema):
    """The People section of the global ``/search`` page: up to 10 cards plus a
    ``has_more`` flag (the section caps at 10; the frontend links to ``/people?q=``
    for the rest). ``items`` reuses the listing card so a section row matches the
    ``/people`` grid exactly."""

    items: list[PersonCardSchema]
    has_more: bool


def person_search_section(q: str) -> PersonSearchSectionSchema:
    """Top ≤10 person cards matching ``q``, composing the listing queryset + card
    serializer so name matches rank exactly as ``/people?q=``. Re-applies the explicit
    ``("-credit_count", "name", "pk")`` total order (``_person_list_qs`` omits the
    ``pk`` tiebreak, so the slice would be nondeterministic on credit-count ties).

    People matched only by their description rank *below* the name/alias tier
    (:func:`tiered_search_rows`, gated on the shared ``DescribedModel``)."""
    # Splat a tuple (not literal args) so django-stubs doesn't field-check
    # ``credit_count`` — it's a real annotation from ``_person_list_qs`` that the stub
    # can't see across the ``_apply_list_q`` boundary (same shape ``list_people`` uses).
    ordering = ("-credit_count", "name", "pk")
    result = tiered_search_rows(
        _apply_list_q(_person_list_qs(), q).order_by(*ordering),
        _person_list_qs().order_by(*ordering),
        q,
    )
    thumbnails = _people_thumbnails([p.pk for p in result.rows])
    return PersonSearchSectionSchema(
        items=[_serialize_person_row(p, thumbnails.get(p.pk)) for p in result.rows],
        has_more=result.has_more,
    )


@people_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: PersonDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_person_claims(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> PersonDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    person = get_object_or_404(
        Person.objects.active(), **{Person.public_id_field: public_id}
    )

    specs = plan_scalar_field_claims(
        Person, data.fields, entity=person, inline_citations=data.inline_citations
    )

    execute_claims(
        person,
        specs,
        user=request.user,
        note=data.note,
        citations=data.citations,
        inline_citations=data.inline_citations,
    )

    person = get_object_or_404(_person_qs(), slug=person.slug)
    return _serialize_person_detail(person)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@people_router.post(
    "/",
    auth=django_auth,
    response={
        201: PersonDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_CREATE)
@rate_limited(CREATE_RATE_LIMIT_SPEC)
def create_person(
    request: HttpRequest, data: EntityCreateInputSchema
) -> Status[PersonDetailSchema]:
    """Create a new Person from a user-supplied name and slug.

    Mirrors ``create_title``: writes a user ChangeSet with ``action=create``
    and three claims — name, slug, and ``status="active"``. Biographical
    fields (birth/death dates, photo, description, wikidata_id) are left
    for the normal edit flow. Duplicate names are rejected outright per
    spec (no disambiguation path for people in v1).

    Rate-limited per user on the shared ``create`` bucket. Staff bypass.
    """
    # Introspect the model's field rather than using MAX_CATALOG_NAME_LENGTH
    # directly — Person.name happens to be capped at 200, while Title/Model
    # are 300, and the shared constant is a ceiling not a floor. Mismatch
    # would let over-long names pass validation and fail at DB insert,
    # which create_entity_with_claims would then misreport as a slug
    # collision.
    name_field = Person._meta.get_field("name")
    assert isinstance(name_field, models.Field)
    assert name_field.max_length is not None
    name = validate_name(data.name, max_length=name_field.max_length)
    slug = validate_slug_format(data.slug)
    assert_name_available(
        Person,
        name,
        normalize=normalize_catalog_name,
        friendly_label="person",
    )
    assert_public_id_available(Person, slug)

    create_entity_with_claims(
        Person,
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

    created = get_object_or_404(_person_qs(), **{Person.public_id_field: slug})
    return Status(201, _serialize_person_detail(created))


# ---------------------------------------------------------------------------
# Delete / restore
# ---------------------------------------------------------------------------


def _active_credit_count(person: Person) -> int:
    """Credits pointing to *person* whose parent Model or Series is active.

    Credit has no ``LifecycleStatusModel``, so the generic soft-delete walker
    in :mod:`.soft_delete` skips it entirely — owned-child rows are
    normally assumed to ride with their parent's visibility. But a Credit
    is owned by *Model or Series*, not by Person, and from Person's
    perspective it's a PROTECT reference. We compute it here rather than
    teaching the walker to follow owned-child chains: Credit is the first
    case to hit this, and generalizing without a second example risks
    designing for the wrong shape.
    """
    # Credit.model XOR Credit.series — exactly one side is non-null. The
    # null-inclusive ``active_status_q`` can't be used alone because its
    # null-status clause matches any Credit where the related side is unset,
    # regardless of the other side's status. Scope each branch to the side
    # that's actually populated.
    return person.credits.filter(
        (Q(model__isnull=False) & active_status_q("model"))
        | (Q(series__isnull=False) & active_status_q("series"))
    ).count()


@people_router.get(
    "/{path:public_id}/delete-preview/",
    auth=django_auth,
    response=PersonDeletePreviewSchema,
    tags=["private"],
)
def person_delete_preview(
    request: HttpRequest, public_id: str
) -> PersonDeletePreviewSchema:
    """Return the impact summary used by the delete confirmation screen."""
    person = get_object_or_404(
        Person.objects.active(), **{Person.public_id_field: public_id}
    )
    plan = plan_soft_delete(person)
    active_credits = _active_credit_count(person)
    is_blocked = plan.is_blocked or active_credits > 0
    changeset_count = 0 if is_blocked else count_entity_changesets(person)
    return PersonDeletePreviewSchema(
        name=person.name,
        slug=person.slug,
        changeset_count=changeset_count,
        active_credit_count=active_credits,
        blocked_by=[serialize_blocking_referrer(b) for b in plan.blockers],
    )


@people_router.post(
    "/{path:public_id}/delete/",
    auth=django_auth,
    response={
        200: DeleteResponseSchema,
        422: PersonSoftDeleteBlockedSchema | AlreadyDeletedSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_DELETE)
@rate_limited(DELETE_RATE_LIMIT_SPEC)
def delete_person(
    request: HttpRequest, public_id: str, data: ChangeSetInputSchema
) -> (
    DeleteResponseSchema | Status[PersonSoftDeleteBlockedSchema | AlreadyDeletedSchema]
):
    """Soft-delete a Person.

    Writes a single user ChangeSet with ``action=delete`` containing one
    ``status=deleted`` claim. Blocks with 422 when *person* is credited on
    any active Model or Series — see :func:`_active_credit_count` for the
    rationale. Also defers to the generic PROTECT walker for any future
    blockers (none expected today).
    """
    person = get_object_or_404(
        Person.objects.active(), **{Person.public_id_field: public_id}
    )

    active_credits = _active_credit_count(person)
    if active_credits > 0:
        return Status(
            422,
            PersonSoftDeleteBlockedSchema(
                detail=(
                    f"Cannot delete: {person.name} is credited on "
                    f"{active_credits} active machine"
                    f"{'s' if active_credits != 1 else ''}. "
                    "Remove the credits first."
                ),
                blocked_by=[],
                active_credit_count=active_credits,
            ),
        )

    try:
        changeset, deleted = execute_soft_delete(
            person, user=request.user, note=data.note, citations=data.citations
        )
    except SoftDeleteBlockedError as exc:
        return Status(
            422,
            PersonSoftDeleteBlockedSchema(
                detail="Cannot delete: active references would be left dangling.",
                blocked_by=[serialize_blocking_referrer(b) for b in exc.blockers],
                active_credit_count=0,
            ),
        )

    if changeset is None:
        return Status(422, AlreadyDeletedSchema(detail="Person is already deleted."))

    return DeleteResponseSchema(
        changeset_id=changeset.pk,
        affected_slugs=[e.slug for e in deleted if isinstance(e, Person)],
    )


@people_router.post(
    "/{path:public_id}/restore/",
    auth=django_auth,
    response={
        200: PersonDetailSchema,
        422: ErrorDetailSchema,
        404: ErrorDetailSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_CREATE)
@rate_limited(CREATE_RATE_LIMIT_SPEC)
def restore_person(
    request: HttpRequest, public_id: str, data: ChangeSetInputSchema
) -> PersonDetailSchema | Status[ErrorDetailSchema]:
    """Write a fresh ``status=active`` claim on a soft-deleted Person.

    Shares the ``create`` rate-limit bucket (Restore is semantically a
    re-create). Person has no lifecycle children, so nothing cascades.
    """
    # Bypass .active() — we're looking for soft-deleted people.
    person = get_object_or_404(Person, **{Person.public_id_field: public_id})
    if not is_deleted(person.status):
        return Status(422, ErrorDetailSchema(detail="Person is not deleted."))

    execute_claims(
        person,
        [ClaimSpec(field_name="status", value="active")],
        user=request.user,
        action=ChangeSetAction.EDIT,
        note=data.note,
        citations=data.citations,
    )

    refreshed = get_object_or_404(_person_qs(), **{Person.public_id_field: public_id})
    return _serialize_person_detail(refreshed)
