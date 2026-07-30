"""Games router — the heterogeneous listing (Title and Model cards, rolled up).

One row per *card* under the Title ➡ Model ➡ Variant roll-up
(``_game_rows.py``): a Title when every live Model matches the Model-only
dimensions, else one card per matching Model, with Variants absorbed into a
matching parent. This module owns the wire contract and hydration; the row
algebra and the facet fan-out live in ``_game_rows.py`` / ``_game_facets.py``.

Only the listing GET and its page endpoint live here. Everything Title-grain —
create, claims, lifecycle — stays under ``/api/titles/``: a "game" is not a
record type anything can be created as.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from django.db.models import F, Max, Prefetch
from django.http import HttpRequest, HttpResponse
from ninja import Query, Router, Schema
from ninja.params.functions import Query as QueryParam
from pydantic import Field, TypeAdapter

from apps.core.licensing import get_minimum_display_rank
from apps.media.helpers import displayed_primary_media, media_prefetch

from ..cache import games_facets_key, get_cached_response, set_cached_response
from ..engine.query.constants import DEFAULT_PAGE_SIZE
from ..engine.query.facet_helpers import FacetOption
from ..models import MachineModel, Title
from ._game_facets import GameFacetOptions, PlayerCountOption, game_facet_counts
from ._game_rows import (
    _SORT_YEAR_GUARD,
    GameFilters,
    GameRow,
    game_rows_merged,
)
from ._search_sections import description_match_q
from ._typing import FacetOptionDict
from .images import extract_image_urls
from .schemas import EntityRef, FacetOptionSchema

# ---------------------------------------------------------------------------
# Wire schemas
# ---------------------------------------------------------------------------


class GameCardSchema(Schema):
    """One listing card — a Title or a Model, discriminated by ``entity_type``.

    Slim by design — only the fields list rows render. Facet arrays live on the
    page endpoint's ``filter_options``, not on every row. A Title card's
    ``year`` / ``manufacturer`` / ``thumbnail_url`` come from its representative
    Model (display only — never a filter input); a Model card's are its own.
    """

    # The serializer reads the ``entity_type`` ClassVars off the model classes;
    # the Literal is the narrowed wire contract, not a second source of truth.
    entity_type: Literal["title", "model"] = Field(
        description="Which record this card is: a title or a machine model."
    )
    name: str = Field(description="The record's display name.")
    slug: str = Field(description="The record's URL slug.")
    year: int | None = Field(None, description="Release year, if known.")
    manufacturer: EntityRef | None = Field(
        None, description="The record's manufacturer."
    )
    thumbnail_url: str | None = Field(
        None, description="URL of a thumbnail image, if available."
    )


class GameListPageSchema(Schema):
    """A page of game cards: ``items`` holds this page's rows; ``count`` is the
    total number of matching cards across all pages."""

    items: list[GameCardSchema]
    count: int


class GameFilterQuerySchema(Schema):
    """Every listing filter dimension as query params — one vocabulary end to
    end (URL ⇄ this schema ⇄ ``GameFilters``). Multi-value params are
    **repeated** (``theme=a&theme=b``), read natively as ``list[str]``."""

    q: str = Field(
        "",
        description=(
            "Free-text search. Accent- and case-insensitive substring match "
            "against title and model names and abbreviations."
        ),
    )
    manufacturer: str | None = Field(
        None,
        description="Manufacturer slug (see `GET /api/manufacturers/`).",
    )
    person: str | None = Field(
        None,
        description=(
            "Person slug (see `GET /api/people/`). Matches records this person "
            "is credited on."
        ),
    )
    tech_gen: str | None = Field(
        None,
        description="Technology-generation slug (see `GET /api/technology-generations/`).",
    )
    display_type: str | None = Field(
        None,
        description="Display-type slug (see `GET /api/display-types/`).",
    )
    system: str | None = Field(
        None,
        description="System slug (see `GET /api/systems/`).",
    )
    franchise: str | None = Field(
        None,
        description="Franchise slug (see `GET /api/franchises/`).",
    )
    series: str | None = Field(
        None,
        description="Series slug (see `GET /api/series/`).",
    )
    player_count: int | None = Field(
        None,
        description="Number of players a machine supports. `6` matches 6 or more.",
    )
    year_min: int | None = Field(None, description="Earliest release year, inclusive.")
    year_max: int | None = Field(None, description="Latest release year, inclusive.")
    theme: list[str] = Field(
        [],
        description=(
            "Theme slug (see `GET /api/themes/`). Repeat to require several "
            "(`theme=a&theme=b`); a parent theme also matches its sub-themes."
        ),
    )
    feature: list[str] = Field(
        [],
        description=(
            "Gameplay-feature slug (see `GET /api/gameplay-features/`). Repeatable; "
            "a parent feature also matches its sub-features."
        ),
    )
    reward_type: list[str] = Field(
        [],
        description=(
            "Reward-type slug (see `GET /api/reward-types/`). Repeatable; all "
            "supplied slugs must match."
        ),
    )

    def to_filters(self) -> GameFilters:
        return GameFilters(
            q=self.q or "",
            manufacturer=self.manufacturer,
            person=self.person,
            tech_gen=self.tech_gen,
            display_type=self.display_type,
            system=self.system,
            franchise=self.franchise,
            series=self.series,
            player_count=self.player_count,
            year_min=self.year_min,
            year_max=self.year_max,
            themes=tuple(self.theme),
            features=tuple(self.feature),
            reward_types=tuple(self.reward_type),
        )


class PlayerCountOptionSchema(Schema):
    value: int
    count: int


class GameFilterOptionsSchema(Schema):
    manufacturer: list[FacetOptionSchema] = []
    person: list[FacetOptionSchema] = []
    tech_gen: list[FacetOptionSchema] = []
    display_type: list[FacetOptionSchema] = []
    system: list[FacetOptionSchema] = []
    reward_type: list[FacetOptionSchema] = []
    theme: list[FacetOptionSchema] = []
    feature: list[FacetOptionSchema] = []
    franchise: list[FacetOptionSchema] = []
    series: list[FacetOptionSchema] = []
    player_count: list[PlayerCountOptionSchema] = []


class GameFacetsPageSchema(Schema):
    """The /games page endpoint payload — facet options plus the query-only
    count (cards come from ``GET /api/games/``)."""

    filter_options: GameFilterOptionsSchema
    # Cards matching `q` alone, ignoring active facets; null when there is no
    # `q`. Drives the "create this title?" prompt — see `_query_only_count`.
    query_count: int | None = None


_FACETS_ADAPTER: TypeAdapter[GameFacetsPageSchema] = TypeAdapter(GameFacetsPageSchema)


# ---------------------------------------------------------------------------
# Hydration + serialization
# ---------------------------------------------------------------------------


def _card_models_prefetch() -> Prefetch[str, Any, str]:
    """Prefetch each title's active non-variant models (ordered
    first-model-first) with manufacturer and all ready media — the shape a
    Title card needs to render its representative. Model rows do **not** load
    through this: they hydrate directly as their own queryset.

    The displayed primary is selected at read time (``displayed_primary_media``),
    so this loads all ``asset__status="ready"`` rows via ``media_prefetch()``
    rather than an ``is_primary=True`` subset."""
    return Prefetch(
        "machine_models",
        queryset=MachineModel.first_model_candidates()
        .select_related("corporate_entity__manufacturer")
        .prefetch_related(media_prefetch()),
        to_attr="card_models",
    )


def _manufacturer_ref(model: MachineModel | None) -> EntityRef | None:
    if model is None:
        return None
    ce = model.corporate_entity
    mfr = ce.manufacturer if ce and ce.manufacturer else None
    if mfr is None:
        return None
    return EntityRef(public_id=mfr.public_id, name=mfr.name)


def _serialize_title_card(title: Title, *, min_rank: int) -> GameCardSchema:
    """A Title card: identity from the Title, display fields from the
    representative (``card_models[0]``)."""
    models: list[MachineModel] = getattr(title, "card_models", [])
    first = models[0] if models else None
    thumbnail_url: str | None = None
    if first is not None:
        thumbnail_url, _ = extract_image_urls(
            first.extra_data or {},
            displayed_primary_media(first),
            min_rank=min_rank,
        )
    return GameCardSchema(
        entity_type=Title.entity_type,
        name=title.name,
        slug=title.slug,
        year=first.year if first else None,
        manufacturer=_manufacturer_ref(first),
        thumbnail_url=thumbnail_url,
    )


def _serialize_model_card(model: MachineModel, *, min_rank: int) -> GameCardSchema:
    """A Model card: every field is the Model's own."""
    thumbnail_url, _ = extract_image_urls(
        model.extra_data or {},
        displayed_primary_media(model),
        min_rank=min_rank,
    )
    return GameCardSchema(
        entity_type=MachineModel.entity_type,
        name=model.name,
        slug=model.slug,
        year=model.year,
        manufacturer=_manufacturer_ref(model),
        thumbnail_url=thumbnail_url,
    )


