"""API endpoints for the catalog app.

Routers: models, titles, manufacturers, people, themes, systems, series,
franchises, and all taxonomy types.
Auto-discovered via the ``routers`` list convention in config/api.py.
"""

from .corporate_entities import corporate_entities_router
from .franchises import franchises_router
from .gameplay_features import gameplay_features_router
from .locations import locations_router
from .locations_write import locations_write_router
from .machine_models import models_router
from .manufacturers import manufacturers_router
from .page_endpoints import pages_router
from .people import people_router
from .series import series_router
from .systems import systems_router
from .taxonomy import (
    cabinets_router,
    credit_roles_router,
    display_subtypes_router,
    display_types_router,
    game_formats_router,
    production_statuses_router,
    reward_types_router,
    tags_router,
    technology_generations_router,
    technology_subgenerations_router,
)
from .themes import themes_router
from .titles import titles_router

__all__ = [
    "cabinets_router",
    "corporate_entities_router",
    "credit_roles_router",
    "display_subtypes_router",
    "display_types_router",
    "franchises_router",
    "game_formats_router",
    "gameplay_features_router",
    "locations_router",
    "locations_write_router",
    "manufacturers_router",
    "models_router",
    "pages_router",
    "people_router",
    "production_statuses_router",
    "reward_types_router",
    "routers",
    "series_router",
    "systems_router",
    "tags_router",
    "technology_generations_router",
    "technology_subgenerations_router",
    "themes_router",
    "titles_router",
]

routers = [
    ("/corporate-entities/", corporate_entities_router),
    ("/display-types/", display_types_router),
    ("/technology-generations/", technology_generations_router),
    ("/models/", models_router),
    ("/titles/", titles_router),
    ("/manufacturers/", manufacturers_router),
    ("/people/", people_router),
    ("/themes/", themes_router),
    ("/systems/", systems_router),
    ("/series/", series_router),
    ("/franchises/", franchises_router),
    ("/cabinets/", cabinets_router),
    ("/credit-roles/", credit_roles_router),
    ("/display-subtypes/", display_subtypes_router),
    ("/game-formats/", game_formats_router),
    ("/gameplay-features/", gameplay_features_router),
    ("/production-statuses/", production_statuses_router),
    ("/pages/locations/", locations_router),
    ("/locations/", locations_write_router),
    ("/reward-types/", reward_types_router),
    ("/tags/", tags_router),
    ("/technology-subgenerations/", technology_subgenerations_router),
    ("/pages/", pages_router),
]
