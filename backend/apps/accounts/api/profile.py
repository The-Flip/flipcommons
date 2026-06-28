"""User profile page endpoint: contribution history for a single user."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from django.db.models import Count, Max
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.accounts.models import User
from apps.core.authz import compute_row_capabilities, policy_user
from apps.core.schemas import ErrorDetailSchema
from apps.core.types import EntityKey
from apps.provenance.entity_links import build_entity_links
from apps.provenance.models import ChangeSet, Claim

from .profile_schemas import (
    EntityContributionSchema,
    UserChangeSetSchema,
    UserProfileSchema,
)

user_page_router = Router(tags=["private"])


class EntityContributionRow(TypedDict):
    content_type_id: int
    object_id: int
    edit_count: int
    last_edited_at: datetime


@user_page_router.get(
    "/{username}/", response={200: UserProfileSchema, 404: ErrorDetailSchema}
)
def user_profile_page(request: HttpRequest, username: str) -> UserProfileSchema:
    """Page model for the user profile page: contribution history."""
    caller = policy_user(request.user)
    user = get_object_or_404(User, username=username)

    edit_count = ChangeSet.objects.filter(actor_id=user.actor_id).count()
    member_since = user.date_joined.isoformat()

    raw_entity_rows = list(
        Claim.objects.filter(actor_id=user.actor_id, changeset__isnull=False)
        .values("content_type_id", "object_id")
        .annotate(
            edit_count=Count("changeset", distinct=True),
            last_edited_at=Max("changeset__created_at"),
        )
        .order_by("-last_edited_at")
    )

    entity_rows: list[EntityContributionRow] = []
    for row in raw_entity_rows:
        last_edited_at = row["last_edited_at"]
        assert isinstance(last_edited_at, datetime)
        entity_rows.append(
            {
                "content_type_id": int(row["content_type_id"]),
                "object_id": int(row["object_id"]),
                "edit_count": int(row["edit_count"]),
                "last_edited_at": last_edited_at,
            }
        )

    resolved = build_entity_links(
        [EntityKey(row["content_type_id"], row["object_id"]) for row in entity_rows]
    )

    entities_edited: list[EntityContributionSchema] = []
    for entity_row in entity_rows:
        meta = resolved.get(
            EntityKey(entity_row["content_type_id"], entity_row["object_id"])
        )
        if not meta:
            continue
        entities_edited.append(
            EntityContributionSchema(
                entity=meta,
                edit_count=entity_row["edit_count"],
                last_edited_at=entity_row["last_edited_at"].isoformat(),
            )
        )

    recent_changesets = (
        ChangeSet.objects.filter(actor_id=user.actor_id)
        .prefetch_related("claims")
        .order_by("-created_at")[:50]
    )

    cs_entity_keys: list[EntityKey] = []
    cs_first_claim: dict[int, EntityKey] = {}
    for cs in recent_changesets:
        prefetched_claims = cs.claims.all()
        if prefetched_claims:
            c = prefetched_claims[0]
            assert cs.pk is not None
            key = EntityKey(c.content_type_id, c.object_id)
            cs_first_claim[cs.pk] = key
            cs_entity_keys.append(key)

    cs_resolved = build_entity_links(cs_entity_keys)

    recent_edits: list[UserChangeSetSchema] = []
    for cs in recent_changesets:
        assert cs.pk is not None
        ref = cs_first_claim.get(cs.pk)
        if not ref:
            continue
        meta = cs_resolved.get(ref)
        if not meta:
            continue
        recent_edits.append(
            UserChangeSetSchema(
                id=cs.pk,
                note=cs.note,
                created_at=cs.created_at.isoformat(),
                entity=meta,
                capabilities=compute_row_capabilities(
                    caller, cs, UserChangeSetSchema.policy_activities
                ),
            )
        )

    return UserProfileSchema(
        username=user.username,
        member_since=member_since,
        edit_count=edit_count,
        entities_edited=entities_edited,
        recent_edits=recent_edits,
    )
