"""Generic entity delete / restore surface.

The delete-restore registrar, the soft-delete engine it executes (plan / execute
/ count over ``LinkableLifecycleClaimModel``) and the generic delete wire
schemas. Entity-specific delete previews subclass :class:`DeletePreviewBaseSchema`
domain-side.
"""

from .registrar import register_entity_delete_restore
from .schemas import (
    AlreadyDeletedSchema,
    BlockingReferrerSchema,
    DeletePreviewBaseSchema,
    DeleteResponseSchema,
    SoftDeleteBlockedSchema,
    TaxonomyDeletePreviewSchema,
)
from .soft_delete import (
    BlockingReferrer,
    SoftDeleteBlockedError,
    SoftDeletePlan,
    count_entity_changesets,
    execute_soft_delete,
    plan_soft_delete,
    serialize_blocking_referrer,
)

__all__ = [
    "AlreadyDeletedSchema",
    "BlockingReferrer",
    "BlockingReferrerSchema",
    "DeletePreviewBaseSchema",
    "DeleteResponseSchema",
    "SoftDeleteBlockedError",
    "SoftDeleteBlockedSchema",
    "SoftDeletePlan",
    "TaxonomyDeletePreviewSchema",
    "count_entity_changesets",
    "execute_soft_delete",
    "plan_soft_delete",
    "register_entity_delete_restore",
    "serialize_blocking_referrer",
]
