"""People router — list, detail, create, delete, restore, and claim-patch endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from django.db import models
from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.pagination import paginate
from ninja.responses import Status
from ninja.security import django_auth
from pydantic import TypeAdapter

from apps.catalog.naming import normalize_catalog_name
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.pagination import NamedPageNumberPagination
from apps.core.schemas import (
    ErrorDetailSchema,
    RateLimitErrorSchema,
    ValidationErrorSchema,
)
from apps.media.helpers import all_media
from apps.media.schemas import UploadedMediaSchema
from apps.provenance.helpers import active_claims, claims_prefetch
from apps.provenance.models import ChangeSetAction
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    DELETE_RATE_LIMIT_SPEC,
    EDIT_RATE_LIMIT_SPEC,
    rate_limited,
)
from apps.provenance.schemas import ChangeSetInputSchema, RichTextSchema

from ..cache import get_cached_response, people_all_key, set_cached_response
from ..models import Credit, MachineModel, Person
from ._typing import HasCreditCount
from .constants import DEFAULT_PAGE_SIZE
from .edit_claims import ClaimSpec, execute_claims, plan_scalar_field_claims
from .entity_create import (
    assert_name_available,
    assert_public_id_available,
    create_entity_with_claims,
    validate_name,
    validate_slug_format,
)
from .images import (
    extract_image_urls,
    fetch_model_media_map,
    media_prefetch,
    serialize_uploaded_media,
)
from .rich_text import build_rich_text
from .schemas import (
    AlreadyDeletedSchema,
    ClaimPatchSchema,
    DeleteResponseSchema,
    EntityCreateInputSchema,
    LinkableDetailSchema,
    PersonDeletePreviewSchema,
    PersonSoftDeleteBlockedSchema,
    RelatedTitleSchema,
)
from .soft_delete import (
    SoftDeleteBlockedError,
    count_entity_changesets,
    execute_soft_delete,
    plan_soft_delete,
    serialize_blocking_referrer,
)


class PersonGridItemSchema(Schema):
    name: str
    slug: str
    aliases: list[str] = []
    credit_count: int = 0
    thumbnail_url: str | None = None


_ALL_ADAPTER: TypeAdapter[list[PersonGridItemSchema]] = TypeAdapter(
    list[PersonGridItemSchema]
)


class PersonListItemSchema(Schema):
    name: str
    slug: str
    credit_count: int = 0


class PersonTitleSchema(RelatedTitleSchema):
    roles: list[str] = []


class PersonDetailSchema(LinkableDetailSchema):
    slug: str
    description: RichTextSchema = RichTextSchema()
    birth_year: int | None = None
    birth_month: int | None = None
    birth_day: int | None = None
    death_year: int | None = None
    death_month: int | None = None
    death_day: int | None = None
    birth_place: str | None = None
    nationality: str | None = None
    photo_url: str | None = None
    titles: list[PersonTitleSchema]
    uploaded_media: list[UploadedMediaSchema] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _PersonTitleAccum:
    name: str
    public_id: str
    year: int | None
    manufacturer_name: str | None
    thumbnail_url: str | None
    roles: list[str] = field(default_factory=list)


def _serialize_person_detail(person: Person) -> PersonDetailSchema:
    """Serialize a Person into the detail response schema.

    Expects *person* to have been fetched with prefetch_related for credits
    (select_related model, model__title, model__manufacturer) and claims
    (to_attr="active_claims").
    """
    min_rank = get_minimum_display_rank()
    credits = list(person.credits.all())
    media_by_model = fetch_model_media_map(
        c.model_id for c in credits if c.model_id is not None
    )
    accum: dict[str, _PersonTitleAccum] = {}
    for c in credits:
        if c.model is None or c.model.title is None:
            continue
        title = c.model.title
        key = title.slug
        thumbnail_url = extract_image_urls(
            c.model.extra_data or {},
            media_by_model.get(c.model.pk),
            min_rank=min_rank,
        )[0]
        if key not in accum:
            accum[key] = _PersonTitleAccum(
                name=title.name,
                public_id=title.public_id,
                year=c.model.year,
                manufacturer_name=(
                    c.model.corporate_entity.manufacturer.name
                    if c.model.corporate_entity
                    and c.model.corporate_entity.manufacturer
                    else None
                ),
                thumbnail_url=thumbnail_url,
            )
        elif accum[key].thumbnail_url is None and thumbnail_url:
            accum[key].thumbnail_url = thumbnail_url
        role_display = c.role.name
        if role_display not in accum[key].roles:
            accum[key].roles.append(role_display)
    titles = [
        PersonTitleSchema(
            name=a.name,
            public_id=a.public_id,
            year=a.year,
            manufacturer_name=a.manufacturer_name,
            thumbnail_url=a.thumbnail_url,
            roles=a.roles,
        )
        for a in accum.values()
    ]
    return PersonDetailSchema(
        name=person.name,
        public_id=person.public_id,
        slug=person.slug,
        description=build_rich_text(person, "description", active_claims(person)),
        birth_year=person.birth_year,
        birth_month=person.birth_month,
        birth_day=person.birth_day,
        death_year=person.death_year,
        death_month=person.death_month,
        death_day=person.death_day,
        birth_place=person.birth_place,
        nationality=person.nationality,
        photo_url=person.photo_url,
        titles=titles,
        uploaded_media=serialize_uploaded_media(all_media(person)),
    )


def _person_qs() -> QuerySet[Person]:
    return Person.objects.active().prefetch_related(
        Prefetch(
            "credits",
            queryset=Credit.objects.filter(model__isnull=False)
            .select_related(
                "model__title", "model__corporate_entity__manufacturer", "role"
            )
            .order_by(F("model__year").desc(nulls_last=True), "model__name"),
        ),
        claims_prefetch(),
        media_prefetch(),
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

people_router = Router(tags=["people"])


class PersonListPagination(NamedPageNumberPagination):
    response_name = "PersonListSchema"


@people_router.get("/", response=list[PersonListItemSchema])
@paginate(PersonListPagination, page_size=DEFAULT_PAGE_SIZE)
def list_people(request: HttpRequest) -> list[PersonListItemSchema]:
    return [
        PersonListItemSchema(
            name=row["name"], slug=row["slug"], credit_count=row["credit_count"]
        )
        for row in Person.objects.active()
        .annotate(credit_count=Count("credits"))
        .order_by("name")
        .values("name", "slug", "credit_count")
    ]


@people_router.get("/all/", response=list[PersonGridItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_all_people(
    request: HttpRequest,
) -> HttpResponse | list[dict[str, Any]]:
    """Return every person with credit count and thumbnail.

    Uses a bulk query to find the newest credited model per person for
    thumbnails, instead of prefetching all credits and iterating in Python.
    See ``list_all_titles`` for the full explanation of this pattern.
    """
    response = get_cached_response(people_all_key())
    if response is not None:
        return response

    min_rank = get_minimum_display_rank()

    people = list(
        Person.objects.active()
        .annotate(credit_count=Count("credits"))
        .prefetch_related("aliases")
        .order_by("-credit_count")
    )

    # Batch thumbnail: newest credited model with extra_data per person
    person_thumb_model: dict[int, int] = {}
    for person_id, model_id in (
        Credit.objects.filter(
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

    result: list[dict[str, Any]] = []
    for p in people:
        thumb = None
        person_id = p.pk
        tm_id = person_thumb_model.get(person_id)
        tm = thumb_models.get(tm_id) if tm_id else None
        if tm:
            t, _ = extract_image_urls(
                tm.extra_data or {},
                thumb_media.get(tm.pk),
                min_rank=min_rank,
            )
            if t:
                thumb = t
        result.append(
            {
                "name": p.name,
                "slug": p.slug,
                "aliases": [a.value for a in p.aliases.all()],
                "credit_count": cast(HasCreditCount, p).credit_count,
                "thumbnail_url": thumb,
            }
        )
    return set_cached_response(people_all_key(), _ALL_ADAPTER, result)


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

    specs = plan_scalar_field_claims(Person, data.fields, entity=person)

    execute_claims(
        person, specs, user=request.user, note=data.note, citation=data.citation
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
        citation=data.citation,
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
    # null-inclusive ``active_status_q`` can't be used alone because
    # ``series__status__isnull=True`` matches any Credit where series is
    # unset, regardless of the model's status. Scope each branch to the
    # side that's actually populated.
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
            person, user=request.user, note=data.note, citation=data.citation
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
    if person.status != "deleted":
        return Status(422, ErrorDetailSchema(detail="Person is not deleted."))

    execute_claims(
        person,
        [ClaimSpec(field_name="status", value="active")],
        user=request.user,
        action=ChangeSetAction.EDIT,
        note=data.note,
        citation=data.citation,
    )

    refreshed = get_object_or_404(_person_qs(), **{Person.public_id_field: public_id})
    return _serialize_person_detail(refreshed)