def _hydrate_cards(rows: Sequence[GameRow], *, min_rank: int) -> list[GameCardSchema]:
    """One query per kind (plus prefetches), then serialize in row order."""
    title_pks = [r.pk for r in rows if r.kind == Title.entity_type]
    model_pks = [r.pk for r in rows if r.kind == MachineModel.entity_type]
    titles = {
        t.pk: t
        for t in Title.objects.filter(pk__in=title_pks).prefetch_related(
            _card_models_prefetch()
        )
    }
    models = {
        m.pk: m
        for m in MachineModel.objects.filter(pk__in=model_pks)
        .select_related("corporate_entity__manufacturer")
        .prefetch_related(media_prefetch())
    }
    return [
        _serialize_title_card(titles[r.pk], min_rank=min_rank)
        if r.kind == Title.entity_type
        else _serialize_model_card(models[r.pk], min_rank=min_rank)
        for r in rows
    ]


# ---------------------------------------------------------------------------
# The listing endpoint
# ---------------------------------------------------------------------------

games_router = Router(tags=["games"])


@games_router.get("/", response=GameListPageSchema)
def list_games(
    request: HttpRequest,
    filters: Query[GameFilterQuerySchema],
    page: Annotated[int, QueryParam(1, description="Page number, 1-based.")] = 1,
) -> GameListPageSchema:
    """Pinball titles and models at card grain, paginated. Narrow with the
    filters and the search (``q``). Ordered by release year (newest first),
    then alphabetically.

    All filters combine with AND."""
    rows = game_rows_merged(filters.to_filters())
    size = DEFAULT_PAGE_SIZE
    start = (max(page, 1) - 1) * size
    min_rank = get_minimum_display_rank()
    return GameListPageSchema(
        items=_hydrate_cards(rows[start : start + size], min_rank=min_rank),
        count=len(rows),
    )


