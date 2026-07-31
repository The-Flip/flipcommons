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
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Annotated, Any, Literal, NamedTuple

from django.db.models import F, Max, Prefetch, Q
from django.http import HttpRequest, HttpResponse
from ninja import Query, Router, Schema
from ninja.params.functions import Query as QueryParam
from pydantic import Field, TypeAdapter

from apps.core.licensing import get_minimum_display_rank
from apps.core.models import SitemappedModel, active_status_q
from apps.media.helpers import displayed_primary_media, media_prefetch

from ..cache import games_facets_key, get_cached_response, set_cached_response
from ..engine.entity_api.detail import DetailPageContext
from ..engine.query.constants import DEFAULT_PAGE_SIZE
from ..engine.query.facet_helpers import FacetOption
from ..models import Credit, MachineModel, Title
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
    public_id: str = Field(description="The record's URL-identity value.")
    year: int | None = Field(None, description="Release year, if known.")
    manufacturer: EntityRef | None = Field(
        None, description="The record's manufacturer."
    )
    thumbnail_url: str | None = Field(
        None, description="URL of a thumbnail image, if available."
    )
    # Person-contextual card annotation: present only when the `person`
    # dimension is active, so a page of one person's games can say what they
    # did on each. The pattern for dimension-contingent annotations — a future
    # relationship-context field works the same way.
    roles: list[str] | None = Field(
        None,
        description=(
            "Only when filtering by `person`: that person's role names on this "
            "record (for a title, across its models). Otherwise omitted."
        ),
    )


