"""API endpoints for the citation app.

Routers: citation_sources.
Auto-discovered via the ``routers`` list convention in config/api.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Protocol, cast
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status
from ninja.security import django_auth
from ninja.throttling import AuthRateThrottle

from apps.core.api_helpers import authed_user
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.schemas import ErrorDetailSchema

from .extraction import classify_input, extract_isbn, normalize_isbn
from .extractors import EXTRACTORS, Recognition, recognize_url
from .hosts import normalize_host
from .models import (
    CITATION_ROOT_DOMAIN_HOST_TAKEN_MSG,
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)
from .schemas import (
    CitationExtractDraftSchema,
    CitationExtractInputSchema,
    CitationExtractResultSchema,
    CitationRecognitionSchema,
    CitationSourceChildSchema,
    CitationSourceCreateSchema,
    CitationSourceDetailSchema,
    CitationSourceLinkCreateSchema,
    CitationSourceLinkSchema,
    CitationSourceLinkUpdateSchema,
    CitationSourceMatchSchema,
    CitationSourceParentSchema,
    CitationSourceSearchResponseSchema,
    CitationSourceSearchSchema,
    CitationSourceUpdateSchema,
)
from .url_extraction import extract_url

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

citation_sources_router = Router(tags=["citation-sources", "private"])

routers = [
    ("/citation-sources/", citation_sources_router),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _HasChildren(Protocol):
    """Structural type for rows returned by the search queryset below.

    ``.annotate(has_children=Exists(...))`` adds a boolean column that isn't
    a real model attribute. Cast at the read site to narrow mypy's view —
    same pattern as the ``Has*`` protocols in ``apps.catalog.api._typing``.
    """

    has_children: bool


def _is_abstract(source_type: str, parent_id: int | None, has_children: bool) -> bool:
    """Source is abstract if it has children or is a root web/magazine source."""
    return has_children or (parent_id is None and source_type in ("web", "magazine"))


def _clean_and_save(
    instance: models.Model,
    update_fields: Sequence[str] | None = None,
    *,
    integrity_msg: str = "",
) -> None:
    """Validate model then save.

    Converts both ``ValidationError`` (from ``full_clean``) and
    ``IntegrityError`` (from ``save``) into ``HttpError(422)``.

    *integrity_msg* is the friendly message shown when the expected unique
    constraint fires.  For unexpected integrity violations the raw DB
    message is surfaced instead.
    """
    try:
        instance.full_clean()
    except ValidationError as exc:
        if hasattr(exc, "message_dict"):
            parts = []
            for field, messages in exc.message_dict.items():
                for msg in messages:
                    parts.append(f"{field}: {msg}" if field != "__all__" else msg)
            detail = "; ".join(parts)
        else:
            detail = str(exc)
        raise HttpError(422, detail) from exc
    try:
        instance.save(update_fields=update_fields)
    except IntegrityError as exc:
        msg = str(exc).lower()
        if integrity_msg and ("unique" in msg or "duplicate" in msg):
            raise HttpError(422, integrity_msg) from exc
        raise HttpError(422, f"Integrity error: {exc}") from exc


def _detail_qs() -> QuerySet[CitationSource]:
    return CitationSource.objects.select_related("parent").prefetch_related(
        "links", "children", "children__links"
    )


def _serialize_child(child: CitationSource) -> CitationSourceChildSchema:
    return CitationSourceChildSchema(
        id=child.pk,
        name=child.name,
        source_type=child.source_type,
        year=child.year,
        isbn=child.isbn,
        skip_locator=child.skip_locator,
        urls=[link.url for link in child.links.all()],
    )


def _serialize_search_row(s: CitationSource) -> CitationSourceSearchSchema:
    has_children = cast(_HasChildren, s).has_children
    return CitationSourceSearchSchema(
        id=s.pk,
        name=s.name,
        source_type=s.source_type,
        author=s.author,
        publisher=s.publisher,
        year=s.year,
        isbn=s.isbn,
        parent_id=s.parent_id,
        has_children=has_children,
        is_abstract=_is_abstract(s.source_type, s.parent_id, has_children),
        skip_locator=s.skip_locator,
        identifier_key=s.identifier_key,
    )


def _serialize_detail(source: CitationSource) -> CitationSourceDetailSchema:
    parent: CitationSourceParentSchema | None = None
    if source.parent_id is not None:
        parent_obj = source.parent
        assert parent_obj is not None
        parent = CitationSourceParentSchema(id=source.parent_id, name=parent_obj.name)
    return CitationSourceDetailSchema(
        id=source.pk,
        name=source.name,
        source_type=source.source_type,
        author=source.author,
        publisher=source.publisher,
        year=source.year,
        month=source.month,
        day=source.day,
        date_note=source.date_note,
        isbn=source.isbn,
        description=source.description,
        identifier_key=source.identifier_key,
        skip_locator=source.skip_locator,
        parent=parent,
        links=[
            CitationSourceLinkSchema.model_validate(link, from_attributes=True)
            for link in source.links.all()
        ],
        children=[_serialize_child(child) for child in source.children.all()],
        created_at=source.created_at.isoformat(),
        updated_at=source.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Citation Source endpoints
# ---------------------------------------------------------------------------


def _is_url(q: str) -> bool:
    return q.startswith("http://") or q.startswith("https://")


def _build_recognition(rec: Recognition) -> CitationRecognitionSchema:
    """Serialize an extractors.Recognition into the API response shape."""
    child: CitationSourceMatchSchema | None = None
    if rec.child is not None:
        child = CitationSourceMatchSchema(
            id=rec.child.id,
            name=rec.child.name,
            skip_locator=rec.child.skip_locator,
        )
    return CitationRecognitionSchema(
        parent=CitationSourceParentSchema(id=rec.parent_id, name=rec.parent_name),
        child=child,
        identifier=rec.identifier,
    )


@citation_sources_router.get(
    "/search/",
    response=CitationSourceSearchResponseSchema,
    auth=django_auth,
)
def search_citation_sources(
    request: HttpRequest, q: str = ""
) -> CitationSourceSearchResponseSchema:
    """Typeahead search with URL/ISBN recognition.

    Returns search results plus optional recognition metadata when the
    input is a recognized URL or ISBN.
    """
    q = q.strip()
    if not q:
        return CitationSourceSearchResponseSchema(results=[], recognition=None)

    # --- Recognition (URL or ISBN) -----------------------------------------
    recognition: CitationRecognitionSchema | None = None
    if _is_url(q):
        rec = recognize_url(q)
        if rec is not None:
            recognition = _build_recognition(rec)

    # --- Text search -------------------------------------------------------
    text_filter = (
        Q(name__icontains=q)
        | Q(author__icontains=q)
        | Q(publisher__icontains=q)
        | Q(isbn__icontains=q)
        | Q(links__url__icontains=q)
    )
    # For ISBN-shaped input, also do exact match on normalized ISBN.
    if not _is_url(q):
        normalized_isbn = normalize_isbn(q)
        if normalized_isbn:
            text_filter = text_filter | Q(isbn=normalized_isbn)

    qs = (
        CitationSource.objects.filter(text_filter)
        .annotate(
            has_children=Exists(CitationSource.objects.filter(parent=OuterRef("pk")))
        )
        .distinct()
        .order_by("name")[:20]
    )
    return CitationSourceSearchResponseSchema(
        results=[_serialize_search_row(s) for s in qs],
        recognition=recognition,
    )


@citation_sources_router.post(
    "/",
    response={201: CitationSourceDetailSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def create_citation_source(
    request: HttpRequest, data: CitationSourceCreateSchema
) -> Status[CitationSourceDetailSchema]:
    """Create a new Citation Source, optionally with an initial link."""
    user = authed_user(request)
    parent = None
    if data.parent_id is not None:
        parent = get_object_or_404(CitationSource, pk=data.parent_id)

    # When an identifier is provided and the parent has an extractor,
    # validate, normalize, and auto-build the child name and canonical URL.
    name = data.name
    url = data.url
    identifier = data.identifier
    if identifier and parent and parent.identifier_key:
        extractor = EXTRACTORS.get(parent.identifier_key)
        if extractor:
            normalized = extractor.normalize(identifier)
            if normalized is None:
                raise HttpError(
                    422,
                    f"Invalid identifier for {extractor.source_name}: {identifier!r}",
                )
            identifier = normalized
            if not name or name == data.identifier:
                name = f"{parent.name} #{identifier}"
            if not url:
                url = extractor.build_url(identifier)

    with transaction.atomic():
        source = CitationSource(
            name=name,
            source_type=data.source_type,
            author=data.author,
            publisher=data.publisher,
            year=data.year,
            month=data.month,
            day=data.day,
            date_note=data.date_note,
            isbn=data.isbn,
            description=data.description,
            identifier=identifier,
            parent=parent,
            created_by=user,
            updated_by=user,
        )
        _clean_and_save(
            source,
            integrity_msg="A source with this ISBN or identifier already exists.",
        )

        if url:
            link_type = data.link_type or "homepage"
            link = CitationSourceLink(
                citation_source=source,
                link_type=link_type,
                url=url,
                label=data.link_label,
                created_by=user,
                updated_by=user,
            )
            _clean_and_save(link)

            # A parentless source with a homepage link owns a recognition host
            # (any source_type — see the any-root decision). Dedup belongs to
            # the interactive cite-url flow; here a host another root already
            # owns surfaces as a 422 — from full_clean's unique check (the
            # field's custom message), with integrity_msg as the create-race
            # backstop. Either way the surrounding atomic() rolls the create back.
            hostname = urlparse(url).hostname
            if parent is None and link_type == "homepage" and hostname is not None:
                domain = CitationSourceRootDomain(
                    source=source, host=normalize_host(hostname)
                )
                _clean_and_save(
                    domain, integrity_msg=CITATION_ROOT_DOMAIN_HOST_TAKEN_MSG
                )

    source = get_object_or_404(_detail_qs(), pk=source.pk)
    return Status(201, _serialize_detail(source))


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


class _ExtractThrottle(AuthRateThrottle):
    rate = "10/m"


@citation_sources_router.post(
    "/extract/",
    response={
        200: CitationExtractResultSchema,
        422: ErrorDetailSchema,
        429: ErrorDetailSchema,
    },
    auth=django_auth,
    throttle=[_ExtractThrottle("10/m")],
)
@requires(Activity.CITATION_EDIT)
def extract_citation_source(
    request: HttpRequest, data: CitationExtractInputSchema
) -> CitationExtractResultSchema:
    """Classify input and look up metadata from external APIs."""
    classified = classify_input(data.input)
    if classified is None:
        raise HttpError(422, "Unsupported input")

    kind, normalized = classified
    if kind == "isbn":
        result = extract_isbn(normalized)
    elif kind == "url":
        result = extract_url(normalized)
    else:
        raise HttpError(422, "Unsupported input")

    return CitationExtractResultSchema(
        match=CitationSourceMatchSchema(**result.match) if result.match else None,
        draft=CitationExtractDraftSchema(**asdict(result.draft))
        if result.draft
        else None,
        error=result.error,
        confidence=result.confidence,
        source_api=result.source_api,
    )


# ---------------------------------------------------------------------------
# Children / Detail / Links
# ---------------------------------------------------------------------------


@citation_sources_router.get(
    "/{source_id}/children/",
    response=list[CitationSourceChildSchema],
    auth=django_auth,
)
def list_citation_source_children(
    request: HttpRequest, source_id: int, q: str = ""
) -> list[CitationSourceChildSchema]:
    """Filtered children of a source, searched by name, URL, identifier, or ISBN."""
    parent = get_object_or_404(CitationSource, pk=source_id)
    q = q.strip()
    if not q:
        return []
    children = (
        CitationSource.objects.filter(parent=parent)
        .filter(
            Q(name__icontains=q)
            | Q(links__url__icontains=q)
            | Q(identifier__icontains=q)
            | Q(isbn__icontains=q)
        )
        .prefetch_related("links")
        .distinct()
        .order_by("name")[:20]
    )
    return [_serialize_child(child) for child in children]


@citation_sources_router.get(
    "/{source_id}/",
    response=CitationSourceDetailSchema,
    auth=django_auth,
)
def get_citation_source(
    request: HttpRequest, source_id: int
) -> CitationSourceDetailSchema:
    """Get a Citation Source with its links and children."""
    source = get_object_or_404(_detail_qs(), pk=source_id)
    return _serialize_detail(source)


@citation_sources_router.patch(
    "/{source_id}/",
    response={200: CitationSourceDetailSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def update_citation_source(
    request: HttpRequest, source_id: int, data: CitationSourceUpdateSchema
) -> CitationSourceDetailSchema:
    """Partially update a Citation Source."""
    user = authed_user(request)
    source = get_object_or_404(CitationSource, pk=source_id)
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HttpError(422, "No changes provided.")

    for attr, value in fields.items():
        setattr(source, attr, value)
    source.updated_by = user

    _clean_and_save(
        source,
        update_fields=[*fields.keys(), "updated_by", "updated_at"],
        integrity_msg="A source with this ISBN already exists.",
    )

    source = get_object_or_404(_detail_qs(), pk=source.pk)
    return _serialize_detail(source)


# ---------------------------------------------------------------------------
# Citation Source Link endpoints
# ---------------------------------------------------------------------------


@citation_sources_router.post(
    "/{source_id}/links/",
    response={201: CitationSourceLinkSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def create_citation_source_link(
    request: HttpRequest, source_id: int, data: CitationSourceLinkCreateSchema
) -> Status[CitationSourceLinkSchema]:
    """Create a link on a Citation Source."""
    user = authed_user(request)
    source = get_object_or_404(CitationSource, pk=source_id)
    link = CitationSourceLink(
        citation_source=source,
        link_type=data.link_type,
        url=data.url,
        label=data.label,
        created_by=user,
        updated_by=user,
    )
    _clean_and_save(link, integrity_msg="This URL is already linked to this source.")

    return Status(
        201, CitationSourceLinkSchema.model_validate(link, from_attributes=True)
    )


@citation_sources_router.patch(
    "/{source_id}/links/{link_id}/",
    response={200: CitationSourceLinkSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def update_citation_source_link(
    request: HttpRequest,
    source_id: int,
    link_id: int,
    data: CitationSourceLinkUpdateSchema,
) -> CitationSourceLinkSchema:
    """Partially update a link on a Citation Source."""
    user = authed_user(request)
    link = get_object_or_404(
        CitationSourceLink, pk=link_id, citation_source_id=source_id
    )
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HttpError(422, "No changes provided.")

    for attr, value in fields.items():
        setattr(link, attr, value)
    link.updated_by = user

    _clean_and_save(
        link,
        update_fields=[*fields.keys(), "updated_by", "updated_at"],
        integrity_msg="This URL is already linked to this source.",
    )

    return CitationSourceLinkSchema.model_validate(link, from_attributes=True)
