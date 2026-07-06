"""API endpoints for the citation app.

Routers: citation_sources.
Auto-discovered via the ``routers`` list convention in config/api.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Protocol, assert_never, cast

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

from apps.actors.models import Actor
from apps.core.api_helpers import authed_user
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.schemas import ErrorDetailSchema
from apps.core.types import CitationSourceId

from .deliverers import deliverer_notice_message
from .extraction import classify_input, extract_isbn, normalize_isbn
from .extractors import (
    Recognition,
    UrlDeliverer,
    UrlIdentified,
    UrlSchemeRecord,
    UrlSiteOf,
    UrlUnrecognized,
    classify_url,
    create_web_child,
    get_or_create_scheme_child,
    recognize_url,
)
from .models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)
from .psl import HostError, HostRejection, root_host_from_url
from .schemas import (
    CitationCiteUrlSchema,
    CitationExtractDelivererSchema,
    CitationExtractDraftSchema,
    CitationExtractInputSchema,
    CitationExtractResultSchema,
    CitationPageCreateSchema,
    CitationRecognitionSchema,
    CitationRecordCreateSchema,
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


def _validation_detail(exc: ValidationError) -> str:
    """Flatten a ``ValidationError`` into a human-readable 422 detail string."""
    if hasattr(exc, "message_dict"):
        parts = []
        for field, messages in exc.message_dict.items():
            for msg in messages:
                parts.append(f"{field}: {msg}" if field != "__all__" else msg)
        return "; ".join(parts)
    return str(exc)


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
        raise HttpError(422, _validation_detail(exc)) from exc
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


def _serialize_match(source: CitationSource) -> CitationSourceMatchSchema:
    """The minimal "re-cite this source" shape every child-mint endpoint returns."""
    return CitationSourceMatchSchema(
        id=source.pk,
        name=source.name,
        source_type=source.source_type,
        skip_locator=source.skip_locator,
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
        is_abstract=s.is_abstract(has_children=has_children),
        skip_locator=s.skip_locator,
        identifier_key=s.identifier_key,
    )


def _serialize_detail(source: CitationSource) -> CitationSourceDetailSchema:
    parent: CitationSourceParentSchema | None = None
    if not source.is_root:
        parent_obj = source.parent
        assert parent_obj is not None  # a non-root always has a parent loaded
        parent = CitationSourceParentSchema(id=parent_obj.pk, name=parent_obj.name)
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
            source_type=rec.child.source_type,
            skip_locator=rec.child.skip_locator,
        )
    return CitationRecognitionSchema(
        parent=CitationSourceParentSchema(id=rec.parent_id, name=rec.parent_name),
        child=child,
        identifier=rec.identifier,
        locator_hint=rec.locator_hint,
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
    # Classification, not raw recognition: a deliverer URL yields no
    # recognition row even where legacy prod data holds a misclassified root
    # for its host — the UI must never offer "Cite a page under Amazon.com"
    # (the paste's extract call surfaces the teaching notice instead). An
    # unseeded scheme-record match likewise surfaces nothing here; the
    # create paths own that rejection.
    recognition: CitationRecognitionSchema | None = None
    if _is_url(q):
        match classify_url(q):
            case (
                UrlSchemeRecord(recognition=Recognition() as rec)
                | UrlIdentified(recognition=rec)
                | UrlSiteOf(recognition=rec)
            ):
                recognition = _build_recognition(rec)
            case UrlDeliverer() | UrlSchemeRecord() | UrlUnrecognized():
                recognition = None

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
    """Create a book/magazine root or a linkless authored child.

    This endpoint owns neither URLs nor links: web roots/children are minted by
    ``cite-url``/``pages/`` and scheme children by ``records/``. It creates a
    plain authored source — a root, or a child nested under ``parent_id``.
    """
    user = authed_user(request)
    parent = None
    if data.parent_id is not None:
        parent = get_object_or_404(CitationSource, pk=data.parent_id)
        # Authored children extend their own work's hierarchy — an edition
        # under its book, an issue under its magazine. A cross-type authored
        # child (a book "edition" under a video or web root) has no meaning
        # and would sidestep the parent type's minting rules.
        if parent.source_type != data.source_type:
            raise HttpError(
                422,
                f"A {data.source_type} child can't nest under a "
                f"{parent.source_type} source — an authored child belongs to "
                f"its own work's hierarchy (an edition under its book, an "
                f"issue under its magazine).",
            )

    source = CitationSource(
        name=data.name,
        source_type=data.source_type,
        author=data.author,
        publisher=data.publisher,
        year=data.year,
        month=data.month,
        day=data.day,
        date_note=data.date_note,
        isbn=data.isbn,
        description=data.description,
        parent=parent,
        created_by=user.actor,
        updated_by=user.actor,
    )
    _clean_and_save(source, integrity_msg="A source with this ISBN already exists.")

    source = get_object_or_404(_detail_qs(), pk=source.pk)
    return Status(201, _serialize_detail(source))


def _reject_uncitable_page_url(url: str) -> None:
    """422 a URL that must never become a web page child, per classification.

    Two verdicts are uncitable as pages regardless of which parent was
    chosen: a **deliverer** copy (cite the work it delivers, never the store/
    streaming page) and a **scheme record** (mints through ``records/`` /
    ``scheme:identifier`` so the same record always dedups to one child with
    the scheme's canonical URL, owning type and locator behavior — enforced
    even before the scheme's root is seeded, via the registry-only match).
    The identity verdicts pass through: the caller owns the explicit parent
    choice.
    """
    match classify_url(url):
        case UrlDeliverer(spec=spec, kind=kind):
            raise HttpError(422, deliverer_notice_message(spec, kind))
        case UrlSchemeRecord(label=label):
            raise HttpError(
                422,
                f"This URL is a {label} record; cite it via its scheme "
                f"identifier (scheme:identifier), not as a web page.",
            )
        case UrlIdentified() | UrlSiteOf() | UrlUnrecognized():
            return
        case unreachable:
            assert_never(unreachable)


def _mint_web_child(
    parent_id: CitationSourceId, url: str, page_name: str, actor: Actor
) -> CitationSource:
    """Mint a page child via ``create_web_child``, mapping its error to a 422.

    ``create_web_child`` ``full_clean``s the child and its link and raises
    ``ValidationError`` (e.g. a malformed *url*); surface that as a 422.
    """
    try:
        return create_web_child(parent_id, url, page_name, created_by=actor)
    except ValidationError as exc:
        raise HttpError(422, _validation_detail(exc)) from exc


def _host_error_detail(reason: HostRejection) -> str:
    """The 422 message for a funnel rejection. Exhaustive over ``HostRejection``."""
    match reason:
        case HostRejection.NO_HOST:
            return "That URL has no host to create a site from."
        case HostRejection.NOT_DNS:
            return (
                "That URL's host isn't a domain name — an IP address or malformed "
                "host can't root a site."
            )
        case HostRejection.RESERVED_TLD:
            return (
                "That URL's host is a reserved test domain, so it can't root a "
                "real site."
            )
        case HostRejection.PUBLIC_SUFFIX:
            return (
                "That URL's host is a public suffix (like gov.uk); cite a page on "
                "a specific site under it instead."
            )
    assert_never(reason)


def _create_root_and_child(
    url: str, data: CitationCiteUrlSchema, actor: Actor
) -> CitationSource:
    """Create a new site root (homepage link + recognition domain) and a child.

    Roots at the URL's **registrable domain** — :func:`root_host_from_url` rounds
    a fuzzy subdomain paste (``s4.american-pinball.com``) down to one root
    (``american-pinball.com``) so future cites under the same site collapse
    together, and 422s a host that can't root a site (no host, IP literal,
    reserved TLD, bare public suffix) before any write. The root-create then runs
    in a savepoint: on a concurrent ``host`` ``unique`` violation the savepoint
    rolls back, the URL is re-recognized against the now-committed root, and the
    child nests under it.
    """
    try:
        host = root_host_from_url(url)
    except HostError as exc:
        raise HttpError(422, _host_error_detail(exc.reason)) from exc

    try:
        with transaction.atomic():
            root = CitationSource(
                name=data.site_name or host,
                source_type=CitationSource.SourceType.WEB,
                description=data.site_description,
                created_by=actor,
                updated_by=actor,
            )
            _clean_and_save(root)
            homepage = CitationSourceLink(
                citation_source=root,
                link_type=CitationSourceLink.LinkType.HOMEPAGE,
                url=f"https://{host}/",
                created_by=actor,
                updated_by=actor,
            )
            _clean_and_save(homepage)
            domain = CitationSourceRootDomain(
                source=root, host=host, created_by=actor, updated_by=actor
            )
            # validate_unique=False so the model guards (root-only clean(),
            # CHECK constraints) still fire — as a 422 — while the host-unique
            # race surfaces only as a DB IntegrityError from save() below,
            # distinct from a guard failure.
            try:
                domain.full_clean(validate_unique=False)
            except ValidationError as exc:
                raise HttpError(422, _validation_detail(exc)) from exc
            domain.save()
            parent_id = root.pk
    except IntegrityError:
        # Lost the create-root race: another request committed this host. Re-
        # recognize and nest the child under the now-existing root.
        rec = recognize_url(url)
        if rec is None:
            raise
        parent_id = rec.parent_id

    return _mint_web_child(parent_id, url, data.page_name, actor)


@citation_sources_router.post(
    "/cite-url/",
    response={201: CitationSourceMatchSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def cite_url(
    request: HttpRequest, data: CitationCiteUrlSchema
) -> Status[CitationSourceMatchSchema]:
    """Cite a web page, creating its site root and page child as needed.

    The interactive web-create flow's finalize call. The pasted URL is
    classified server-side (``classify_url``) and every verdict is handled,
    the success arms all returning the **web child** to cite (never the
    abstract root):

    * **deliverer** (Amazon, Netflix, …) → 422 with the teaching message;
      cite the work the URL delivers, never a page for its copy;
    * **scheme record** (IPDB/OPDB/…) → 422; cite it as ``scheme:identifier``
      (rejected even before the scheme's root is seeded);
    * **identified** (exact child) → reuse it;
    * **site match** → create a page child under the existing root, ignoring
      ``site_*`` (the root already exists and is never renamed from here);
    * **unrecognized** → create the site root (at the URL's registrable
      domain, or 422 if the host can't root a site) and a page child.

    One transaction; every created row is attributed to the caller.
    """
    user = authed_user(request)
    url = data.url

    with transaction.atomic():
        match classify_url(url):
            case UrlDeliverer(spec=spec, kind=kind):
                raise HttpError(422, deliverer_notice_message(spec, kind))
            case UrlSchemeRecord(label=label):
                raise HttpError(
                    422,
                    f"This URL is a {label} record; cite it via its "
                    f"scheme identifier (scheme:identifier), not the web flow.",
                )
            case UrlIdentified(child=existing):
                # An exact child already covers this URL — reuse it.
                # Classification already loaded the fields the response
                # needs, so there's nothing left to create or fetch.
                return Status(
                    201,
                    CitationSourceMatchSchema(
                        id=existing.id,
                        name=existing.name,
                        source_type=existing.source_type,
                        skip_locator=existing.skip_locator,
                    ),
                )
            case UrlSiteOf(recognition=rec):
                child = _mint_web_child(rec.parent_id, url, data.page_name, user.actor)
            case UrlUnrecognized():
                child = _create_root_and_child(url, data, user.actor)
            case unreachable:
                assert_never(unreachable)

    return Status(201, _serialize_match(child))


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
        deliverer=CitationExtractDelivererSchema(**result.deliverer._asdict())
        if result.deliverer
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


@citation_sources_router.post(
    "/{source_id}/pages/",
    response={201: CitationSourceMatchSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def create_citation_source_page(
    request: HttpRequest, source_id: int, data: CitationPageCreateSchema
) -> Status[CitationSourceMatchSchema]:
    """Mint a web page child under an explicit parent root.

    The contributor already chose the parent (the identify path), so the URL is
    not re-recognized — the page nests directly under *source_id*. The parent may
    be any root type (a web page under a magazine/book/video root is intended —
    a platform's terms or channel page is a page, not a record); the structural
    rules are the uncitable-URL classification below (deliverer copies and
    scheme records never mint as pages) and the web-flatness guard, which 422s
    a page under a web *child* parent via ``clean()``.
    """
    user = authed_user(request)
    parent = get_object_or_404(CitationSource, pk=source_id)
    _reject_uncitable_page_url(data.url)
    child = _mint_web_child(parent.pk, data.url, data.page_name, user.actor)
    return Status(201, _serialize_match(child))


@citation_sources_router.post(
    "/{source_id}/records/",
    response={201: CitationSourceMatchSchema, 422: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.CITATION_EDIT)
def create_citation_source_record(
    request: HttpRequest, source_id: int, data: CitationRecordCreateSchema
) -> Status[CitationSourceMatchSchema]:
    """Mint (or reuse) a scheme child under an explicit parent root.

    The parent root carries an ``identifier_key`` scheme (IPDB/OPDB/…); the leaf
    owns the ``{root} #{id}`` name rule and dedups by ``(root, identifier)``, so
    re-citing an existing identifier reuses its child rather than 422ing.
    """
    user = authed_user(request)
    parent = get_object_or_404(CitationSource, pk=source_id)
    try:
        child = get_or_create_scheme_child(
            parent, data.identifier, created_by=user.actor
        )
    except ValidationError as exc:
        raise HttpError(422, _validation_detail(exc)) from exc
    except ValueError as exc:
        raise HttpError(422, str(exc)) from exc
    return Status(201, _serialize_match(child))


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
    source.updated_by = user.actor

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
    request: HttpRequest,
    source_id: int,
    data: CitationSourceLinkCreateSchema,
) -> Status[CitationSourceLinkSchema]:
    """Create a link on a Citation Source."""
    user = authed_user(request)
    source = get_object_or_404(CitationSource, pk=source_id)
    link = CitationSourceLink(
        citation_source=source,
        link_type=data.link_type,
        url=data.url,
        label=data.label,
        created_by=user.actor,
        updated_by=user.actor,
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
    link.updated_by = user.actor

    _clean_and_save(
        link,
        update_fields=[*fields.keys(), "updated_by", "updated_at"],
        integrity_msg="This URL is already linked to this source.",
    )

    return CitationSourceLinkSchema.model_validate(link, from_attributes=True)
