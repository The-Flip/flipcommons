import importlib
from typing import Never

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.models import Max
from django.http import HttpRequest, JsonResponse
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError, ValidationError
from ninja.security import django_auth

from apps.catalog.api.export import export_rate_limit_summary, export_router
from apps.catalog.api.public_filter import filter_rate_limit_summary, filter_router
from apps.catalog.engine.entity_api.field_constraints import FieldConstraintSchema
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.cache_control import public_api_freshness_summary
from apps.core.exceptions import StructuredApiError, StructuredValidationError
from apps.provenance.models import IngestRun

# Internal API: every listing/read/write endpoint that powers this site's own UI.
# Its OpenAPI + docs endpoints are DISABLED, so the internal surface is never
# served publicly — external systems get no real-time-integration target. Frontend
# types are still generated from the file written by ``manage.py
# export_openapi_schema`` (it calls ``api.get_openapi_schema()`` directly, which is
# unaffected by ``openapi_url=None``), and the boundary tests do the same.
api = NinjaAPI(
    title="API",
    urls_namespace="api",
    openapi_url=None,
    docs_url=None,
)

# Public API: the documented, externally-consumed surface. A SEPARATE NinjaAPI so
# its OpenAPI document *is* exactly the published surface — publication is by
# location, not by annotation, so an internal endpoint cannot leak into it
# through a forgotten marker. Mounted at /api/public/ (config/urls.py); each
# router mounted here is a section of the published reference (its tags render
# as the section headings). Abuse is capped per-IP by the views (the project's
# sanctioned IP limiter), which raises StructuredApiError — so public_api
# registers the shared structured-error handler below.
public_api = NinjaAPI(
    title="Flipcommons Public API",
    version="1.0.0",
    description=(
        "The public Flipcommons API: bulk export of catalog records, plus a "
        'filtering endpoint that answers "which models match" so you don\'t '
        "have to reimplement the catalog's relationships client-side.\n\n"
        "Please be gentle on the system: save the exported data and do the rest "
        "of your operations locally on your exported copy, joining the filter "
        "endpoint's ids against it. Requests are rate-limited per IP — "
        # Limits derived from the live config so the published numbers never go stale.
        f"exports to {export_rate_limit_summary()}, filtering to "
        f"{filter_rate_limit_summary()}; a 429 with a Retry-After header "
        "means you've exceeded a limit.\n\n"
        "Responses are cached for up to "
        f"{public_api_freshness_summary()} and each URL expires individually, "
        "so each response reflects the catalog at a different moment: "
        "a record referenced in one may be missing from another. Dangling "
        "references will resolve as fresher responses arrive."
    ),
    urls_namespace="public",
)
public_api.add_router("/export/", export_router)
public_api.add_router("/filter/", filter_router)


class SiteStatsSchema(Schema):
    titles: int
    models: int
    manufacturers: int
    people: int


