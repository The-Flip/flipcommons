"""Response schemas for the user-profile page endpoint.

These live next to `profile.py` rather than in `apps/accounts/schemas.py`
because they reach into provenance (`ChangeSet`, claims rollups). Per
[AppBoundaries.md](../../../../docs/AppBoundaries.md), `accounts` sits in
the bottom tier with `core` ("depends on nothing"); the page-endpoint
carve-out lets profile-page code cross into provenance, but the cross-
boundary import must stay scoped to the page endpoint's own modules
rather than leaking into the shared accounts schema surface that auth
and signup also import.
"""

from __future__ import annotations

from typing import ClassVar

from django.db.models import Model
from ninja import Schema
from pydantic import Field

from apps.core.authz import Activity, PolicyActivities
from apps.core.schemas import EntityLinkSchema
from apps.provenance.models import ChangeSet


class EntityContributionSchema(Schema):
    entity: EntityLinkSchema
    edit_count: int
    last_edited_at: str


class UserChangeSetSchema(Schema):
    id: int
    note: str
    created_at: str
    entity: EntityLinkSchema
    capabilities: dict[Activity, bool] = Field(default_factory=dict)

    policy_activities: ClassVar[PolicyActivities] = (Activity.CHANGESET_UNDO,)
    policy_target_model: ClassVar[type[Model]] = ChangeSet


class UserProfileSchema(Schema):
    username: str
    member_since: str
    edit_count: int
    entities_edited: list[EntityContributionSchema]
    recent_edits: list[UserChangeSetSchema]
