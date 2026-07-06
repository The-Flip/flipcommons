"""API endpoints for the provenance app.

Routers: sources, claims, changesets, pages, citation-instances.
Auto-discovered via the ``routers`` list convention in config/api.py.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router
from ninja.decorators import decorate_view
from ninja.errors import HttpError
from ninja.responses import Status
from ninja.security import django_auth

from apps.citation.deep_links import deep_linked_url
from apps.citation.models import CitationInstance, CitationSource
from apps.core.api_helpers import authed_user
from apps.core.authz.enforce import enforce
from apps.core.authz.evaluator import policy_user
from apps.core.authz.markers import gated_inline, requires
from apps.core.authz.types import Activity
from apps.core.schemas import ErrorDetailSchema

from . import citation_writer
from .models import ClaimControlledModel, Source
from .page_endpoints import pages_router
from .schemas import (
    CitationInstanceBatchSchema,
    CitationInstanceCreateSchema,
    CitationInstanceSchema,
    CitationLinkSchema,
    CitationSourceSchema,
    RevertNoteSchema,
    UndoChangeSetSchema,
    UndoResultSchema,
)

sources_router = Router(tags=["sources", "private"])


@sources_router.get("/", response=list[CitationSourceSchema])
@decorate_view(cache_control(no_cache=True))
def list_sources(request: HttpRequest) -> list[Source]:
    return list(Source.objects.all())


# ── Claim and ChangeSet mutations (revert, undo) ───────────────────


claims_router = Router(tags=["claims", "private"])
changesets_router = Router(tags=["changesets", "private"])


@claims_router.post(
    "/{claim_id}/revert/",
    auth=django_auth,
    response={
        204: None,
        404: ErrorDetailSchema,
        422: ErrorDetailSchema,
    },
)
@gated_inline(Activity.CLAIM_REVERT)
def revert_claim(
    request: HttpRequest, claim_id: int, data: RevertNoteSchema
) -> Status[None] | Status[ErrorDetailSchema]:
    """Revert (deactivate) a single user claim and re-resolve its entity.

    The claim carries its own entity reference (``content_type`` +
    ``object_id``), so we resolve the entity from the claim rather than
    requiring it in the URL.
    """
    from django.core.exceptions import ObjectDoesNotExist

    from .models import Claim
    from .revert import RevertError, execute_revert

    user = authed_user(request)
    try:
        claim = Claim.objects.select_related("content_type").get(pk=claim_id)
    except Claim.DoesNotExist:
        return Status(404, ErrorDetailSchema(detail="Claim not found."))

    try:
        entity = claim.content_type.get_object_for_this_type(pk=claim.object_id)
    except ObjectDoesNotExist:
        return Status(
            404, ErrorDetailSchema(detail="Entity for this claim no longer exists.")
        )

    # By construction, any entity carrying a Claim is a ClaimControlledModel.
    assert isinstance(entity, ClaimControlledModel)

    # `django_auth` covers `is_authenticated` + `is_active`, and
    # `execute_revert` only enforces the experience-required check.
    # Without this call, the rule's `email_verified` predicate would
    # never fire — for others-revert the experience check at least
    # surfaces a (different-code) 403, but self-revert would slip
    # through entirely.
    enforce(policy_user(user), Activity.CLAIM_REVERT, target=claim)

    try:
        execute_revert(entity, claim_id=claim_id, user=user, note=data.note)
    except RevertError as exc:
        return Status(exc.status_code, ErrorDetailSchema(detail=str(exc)))
    return Status(204, None)


@changesets_router.post(
    "/{changeset_id}/undo/",
    auth=django_auth,
    response={
        200: UndoResultSchema,
        404: ErrorDetailSchema,
        422: ErrorDetailSchema,
    },
)
@gated_inline(Activity.CHANGESET_UNDO)
def undo_changeset(
    request: HttpRequest, changeset_id: int, data: UndoChangeSetSchema
) -> UndoResultSchema | Status[ErrorDetailSchema]:
    """Atomically invert a DELETE ChangeSet (restore a soft-deleted tree).

    This powers the post-delete Undo toast. Scoped to delete ChangeSets
    authored by the caller; other scenarios use per-claim revert.
    """
    from .models import ChangeSet
    from .revert import UndoError, execute_undo_changeset

    user = authed_user(request)
    try:
        changeset = ChangeSet.objects.select_related("actor").get(pk=changeset_id)
    except ChangeSet.DoesNotExist:
        return Status(404, ErrorDetailSchema(detail="ChangeSet not found."))

    enforce(policy_user(user), Activity.CHANGESET_UNDO, target=changeset)

    try:
        new_cs = execute_undo_changeset(changeset, user=user, note=data.note)
    except UndoError as exc:
        return Status(422, ErrorDetailSchema(detail=str(exc)))
    return UndoResultSchema(changeset_id=new_cs.pk)


citation_instances_router = Router(tags=["citation-instances", "private"])


@citation_instances_router.get(
    "/",
    response=list[CitationInstanceSchema],
    auth=django_auth,
)
def list_citation_instances(
    request: HttpRequest, source: int | None = None, claim: int | None = None
) -> list[CitationInstanceSchema]:
    """List Citation Instances, filtered by source and/or citing claim.

    ``?claim=`` resolves through the ``ClaimCitationInstance`` join — the
    instances attached to that claim as supporting evidence. Inline
    ``[[cite:...]]`` instances carry no join rows, so they only surface via
    ``?source=``.
    """
    if source is None and claim is None:
        raise HttpError(422, "Provide ?source= or ?claim= filter.")

    qs = CitationInstance.objects.select_related("citation_source")
    if source is not None:
        qs = qs.filter(citation_source_id=source)
    if claim is not None:
        qs = qs.filter(claims=claim)
    qs = qs.order_by("-created_at")

    return [
        CitationInstanceSchema(
            id=ci.pk,
            slug=ci.slug,
            citation_source_id=ci.citation_source_id,
            citation_source_name=ci.citation_source.name,
            locator=ci.locator,
            quote=ci.quote,
            created_at=ci.created_at.isoformat(),
        )
        for ci in qs
    ]


@citation_instances_router.get(
    "/batch/",
    response={200: list[CitationInstanceBatchSchema], 422: ErrorDetailSchema},
)
def batch_citation_instances(
    request: HttpRequest, ids: str = ""
) -> list[CitationInstanceBatchSchema]:
    """Return citation instances by ID for tooltip rendering."""
    if not ids.strip():
        return []

    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError as err:
        raise HttpError(422, "ids must be comma-separated integers.") from err

    if len(id_list) > 50:
        raise HttpError(422, "Maximum 50 IDs per request.")

    qs = (
        CitationInstance.objects.filter(pk__in=id_list)
        .select_related("citation_source", "citation_source__parent")
        .prefetch_related("citation_source__links")
    )

    return [
        CitationInstanceBatchSchema(
            id=ci.pk,
            source_name=ci.citation_source.name,
            source_type=ci.citation_source.source_type,
            author=ci.citation_source.author,
            year=ci.citation_source.year,
            locator=ci.locator,
            quote=ci.quote,
            links=[
                CitationLinkSchema(
                    url=deep_linked_url(ci.citation_source, ci.locator, link.url),
                    link_type=link.link_type,
                    display_name=link.display_name,
                )
                for link in ci.citation_source.links.all()
            ],
        )
        for ci in qs
    ]


@citation_instances_router.post(
    "/",
    response={201: CitationInstanceSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def create_citation_instance(
    request: HttpRequest, data: CitationInstanceCreateSchema
) -> Status[CitationInstanceSchema]:
    """Create a new CitationInstance for use in ``[[cite:N]]`` markers."""
    source = get_object_or_404(CitationSource, pk=data.citation_source_id)

    try:
        instance = citation_writer.create_citation_instance(data)
    except ValidationError as exc:
        raise HttpError(422, str(exc)) from exc
    except IntegrityError as exc:
        raise HttpError(422, str(exc)) from exc

    return Status(
        201,
        CitationInstanceSchema(
            id=instance.pk,
            slug=instance.slug,
            citation_source_id=instance.citation_source_id,
            citation_source_name=source.name,
            locator=instance.locator,
            quote=instance.quote,
            created_at=instance.created_at.isoformat(),
        ),
    )


routers = [
    ("/sources/", sources_router),
    ("/claims/", claims_router),
    ("/changesets/", changesets_router),
    ("/pages/", pages_router),
    ("/citation-instances/", citation_instances_router),
]
