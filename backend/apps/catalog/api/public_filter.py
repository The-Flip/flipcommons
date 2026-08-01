"""The public filtering API: ``GET /api/public/filter/models/``.

The published half of the listing engine. It reads the same dimension
vocabulary as the games listing (``GameDimensionQuerySchema``) and answers
with the same predicate (``matching_models``) — but flat, at Model grain,
with none of the listing's roll-up. The roll-up is a reader-facing display
rule; a machine consumer counting machines wants the matching set itself,
and rolling Models into a unanimous Title card would corrupt exactly the
counts this route exists to serve. The two surfaces therefore disagree on
numbers by design, and must never be reconciled.

The response is identity-only: ``{count, public_ids}``, unpaginated. The
bulk export (``GET /api/public/export/models/``) carries every field of
every Model — including ``title`` — keyed by ``public_id``, so consumers
join these ids against their saved copy of the export. The two surfaces are
companions: the export carries the records, this route answers "which ones".

Strictness inverts the listing's twice here, both deliberately:

- **An unknown ``edge`` key is an error, where the listing matches
  nothing.** Match-nothing is right for a reader clicking a stale bookmark
  and wrong for an integration, where a typo must fail loudly rather than
  return a confident wrong answer. Vocabulary *slugs* keep match-nothing —
  a slug can legitimately be retired, and an empty result is then a true
  answer.
- **An unknown query param name is an error, where the listing ignores
  it.** The same typo argument one level up: ``edge_type=`` silently
  ignored would return the whole catalog. This also actively documents
  what is not here — ``q`` (unpublished; its accent folding is
  backend-dependent) and ``page`` (the response is unpaginated) both fail
  rather than silently doing nothing.
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from ninja import Query, Router, Schema
from pydantic import Field

from apps.core.exceptions import StructuredValidationError
from apps.core.rate_limits import RateLimitSpec, check_and_record_ip
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema

from ..models import MachineModel
from ._edge_vocabulary import EDGE_KEYS, parse_edge_value
from ._game_rows import matching_models
from .games import GameDimensionQuerySchema

filter_router = Router(tags=["filter"])


# Its own bucket, sized separately from the export's — a filter call is the
# cheap alternative to re-syncing a dump, so it must not charge the sync
# budget (rationale + numbers: settings.FILTER_RATELIMIT_IP). Built
# per-request from settings so the cap is tunable at runtime.
def _filter_rate_limit_spec() -> RateLimitSpec:
    limit, window = settings.FILTER_RATELIMIT_IP
    return RateLimitSpec(bucket="filter", limit=limit, window_seconds=window)


def filter_rate_limit_summary() -> str:
    """Human-readable budget for the public API description, derived from the
    configured spec so the published number never goes stale."""
    limit, window = settings.FILTER_RATELIMIT_IP
    per_hour = round(limit * 3600 / window)
    return f"{per_hour} filter requests per hour"


class FilterModelsSchema(Schema):
    """Which Models match: identity only, joined against the bulk export."""

    count: int = Field(description="Number of matching models.")
    public_ids: list[str] = Field(
        description=(
            "The `slug` (aka `public_id`) of every matching model, ascending. "
            "Join against your saved copy of `GET /export/models/` to get the "
            "rest of the fields on the model."
        )
    )


_DECLARED_PARAMS = frozenset(GameDimensionQuerySchema.model_fields)


def _reject_unknown_params(request: HttpRequest) -> None:
    unknown = sorted(set(request.GET) - _DECLARED_PARAMS)
    if unknown:
        raise StructuredValidationError(
            message="Unknown query parameter(s).",
            form_errors=[
                f"Unknown query parameter {name!r}. Valid parameters: "
                f"{', '.join(sorted(_DECLARED_PARAMS))}."
                for name in unknown
            ],
        )


def _reject_unknown_edge_values(values: list[str]) -> None:
    bad = sorted(v for v in values if parse_edge_value(v) is None)
    if bad:
        raise StructuredValidationError(
            message="Unknown relationship key.",
            field_errors={
                "edge": (
                    f"Unknown value(s): {', '.join(bad)}. Valid keys: "
                    f"{', '.join(EDGE_KEYS)} — each optionally suffixed "
                    "':in' for the inbound direction."
                )
            },
        )


@filter_router.get(
    "/models/",
    response={
        200: FilterModelsSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    summary="Filter models",
    description=(
        "Returns unpaginated list of every model matching all the specified "
        "filters.\n\n"
        "Repeat a parameter to give it several values — each parameter's "
        "description says whether repeating it means AND or OR. A mistyped "
        "parameter name or edge value is an error. A filter value that "
        "doesn't exist in the catalog (say, a manufacturer slug that isn't "
        "there) is not an error: it simply matches no models."
    ),
)
def filter_models(
    request: HttpRequest, filters: Query[GameDimensionQuerySchema]
) -> FilterModelsSchema:
    check_and_record_ip(request, _filter_rate_limit_spec())
    _reject_unknown_params(request)
    _reject_unknown_edge_values(filters.edge)
    id_field = MachineModel.public_id_field
    public_ids = list(
        matching_models(filters.to_filters())
        # The theme/feature dimensions chain M2M joins that duplicate rows.
        .distinct()
        .order_by(id_field)
        .values_list(id_field, flat=True)
    )
    return FilterModelsSchema(count=len(public_ids), public_ids=public_ids)
