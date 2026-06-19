"""Generic entity create surface.

The create registrar (:func:`register_entity_create`) and the create primitives
it composes (:mod:`.persist`) — slug/name validation, name/public-id
availability checks and the transactional ``create_entity_with_claims`` unit of
work — which domain routers also call directly when an entity's create is
structurally different enough to need a custom handler over the primitives.
"""

from .persist import (
    assert_name_available,
    assert_public_id_available,
    create_entity_with_claims,
    validate_create_input,
    validate_name,
    validate_slug_format,
)
from .registrar import CreateExtras, register_entity_create

__all__ = [
    "CreateExtras",
    "assert_name_available",
    "assert_public_id_available",
    "create_entity_with_claims",
    "register_entity_create",
    "validate_create_input",
    "validate_name",
    "validate_slug_format",
]