class GameListSchema(Schema):
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
    display_subtype: str | None = Field(
        None,
        description="Display-subtype slug (see `GET /api/display-subtypes/`).",
    )
    tag: str | None = Field(
        None,
        description="Tag slug (see `GET /api/tags/`).",
    )
    technology_subgeneration: str | None = Field(
        None,
        description=(
            "Technology-subgeneration slug (see `GET /api/technology-subgenerations/`). "
            "Matches models carrying the subgeneration directly or through their system."
        ),
    )
    cabinet: str | None = Field(
        None,
        description=(
            "Cabinet slug (see `GET /api/cabinets/`). Matches only explicitly "
            "classified models."
        ),
    )
    game_format: str | None = Field(
        None,
        description=(
            "Game-format slug (see `GET /api/game-formats/`). Matches only "
            "explicitly classified models."
        ),
    )
    production_status: str | None = Field(
        None,
        description=(
            "Production-status slug (see `GET /api/production-statuses/`). "
            "Matches only explicitly classified models."
        ),
    )
    corporate_entity: str | None = Field(
        None,
        description=(
            "Corporate-entity slug (see `GET /api/corporate-entities/`). Narrower "
            "than `manufacturer`: matches records built by this specific entity."
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
            display_subtype=self.display_subtype,
            tag=self.tag,
            technology_subgeneration=self.technology_subgeneration,
            cabinet=self.cabinet,
            game_format=self.game_format,
            production_status=self.production_status,
            corporate_entity=self.corporate_entity,
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


def _serialize_title_card(
    title: Title, *, min_rank: int, roles: list[str] | None = None
) -> GameCardSchema:
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
        public_id=title.public_id,
        year=first.year if first else None,
        manufacturer=_manufacturer_ref(first),
        thumbnail_url=thumbnail_url,
        roles=roles,
    )


def _serialize_model_card(
    model: MachineModel, *, min_rank: int, roles: list[str] | None = None
) -> GameCardSchema:
    """A Model card: every field is the Model's own."""
    thumbnail_url, _ = extract_image_urls(
        model.extra_data or {},
        displayed_primary_media(model),
        min_rank=min_rank,
    )
    return GameCardSchema(
        entity_type=MachineModel.entity_type,
        name=model.name,
        public_id=model.public_id,
        year=model.year,
        manufacturer=_manufacturer_ref(model),
        thumbnail_url=thumbnail_url,
        roles=roles,
    )


class _PersonRoles(NamedTuple):
    """The active person's deduped role names per carded record, keyed by pk —
    a Title's collected across its live Models."""

    by_title: dict[int, list[str]]
    by_model: dict[int, list[str]]


def _person_roles(rows: Sequence[GameRow], person: str) -> _PersonRoles:
    """Two bulk Credit queries for the page's cards.

    Title cards keep the person page's historical role order — credit order,
    newest Model first (the ``_PersonTitleAccum`` semantics), over **live**
    Models only, matching what the roll-up counted. A Model card's roles are
    its own, in the role vocabulary's display order."""
    by_title: dict[int, list[str]] = {}
    by_model: dict[int, list[str]] = {}
    title_pks = [r.pk for r in rows if r.kind == Title.entity_type]
    model_pks = [r.pk for r in rows if r.kind == MachineModel.entity_type]
    credits = Credit.objects.filter(person__slug=person, model__isnull=False)
    title_credits = (
        credits.filter(Q(model__title_id__in=title_pks) & active_status_q("model"))
        .order_by(
            F("model__year").desc(nulls_last=True),
            "model__name",
            "role__display_order",
        )
        .values_list("model__title_id", "role__name")
    )
    for title_id, role_name in title_credits:
        names = by_title.setdefault(title_id, [])
        if role_name not in names:
            names.append(role_name)
    model_credits = (
        credits.filter(model_id__in=model_pks)
        .order_by("role__display_order", "role__name")
        .values_list("model_id", "role__name")
    )
    for model_id, role_name in model_credits:
        names = by_model.setdefault(model_id, [])
        if role_name not in names:
            names.append(role_name)
    return _PersonRoles(by_title=by_title, by_model=by_model)


def _hydrate_cards(
    rows: Sequence[GameRow], *, min_rank: int, person: str | None = None
) -> list[GameCardSchema]:
    """One query per kind (plus prefetches), then serialize in row order.
    *person* is the active person dimension, if any — it annotates each card
    with that person's roles on the record."""
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
    roles = _person_roles(rows, person) if person else None
    return [
        _serialize_title_card(
            titles[r.pk],
            min_rank=min_rank,
            roles=roles.by_title.get(r.pk, []) if roles else None,
        )
        if r.kind == Title.entity_type
        else _serialize_model_card(
            models[r.pk],
            min_rank=min_rank,
            roles=roles.by_model.get(r.pk, []) if roles else None,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# The listing endpoint
# ---------------------------------------------------------------------------

games_router = Router(tags=["games"])


def game_list_page(f: GameFilters, *, page: int = 1) -> GameListSchema:
    """One page of cards plus the total count — the single production path for
    listing pages, shared by ``GET /api/games/`` and every detail-page embed
    (:func:`with_games`), so an embedded list cannot drift from the listing."""
    rows = game_rows_merged(f)
    size = DEFAULT_PAGE_SIZE
    start = (max(page, 1) - 1) * size
    return GameListSchema(
        items=_hydrate_cards(
            rows[start : start + size],
            min_rank=get_minimum_display_rank(),
            person=f.person,
        ),
        count=len(rows),
    )


def with_games[ModelT: SitemappedModel, PageT: Schema](
    serialize_detail: Callable[[ModelT], Schema],
    pin: Callable[[ModelT], GameFilters],
    page_schema: type[PageT],
) -> Callable[[ModelT, DetailPageContext], PageT]:
    """Compose an entity serializer with the games embed, for
    ``register_entity_detail_page``: the page payload is the detail fields plus
    page 1 of the listing pinned to the entity (*pin*) narrowed by the
    request's search term. *page_schema* must be the detail schema plus a
    ``games: GameListSchema`` field — the page/edit-response split: only
    the page endpoint carries (and pays for) the embedded listing."""

    def _serialize(obj: ModelT, ctx: DetailPageContext) -> PageT:
        detail = serialize_detail(obj)
        embed = game_list_page(replace(pin(obj), q=ctx.q))
        # model_validate (not a kwargs constructor): PageT is generic here, so
        # mypy sees only Schema's signature; validation also enforces that
        # *page_schema* really is the detail schema plus ``games``.
        return page_schema.model_validate({**detail.model_dump(), "games": embed})

    return _serialize


@games_router.get("/", response=GameListSchema)
def list_games(
    request: HttpRequest,
    filters: Query[GameFilterQuerySchema],
    page: Annotated[int, QueryParam(1, description="Page number, 1-based.")] = 1,
) -> GameListSchema:
    """Pinball titles and models at card grain, paginated. Narrow with the
    filters and the search (``q``). Ordered by release year (newest first),
    then alphabetically.

    All filters combine with AND."""
    return game_list_page(filters.to_filters(), page=page)


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
