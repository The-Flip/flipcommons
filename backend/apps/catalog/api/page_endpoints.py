"""Page-oriented endpoints for catalog entities.

These endpoints live under /api/pages/ and are tagged "private" so they
stay out of the public API docs.  They return page-model responses shaped
for specific SvelteKit SSR routes.

Each detail page is registered through ``register_entity_detail_page``;
the route segment and lookup field both come from the model
(``entity_type`` and ``public_id_field``), so adding a new linkable
entity is a one-line registration here.

Auto-discovered via the ``routers`` list convention in config/api.py.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from ninja import Query, Router, Schema

from apps.catalog.models import (
    Cabinet,
    CorporateEntity,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    Franchise,
    GameFormat,
    GameplayFeature,
    MachineModel,
    Manufacturer,
    Person,
    ProductionStatus,
    RewardType,
    Series,
    System,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    Title,
)
from apps.core.licensing import get_minimum_display_rank

from ..engine.entity_api.detail import plain_page, register_entity_detail_page
from ._game_rows import GameFilters
from .corporate_entities import CorporateEntityDetailSchema
from .corporate_entities import _detail_qs as _corp_entity_detail_qs
from .corporate_entities import _serialize_detail as _serialize_corp_entity_detail
from .franchises import (
    FranchiseDetailSchema,
    _franchise_detail_qs,
    _serialize_franchise_detail,
)
from .gameplay_features import GameplayFeaturePageSchema
from .gameplay_features import _detail_qs as _gf_detail_qs
from .gameplay_features import _serialize_detail as _serialize_gf_detail
from .games import (
    GameFacetsPageSchema,
    GameFilterQuerySchema,
    GameSearchSectionSchema,
    game_search_section,
    games_facets_response,
    with_games,
)
from .machine_models import (
    ModelDetailSchema,
    _model_detail_qs,
    _serialize_model_detail,
)
from .manufacturers import (
    ManufacturerDetailSchema,
    ManufacturerFacetsPageSchema,
    ManufacturerFilterQuerySchema,
    ManufacturerSearchSectionSchema,
    _manufacturer_qs,
    _serialize_manufacturer_detail,
    manufacturer_facets_response,
    manufacturer_search_section,
)
from .people import (
    PersonDetailSchema,
    PersonSearchSectionSchema,
    _person_qs,
    _serialize_person_detail,
    person_search_section,
)
from .series import SeriesDetailSchema, _serialize_series_detail, _series_detail_qs
from .systems import SystemDetailSchema, _serialize_system_detail, _system_detail_qs
from .taxonomy import (
    CreditRoleDetailSchema,
    DisplaySubtypePageSchema,
    RewardTypeDetailSchema,
    TaxonomyPageSchema,
    TechnologySubgenerationPageSchema,
    _credit_role_detail_qs,
    _reward_type_detail_qs,
    _serialize_credit_role_detail,
    _serialize_display_subtype,
    _serialize_reward_type_detail,
    _serialize_taxonomy,
    _serialize_technology_subgeneration,
    _taxonomy_detail_qs,
)
from .themes import ThemePageSchema
from .themes import _detail_qs as _theme_detail_qs
from .themes import _serialize_detail as _serialize_theme_detail
from .titles import TitleDetailSchema, _serialize_title_detail
from .titles import _detail_qs as _title_detail_qs

pages_router = Router(tags=["private"])

# Minimum trimmed ``q`` length the global search acts on. Below this the endpoint
# returns empty sections without touching the DB, and the SvelteKit page shows a
# "type at least N characters" hint instead of calling the endpoint.
_MIN_SEARCH_CHARS = 3


class SearchResultsSchema(Schema):
    """Global ``/search`` payload: three stacked sections in fixed render order
    (Games → Manufacturers → People). The frontend renders them in this
    declaration order. The games section is heterogeneous — Title and Model
    cards under the roll-up — rather than gaining a separate Models section: a
    sectioned interface plus an absorption rule fights itself."""

    games: GameSearchSectionSchema
    manufacturers: ManufacturerSearchSectionSchema
    people: PersonSearchSectionSchema


def _empty_search_results() -> SearchResultsSchema:
    """All three sections empty — the ``q`` too short / no-work response."""
    return SearchResultsSchema(
        games=GameSearchSectionSchema(items=[], has_more=False),
        manufacturers=ManufacturerSearchSectionSchema(items=[], has_more=False),
        people=PersonSearchSectionSchema(items=[], has_more=False),
    )


@pages_router.get("/search", response=SearchResultsSchema)
def search_page(request: HttpRequest, q: str = "") -> SearchResultsSchema:
    """Global search across Games, Manufacturers and People for the ``/search`` SSR
    page. Each section composes that entity's ordered listing rows + card
    serializer (so a section's top rows match its ``/…?q=`` listing) and caps at 10
    with a ``has_more`` flag. Trimmed ``q`` shorter than ``_MIN_SEARCH_CHARS`` returns
    empty sections without querying. Uncached — free-text ``q`` has a poor cache hit
    rate, and each query is narrow + ``[:11]`` + index-friendly."""
    q = q.strip()
    if len(q) < _MIN_SEARCH_CHARS:
        return _empty_search_results()
    # One Constance lookup shared by the game + manufacturer thumbnail resolvers.
    min_rank = get_minimum_display_rank()
    return SearchResultsSchema(
        games=game_search_section(q, min_rank=min_rank),
        manufacturers=manufacturer_search_section(q, min_rank=min_rank),
        people=person_search_section(q),
    )


@pages_router.get("/games", response=GameFacetsPageSchema)
def games_page_facets(
    request: HttpRequest, filters: Query[GameFilterQuerySchema]
) -> HttpResponse:
    """Facet option lists for the games listing SSR page (streamed after the
    cards; no-filter response cached). Cards come from ``GET /api/games/``."""
    return games_facets_response(filters.to_filters())


@pages_router.get("/manufacturers", response=ManufacturerFacetsPageSchema)
def manufacturers_page_facets(
    request: HttpRequest, filters: Query[ManufacturerFilterQuerySchema]
) -> HttpResponse:
    """Facet option lists for the /manufacturers SSR page (streamed after the cards;
    no-filter response cached). Cards come from ``GET /api/manufacturers/``."""
    return manufacturer_facets_response(filters.to_filters())


# ---------------------------------------------------------------------------
# Bespoke-schema entities — each pairs a model with its own detail schema,
# queryset, and serializer. Listed explicitly (not in a loop) so the
# factory's ``[ModelT, SchemaT]`` type variables stay enforced at every
# call site; a ``list[tuple[type, object, object, type]]`` would erase
# that correlation.
# ---------------------------------------------------------------------------


register_entity_detail_page(
    pages_router,
    Title,
    detail_qs=_title_detail_qs,
    serialize_page=plain_page(_serialize_title_detail),
    response_schema=TitleDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Manufacturer,
    detail_qs=_manufacturer_qs,
    serialize_page=plain_page(_serialize_manufacturer_detail),
    response_schema=ManufacturerDetailSchema,
)
register_entity_detail_page(
    pages_router,
    MachineModel,
    detail_qs=_model_detail_qs,
    serialize_page=plain_page(_serialize_model_detail),
    response_schema=ModelDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Person,
    detail_qs=_person_qs,
    serialize_page=plain_page(_serialize_person_detail),
    response_schema=PersonDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Series,
    detail_qs=_series_detail_qs,
    serialize_page=plain_page(_serialize_series_detail),
    response_schema=SeriesDetailSchema,
)
register_entity_detail_page(
    pages_router,
    CorporateEntity,
    detail_qs=_corp_entity_detail_qs,
    serialize_page=plain_page(_serialize_corp_entity_detail),
    response_schema=CorporateEntityDetailSchema,
)
register_entity_detail_page(
    pages_router,
    GameplayFeature,
    detail_qs=_gf_detail_qs,
    serialize_page=with_games(
        _serialize_gf_detail,
        lambda gf: GameFilters(features=(gf.slug,)),
        GameplayFeaturePageSchema,
    ),
    response_schema=GameplayFeaturePageSchema,
)
register_entity_detail_page(
    pages_router,
    Franchise,
    detail_qs=_franchise_detail_qs,
    serialize_page=plain_page(_serialize_franchise_detail),
    response_schema=FranchiseDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Theme,
    detail_qs=_theme_detail_qs,
    serialize_page=with_games(
        _serialize_theme_detail,
        lambda theme: GameFilters(themes=(theme.slug,)),
        ThemePageSchema,
    ),
    response_schema=ThemePageSchema,
)
register_entity_detail_page(
    pages_router,
    System,
    detail_qs=_system_detail_qs,
    serialize_page=plain_page(_serialize_system_detail),
    response_schema=SystemDetailSchema,
)
register_entity_detail_page(
    pages_router,
    RewardType,
    detail_qs=_reward_type_detail_qs,
    serialize_page=plain_page(_serialize_reward_type_detail),
    response_schema=RewardTypeDetailSchema,
)
register_entity_detail_page(
    pages_router,
    CreditRole,
    detail_qs=_credit_role_detail_qs,
    serialize_page=plain_page(_serialize_credit_role_detail),
    response_schema=CreditRoleDetailSchema,
)


# ---------------------------------------------------------------------------
# Taxonomy entities — the flat ones share the queryset builder, serializer,
# and ``TaxonomySchema``. The two single-parent subtaxonomies (DisplaySubtype,
# TechnologySubgeneration) override the serializer + schema to expose their
# parent ref (for the ``Parent › Child`` breadcrumb). Listed explicitly rather
# than looped so the factory's ``[ModelT, SchemaT]`` type variables stay
# enforced at each call site; a loop with a union-typed iteration variable
# widens ``ModelT`` and loses the per-call type binding.
# ---------------------------------------------------------------------------


register_entity_detail_page(
    pages_router,
    Tag,
    detail_qs=lambda: _taxonomy_detail_qs(Tag),
    serialize_page=with_games(
        _serialize_taxonomy,
        lambda obj: GameFilters(tag=obj.slug),
        TaxonomyPageSchema,
    ),
    response_schema=TaxonomyPageSchema,
)
register_entity_detail_page(
    pages_router,
    Cabinet,
    detail_qs=lambda: _taxonomy_detail_qs(Cabinet),
    serialize_page=with_games(
        _serialize_taxonomy,
        lambda obj: GameFilters(cabinet=obj.slug),
        TaxonomyPageSchema,
    ),
    response_schema=TaxonomyPageSchema,
)
register_entity_detail_page(
    pages_router,
    DisplayType,
    detail_qs=lambda: _taxonomy_detail_qs(DisplayType),
    serialize_page=with_games(
        _serialize_taxonomy,
        lambda obj: GameFilters(display_type=obj.slug),
        TaxonomyPageSchema,
    ),
    response_schema=TaxonomyPageSchema,
)
register_entity_detail_page(
    pages_router,
    DisplaySubtype,
    detail_qs=lambda: _taxonomy_detail_qs(DisplaySubtype).select_related(
        "display_type"
    ),
    serialize_page=with_games(
        _serialize_display_subtype,
        lambda obj: GameFilters(display_subtype=obj.slug),
        DisplaySubtypePageSchema,
    ),
    response_schema=DisplaySubtypePageSchema,
)
register_entity_detail_page(
    pages_router,
    GameFormat,
    detail_qs=lambda: _taxonomy_detail_qs(GameFormat),
    serialize_page=with_games(
        _serialize_taxonomy,
        lambda obj: GameFilters(game_format=obj.slug),
        TaxonomyPageSchema,
    ),
    response_schema=TaxonomyPageSchema,
)
register_entity_detail_page(
    pages_router,
    ProductionStatus,
    detail_qs=lambda: _taxonomy_detail_qs(ProductionStatus),
    serialize_page=with_games(
        _serialize_taxonomy,
        lambda obj: GameFilters(production_status=obj.slug),
        TaxonomyPageSchema,
    ),
    response_schema=TaxonomyPageSchema,
)
register_entity_detail_page(
    pages_router,
    TechnologyGeneration,
    detail_qs=lambda: _taxonomy_detail_qs(TechnologyGeneration),
    serialize_page=with_games(
        _serialize_taxonomy,
        lambda obj: GameFilters(tech_gen=obj.slug),
        TaxonomyPageSchema,
    ),
    response_schema=TaxonomyPageSchema,
)
register_entity_detail_page(
    pages_router,
    TechnologySubgeneration,
    detail_qs=lambda: _taxonomy_detail_qs(TechnologySubgeneration).select_related(
        "technology_generation"
    ),
    serialize_page=with_games(
        _serialize_technology_subgeneration,
        lambda obj: GameFilters(technology_subgeneration=obj.slug),
        TechnologySubgenerationPageSchema,
    ),
    response_schema=TechnologySubgenerationPageSchema,
)