# ---------------------------------------------------------------------------
# The page endpoint payload (facet options + query count)
# ---------------------------------------------------------------------------


def _facet_option_dicts(options: list[FacetOption]) -> list[FacetOptionDict]:
    return [
        {"public_id": o.public_id, "name": o.name, "count": o.count} for o in options
    ]


def _filter_options_payload(opts: GameFacetOptions) -> dict[str, object]:
    """``GameFacetOptions`` → the JSON-able dict the page endpoint returns (and
    caches). Plain dicts (not Schema instances) so the cache's ``json.dumps``
    fast path and the live path stay byte-equivalent (see
    ``set_cached_response``)."""
    players: list[PlayerCountOption] = opts.player_count
    return {
        "filter_options": {
            "manufacturer": _facet_option_dicts(opts.manufacturer),
            "person": _facet_option_dicts(opts.person),
            "tech_gen": _facet_option_dicts(opts.tech_gen),
            "display_type": _facet_option_dicts(opts.display_type),
            "system": _facet_option_dicts(opts.system),
            "reward_type": _facet_option_dicts(opts.reward_type),
            "theme": _facet_option_dicts(opts.theme),
            "feature": _facet_option_dicts(opts.feature),
            "franchise": _facet_option_dicts(opts.franchise),
            "series": _facet_option_dicts(opts.series),
            "player_count": [{"value": p.value, "count": p.count} for p in players],
        }
    }


