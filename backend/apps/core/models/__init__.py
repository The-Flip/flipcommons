"""Re-exports for ``apps.core.models``.

Implementation lives in submodules:

- ``mixins`` — abstract bases (TimeStampedModel,
  LastUpdatedModel,
  SluggedModel, LifecycleStatusModel, IdentifiableModel, LabeledModel,
  LabeledIdentityModel, LinkableModel, SitemappedModel), the EntityStatus
  enum, and the unique_slug helper.
- ``constraints`` — CHECK / UNIQUE constraint factories used in concrete Meta.
- ``license`` — the License model.
- ``references`` — RecordReference graph + post_delete cleanup signal.
- ``fields`` — shared Django field classes (BoundedTextField,
  MarkdownField).
"""

from .constraints import (
    field_lowercase,
    field_not_blank,
    meta_unique_fields,
    nullable_id_not_empty,
    self_fk_field_names,
    self_fk_not_self,
    slug_lowercase,
    slug_not_blank,
    status_valid,
    unique_ci,
)
from .fields import BoundedTextField, MarkdownField
from .license import License
from .mixins import (
    LIFECYCLE_STATUS_FIELD,
    DescribedModel,
    EntityStatus,
    IdentifiableModel,
    LabeledIdentityModel,
    LabeledModel,
    LastUpdatedModel,
    LifecycleManager,
    LifecycleQuerySet,
    LifecycleStatusModel,
    LinkableModel,
    SitemappedModel,
    SluggedModel,
    TimeStampedModel,
    active_status_q,
    is_deleted,
    is_live,
    unique_slug,
)
from .references import RecordReference, register_reference_cleanup

__all__ = [
    "BoundedTextField",
    "DescribedModel",
    "EntityStatus",
    "IdentifiableModel",
    "LabeledIdentityModel",
    "LabeledModel",
    "LastUpdatedModel",
    "LIFECYCLE_STATUS_FIELD",
    "License",
    "LifecycleManager",
    "LifecycleQuerySet",
    "LifecycleStatusModel",
    "LinkableModel",
    "MarkdownField",
    "RecordReference",
    "SitemappedModel",
    "SluggedModel",
    "TimeStampedModel",
    "active_status_q",
    "field_lowercase",
    "field_not_blank",
    "is_deleted",
    "is_live",
    "meta_unique_fields",
    "nullable_id_not_empty",
    "register_reference_cleanup",
    "self_fk_field_names",
    "self_fk_not_self",
    "slug_lowercase",
    "slug_not_blank",
    "status_valid",
    "unique_ci",
    "unique_slug",
]
