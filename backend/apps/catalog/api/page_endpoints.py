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
from ninja import Query, Router

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
    RewardType,
    Series,
    System,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    Title,
)

from .corporate_entities import CorporateEntityDetailSchema
from .corporate_entities import _detail_qs as _corp_entity_detail_qs
from .corporate_entities import _serialize_detail as _serialize_corp_entity_detail
from .entity_detail_page import register_entity_detail_page
from .franchises import (
    FranchiseDetailSchema,
    _franchise_detail_qs,
    _serialize_franchise_detail,
)
from .gameplay_features import GameplayFeatureDetailSchema
from .gameplay_features import _detail_qs as _gf_detail_qs
from .gameplay_features import _serialize_detail as _serialize_gf_detail
from .machine_models import (
    ModelDetailSchema,
    _model_detail_qs,
    _serialize_model_detail,
)
from .manufacturers import (
    ManufacturerDetailSchema,
    _manufacturer_qs,
    _serialize_manufacturer_detail,
)
from .people import PersonDetailSchema, _person_qs, _serialize_person_detail
from .series import SeriesDetailSchema, _serialize_series_detail, _series_detail_qs
from .systems import SystemDetailSchema, _serialize_system_detail, _system_detail_qs
from .taxonomy import (
    CreditRoleDetailSchema,
    RewardTypeDetailSchema,
    TaxonomySchema,
    _credit_role_detail_qs,
    _reward_type_detail_qs,
    _serialize_credit_role_detail,
    _serialize_reward_type_detail,
    _serialize_taxonomy,
    _taxonomy_detail_qs,
)
from .themes import ThemeDetailSchema
from .themes import _detail_qs as _theme_detail_qs
from .themes import _serialize_detail as _serialize_theme_detail
from .titles import (
    TitleDetailSchema,
    TitleFacetsPageSchema,
    TitleFilterQuerySchema,
    _serialize_title_detail,
    title_facets_response,
)
from .titles import _detail_qs as _title_detail_qs

pages_router = Router(tags=["private"])


@pages_router.get("/titles", response=TitleFacetsPageSchema)
def titles_page_facets(
    request: HttpRequest, filters: Query[TitleFilterQuerySchema]
) -> HttpResponse:
    """Facet option lists for the /titles SSR page (streamed after the cards;
    no-filter response cached). Cards come from ``GET /api/titles/``."""
    return title_facets_response(filters.to_filters())


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
    serialize_detail=_serialize_title_detail,
    response_schema=TitleDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Manufacturer,
    detail_qs=_manufacturer_qs,
    serialize_detail=_serialize_manufacturer_detail,
    response_schema=ManufacturerDetailSchema,
)
register_entity_detail_page(
    pages_router,
    MachineModel,
    detail_qs=_model_detail_qs,
    serialize_detail=_serialize_model_detail,
    response_schema=ModelDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Person,
    detail_qs=_person_qs,
    serialize_detail=_serialize_person_detail,
    response_schema=PersonDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Series,
    detail_qs=_series_detail_qs,
    serialize_detail=_serialize_series_detail,
    response_schema=SeriesDetailSchema,
)
register_entity_detail_page(
    pages_router,
    CorporateEntity,
    detail_qs=_corp_entity_detail_qs,
    serialize_detail=_serialize_corp_entity_detail,
    response_schema=CorporateEntityDetailSchema,
)
register_entity_detail_page(
    pages_router,
    GameplayFeature,
    detail_qs=_gf_detail_qs,
    serialize_detail=_serialize_gf_detail,
    response_schema=GameplayFeatureDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Franchise,
    detail_qs=_franchise_detail_qs,
    serialize_detail=_serialize_franchise_detail,
    response_schema=FranchiseDetailSchema,
)
register_entity_detail_page(
    pages_router,
    Theme,
    detail_qs=_theme_detail_qs,
    serialize_detail=_serialize_theme_detail,
    response_schema=ThemeDetailSchema,
)
register_entity_detail_page(
    pages_router,
    System,
    detail_qs=_system_detail_qs,
    serialize_detail=_serialize_system_detail,
    response_schema=SystemDetailSchema,
)
register_entity_detail_page(
    pages_router,
    RewardType,
    detail_qs=_reward_type_detail_qs,
    serialize_detail=_serialize_reward_type_detail,
    response_schema=RewardTypeDetailSchema,
)
register_entity_detail_page(
    pages_router,
    CreditRole,
    detail_qs=_credit_role_detail_qs,
    serialize_detail=_serialize_credit_role_detail,
    response_schema=CreditRoleDetailSchema,
)


# ---------------------------------------------------------------------------
# Taxonomy entities — share queryset builder, serializer, and response
# schema. Listed explicitly rather than looped so the factory's
# ``[ModelT, SchemaT]`` type variables stay enforced at each call site;
# a loop with a union-typed iteration variable widens ``ModelT`` and
# loses the per-call type binding.
# ---------------------------------------------------------------------------


register_entity_detail_page(
    pages_router,
    Tag,
    detail_qs=lambda: _taxonomy_detail_qs(Tag),
    serialize_detail=_serialize_taxonomy,
    response_schema=TaxonomySchema,
)
register_entity_detail_page(
    pages_router,
    Cabinet,
    detail_qs=lambda: _taxonomy_detail_qs(Cabinet),
    serialize_detail=_serialize_taxonomy,
    response_schema=TaxonomySchema,
)
register_entity_detail_page(
    pages_router,
    DisplayType,
    detail_qs=lambda: _taxonomy_detail_qs(DisplayType),
    serialize_detail=_serialize_taxonomy,
    response_schema=TaxonomySchema,
)
register_entity_detail_page(
    pages_router,
    DisplaySubtype,
    detail_qs=lambda: _taxonomy_detail_qs(DisplaySubtype),
    serialize_detail=_serialize_taxonomy,
    response_schema=TaxonomySchema,
)
register_entity_detail_page(
    pages_router,
    GameFormat,
    detail_qs=lambda: _taxonomy_detail_qs(GameFormat),
    serialize_detail=_serialize_taxonomy,
    response_schema=TaxonomySchema,
)
register_entity_detail_page(
    pages_router,
    TechnologyGeneration,
    detail_qs=lambda: _taxonomy_detail_qs(TechnologyGeneration),
    serialize_detail=_serialize_taxonomy,
    response_schema=TaxonomySchema,
)
register_entity_detail_page(
    pages_router,
    TechnologySubgeneration,
    detail_qs=lambda: _taxonomy_detail_qs(TechnologySubgeneration),
    serialize_detail=_serialize_taxonomy,
    response_schema=TaxonomySchema,
)
