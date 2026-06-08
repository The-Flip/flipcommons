"""Ensure all expected API prefixes are registered after autodiscovery."""

from config.api import api

EXPECTED_PREFIXES = {
    "/auth/",
    "/pages/user/",
    "/corporate-entities/",
    "/display-types/",
    "/technology-generations/",
    "/models/",
    "/titles/",
    "/manufacturers/",
    "/people/",
    "/themes/",
    "/systems/",
    "/series/",
    "/franchises/",
    "/cabinets/",
    "/credit-roles/",
    "/display-subtypes/",
    "/game-formats/",
    "/gameplay-features/",
    "/production-statuses/",
    "/pages/locations/",
    "/reward-types/",
    "/tags/",
    "/technology-subgenerations/",
    "/pages/",
    "/link-types/",
    "/sources/",
    "/claims/",
    "/changesets/",
    "/review/",
    "/media/",
}


def test_all_routers_registered():
    registered = {prefix for prefix, _router in api._routers if prefix}
    assert registered >= EXPECTED_PREFIXES, (
        f"Missing routers: {EXPECTED_PREFIXES - registered}"
    )