def _query_only_count(f: GameFilters) -> int | None:
    """Count cards matching ``q`` **alone**, ignoring every other active facet.

    Drives the "create this title?" prompt: a zero here means the name is
    genuinely free, whereas the filtered ``count`` can be zero merely because
    a facet is hiding an existing record (filter to Williams, search a Stern
    title). A search that finds a Model must not offer to create its Title,
    so this reuses the listing rows over a ``q``-only filter set — the exact
    predicate search uses, Model names included, so the two can't drift.
    ``None`` when there is no ``q`` — the prompt never shows without one."""
    # Trim before testing: a whitespace-only `q` is empty to the (trimmed)
    # prompt, so skip it rather than run a near-whole-catalog `icontains " "`.
    if not f.q.strip():
        return None
    return len(game_rows_merged(GameFilters(q=f.q)))


def games_facets_response(f: GameFilters) -> HttpResponse:
    """Build the `/api/pages/games` response. The no-filter payload is cached
    (hottest path, static between catalog edits); filtered requests compute
    live.

    The cache key is audience-scoped and the live branch sets ``Vary: Cookie``
    for consistency/insurance, not because the payload varies by audience: the
    facet counts gate on liveness only, carrying no licensing input, so they
    are audience-invariant today. Audience scoping is cheap insurance if a
    licensing-gated input is ever added."""
    if f == GameFilters():
        cached = get_cached_response(games_facets_key())
        if cached is not None:
            return cached
        # Compute only on a miss — never recompute when about to serve the
        # cache. The no-filter path has no `q`, so `query_count` is always
        # null here.
        payload = _filter_options_payload(game_facet_counts(f))
        payload["query_count"] = None
        return set_cached_response(games_facets_key(), _FACETS_ADAPTER, payload)
    payload = _filter_options_payload(game_facet_counts(f))
    payload["query_count"] = _query_only_count(f)
    json_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    response = HttpResponse(json_bytes, content_type="application/json")
    response["Vary"] = "Cookie"
    return response


# ---------------------------------------------------------------------------
# Global search — the Games section of GET /api/pages/search
# ---------------------------------------------------------------------------


class GameSearchSectionSchema(Schema):
    """The Games section of the global ``/search`` page: up to 10 cards plus a
    ``has_more`` flag (the frontend links to ``/titles?q=`` for the rest).
    ``items`` reuses the listing card so a section row matches the ``/games``
    grid exactly."""

    items: list[GameCardSchema]
    has_more: bool


_SEARCH_LIMIT = 10


def game_search_section(q: str, *, min_rank: int) -> GameSearchSectionSchema:
    """Top ≤10 game cards matching ``q`` — the same rows, order and serializer
    as the listing, so the section matches ``/titles?q=`` exactly.

    Titles matched only by their long-form ``description`` rank *below* the
    name/alias tier, and the tier is deliberately **not** routed through the
    roll-up: a description-matched Title is appended as an extra card and never
    absorbs a Model row already carding under the same Title (the product
    doc's "description is a tier, not a dimension"). It also never feeds the
    record-creation ``query_count`` gate."""
    rows = game_rows_merged(GameFilters(q=q))
    items = _hydrate_cards(rows[:_SEARCH_LIMIT], min_rank=min_rank)
    if len(rows) > _SEARCH_LIMIT:
        return GameSearchSectionSchema(items=items, has_more=True)
    # Room left — fill from the description tier, de-duplicated against the
    # name-tier *Title* rows only (a Model row must not suppress its Title).
    fill = _SEARCH_LIMIT + 1 - len(rows)
    seen = [r.pk for r in rows if r.kind == Title.entity_type]
    description_titles = list(
        Title.objects.active()
        .filter(description_match_q(q))
        .exclude(pk__in=seen)
        .annotate(sort_year=Max("machine_models__year", filter=_SORT_YEAR_GUARD))
        .order_by(F("sort_year").desc(nulls_last=True), "name", "pk")
        .prefetch_related(_card_models_prefetch())[:fill]
    )
    items += [_serialize_title_card(t, min_rank=min_rank) for t in description_titles]
    return GameSearchSectionSchema(
        items=items[:_SEARCH_LIMIT],
        has_more=len(rows) + len(description_titles) > _SEARCH_LIMIT,
    )