@api.get("/stats", response=SiteStatsSchema)
def stats(request: HttpRequest) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
                SELECT
                (SELECT COUNT(*) FROM catalog_title),
                (SELECT COUNT(*) FROM catalog_machinemodel),
                (SELECT COUNT(*) FROM catalog_manufacturer),
                (SELECT COUNT(*) FROM catalog_person)
            """
        )
        row = cursor.fetchone()
        assert row is not None
        titles, models, manufacturers, people = row
    return {
        "titles": titles,
        "models": models,
        "manufacturers": manufacturers,
        "people": people,
    }


@api.get("/health")
def health(request: HttpRequest) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return {"status": "ok"}


class VersionSchema(Schema):
    """What code is running and which data patch the catalog is current to.

    Deliberately narrow. Runtime, library and migration detail is pure
    reconnaissance value with no consumer value, so it stays out.
    """

    commit: str
    data_patch: str | None


@api.get("/version", response=VersionSchema)
def version(request: HttpRequest) -> VersionSchema:
    """Build and data-freshness identity.

    Kept off ``/health`` on purpose: that route is the load balancer's
    liveness probe and shouldn't grow a table read.

    ``data_patch`` is the applied-ledger high-water mark: the highest-numbered
    patch this database has successfully applied. Failed attempts rolled back,
    so they changed nothing and don't count.
    """
    applied = IngestRun.objects.filter(
        status=IngestRun.Status.SUCCESS,
        patch_id__isnull=False,
    ).aggregate(patch=Max("patch_id"))
    return VersionSchema(
        commit=settings.GIT_COMMIT_SHA,
        data_patch=applied["patch"],
    )


class _SentryTestError(RuntimeError):
    """Raised by ``/api/sentry_test`` to verify the Sentry pipeline.

    Distinct type so events from this route group together in Sentry
    and are trivially filterable in the issue stream.
    """


@api.get("/sentry_test", auth=django_auth)
@requires(Activity.OBSERVABILITY_DEBUG)
def sentry_test(request: HttpRequest) -> Never:
    """Deliberately raise so the Sentry pipeline can be verified.

    Gated by ``Activity.OBSERVABILITY_DEBUG`` (staff-only). Supports the
    post-deploy Sentry pipeline verification. See docs/Observability.md.
    """
    raise _SentryTestError("Deliberate exception from /api/sentry_test")


# ---------------------------------------------------------------------------
# Router autodiscovery — each app's api module exports a `routers` list of
# (prefix, router) tuples.  Adding a new router only requires editing the
# app's own api module; this file never needs to change.
# ---------------------------------------------------------------------------


def _discover_routers() -> None:
    for app_config in apps.get_app_configs():
        module_path = f"{app_config.name}.api"
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError as exc:
            if exc.name == module_path:
                continue  # app has no api module — fine
            raise  # broken import inside an existing api module — crash
        for prefix, router in getattr(module, "routers", []):
            api.add_router(prefix, router)


_discover_routers()


# ---------------------------------------------------------------------------
# Structured API errors — every subclass of StructuredApiError routes through
# the single handler below. Subclasses declare ``kind``, ``status``, and
# implement ``to_body()`` / ``extra_headers()``. django-ninja dispatches
# ``@api.exception_handler`` by ``isinstance`` (walks the MRO), so subclasses
# need no per-class handler registration.
# ---------------------------------------------------------------------------


def _structured_error_response(exc: StructuredApiError) -> JsonResponse:
    response = JsonResponse(
        {"detail": {"kind": exc.kind, "message": exc.message, **exc.to_body()}},
        status=exc.status,
    )
    for header, value in exc.extra_headers().items():
        response[header] = value
    return response


# Registered on both APIs: the internal API for its full structured-error
# taxonomy, and the public API whose structured errors are the rate-limit 429
# (RateLimitExceededError → {kind, retry_after} + Retry-After) and validation
# 400s. Same wire shape on both. The decorator returns the function unchanged,
# so stacking just adds a second registration.
@api.exception_handler(StructuredApiError)
@public_api.exception_handler(StructuredApiError)
def _handle_structured_api_error(
    request: HttpRequest, exc: StructuredApiError
) -> JsonResponse:
    return _structured_error_response(exc)


# Pydantic ``loc`` paths begin with the request source — strip these so the
# leaf names align with StructuredValidationError's flat field keys.
_REQUEST_SOURCES = frozenset({"body", "query", "path", "header", "cookie", "form"})


# Registered on both APIs, like the structured handler above: the public
# filter route documents ValidationErrorSchema for its 422s, so a pydantic
# binding failure (`year_min=nope`) must produce the same structured object
# as the route's own validation errors, not Ninja's default error array.
@api.exception_handler(ValidationError)
@public_api.exception_handler(ValidationError)
def _handle_pydantic_validation_error(
    request: HttpRequest, exc: ValidationError
) -> JsonResponse:
    field_errors: dict[str, str] = {}
    form_errors: list[str] = []
    for err in exc.errors:
        loc = err.get("loc") or ()
        msg = err.get("msg", "Invalid value.")
        # Use the last loc segment as the field key. The per-field
        # error renderer keys on bare names ("year", "slug") — matching
        # what application-thrown StructuredValidationError uses. Loc
        # paths from Pydantic include request source + nesting
        # ("body", "gameplay_features", 0, "slug"); collapsing to the leaf
        # preserves UI compatibility. Trade-off: leaf-name collisions in
        # nested payloads (two fields named "slug") map to the same key.
        # Acceptable because malformed-body errors are programmer bugs,
        # not user-facing field corrections; the inline-render path that
        # *does* care about per-field accuracy is fed by
        # StructuredValidationError, which produces flat keys directly.
        leaf = str(loc[-1]) if loc else ""
        if leaf and leaf not in _REQUEST_SOURCES:
            field_errors[leaf] = msg
        else:
            form_errors.append(msg)
    # Constructed only to route through the shared response helper; not raised.
    return _structured_error_response(
        StructuredValidationError(
            message="Invalid request.",
            field_errors=field_errors,
            form_errors=form_errors,
        )
    )


# ---------------------------------------------------------------------------
# Field constraints — single source of truth for numeric validation
# ---------------------------------------------------------------------------


@api.get(
    "/field-constraints/{entity_type}",
    response=dict[str, FieldConstraintSchema],
    exclude_none=True,
)
def get_field_constraints(
    request: HttpRequest, entity_type: str
) -> dict[str, FieldConstraintSchema]:
    """Return numeric field constraints derived from model validators."""
    from apps.catalog.engine.entity_api.field_constraints import (
        get_field_constraints as _get,
    )
    from apps.core.entity_types import get_linkable_model
    from apps.provenance.models import ClaimControlledModel

    try:
        model_class = get_linkable_model(entity_type)
    except ValueError:
        raise HttpError(404, f"Unknown entity type: {entity_type}") from None

    # All registered linkable models extend ClaimControlledModel via
    # CatalogModel — surface a misconfigured registry as a server error
    # rather than disguising it as 404.
    if not issubclass(model_class, ClaimControlledModel):
        raise RuntimeError(
            f"Linkable model for entity_type={entity_type!r} "
            f"({model_class.__name__}) is not a ClaimControlledModel subclass"
        )
    return _get(model_class)
