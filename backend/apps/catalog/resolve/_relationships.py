"""The one transitional relationship-resolution shape the generic builder can't drive yet.

Every explicit ClassVar through-row shape (themes, gameplay features, credits,
abbreviations, corporate-entity locations, and the self-referential parent
hierarchies) resolves through the generic
:func:`apps.catalog.resolve._through_projection.build_through_projection`, driven
off each through-model's ``claim_relationship_spec``. One shape still lives here:

- :class:`AliasProjection` — case-folded membership (the member key is the
  lowercase alias value, the payload keeps original case), so not a plain
  :class:`ThroughRowProjection`.

It is retired by the alias-normalization polish step, after which only the
content-type-keyed media projection (in :mod:`._media`) stays bespoke.
:mod:`._dispatch` registers this and runs the shared :func:`reconcile` loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from apps.core.types import ClaimFieldName, ClaimSubjectId
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.validation import (
    RelationshipSchema,
    get_display_override,
    get_relationship_schema,
)

from ..engine.aliases import alias_type_for
from ._claim_values import AliasClaimValue
from ._engine import (
    Delta,
    ExtractedMember,
    MemberMap,
    RowState,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


# ------------------------------------------------------------------
# Aliases (case-folded membership with a display payload)
# ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AliasProjection:
    """Projection for a parent entity's alias claims into its alias rows.

    Bespoke because the member key is the *lowercase* alias value (for key
    stability) while the stored/displayed value (the payload) keeps original
    case; a display-case change is a payload update, and creates use
    ``ignore_conflicts`` against the unique key.
    """

    parent_model: type[ClaimControlledModel]
    alias_model: type[Model]
    fk_column: str
    claim_field: ClaimFieldName
    schema: RelationshipSchema

    def claims(self, subjects: set[ClaimSubjectId] | None) -> Iterable[Claim]:
        ct = ContentType.objects.get_for_model(self.parent_model)
        claims_qs = Claim.objects.filter(content_type=ct, field_name=self.claim_field)
        if subjects is not None:
            claims_qs = claims_qs.filter(object_id__in=subjects)
        return ranked_claims(claims_qs, "object_id", "claim_key")

    def subject(self, claim: Claim) -> int:
        return claim.object_id

    def extract(self, claim: Claim) -> ExtractedMember[str, str] | None:
        val = cast(AliasClaimValue, claim.value)
        alias_val = val.get("alias_value", "")
        if not alias_val:
            return None
        # The alias schema's sole member (``alias_value``) declares the
        # display_key; registration pins the target's scalar_type to str.
        override = get_display_override(val, self.schema.members[0])
        display = override if override is not None else alias_val
        return ExtractedMember(alias_val, display)  # alias_val is already lowercase

    def read(
        self, subjects: set[ClaimSubjectId] | None
    ) -> MemberMap[ClaimSubjectId, str, RowState[str]]:
        manager = self.alias_model._default_manager
        rows_qs = manager.all()
        if subjects is not None:
            rows_qs = rows_qs.filter(**{f"{self.fk_column}__in": subjects})
        existing: MemberMap[ClaimSubjectId, str, RowState[str]] = {}
        for pk, parent_id, value in rows_qs.values_list("pk", self.fk_column, "value"):
            existing.setdefault(parent_id, {})[value.lower()] = RowState(pk, value)
        return existing

    def write(self, delta: Delta[ClaimSubjectId, str, str]) -> None:
        manager = self.alias_model._default_manager
        if delta.delete:
            manager.filter(pk__in=delta.delete).delete()
        if delta.create:
            rows = [
                self.alias_model(**{self.fk_column: row.subject, "value": row.payload})
                for row in delta.create
            ]
            manager.bulk_create(rows, batch_size=2000, ignore_conflicts=True)
        for row in delta.update:
            manager.filter(pk=row.pk).update(value=row.payload)


def _alias_projection(parent_model: type[ClaimControlledModel]) -> AliasProjection:
    """Build the alias projection for a parent entity.

    Everything about the alias type comes from the canonical alias registry, so
    callers supply only the parent model.
    """
    at = alias_type_for(parent_model)
    assert at is not None, f"{parent_model.__name__} is not a registered alias type"
    schema = get_relationship_schema(at.claim_field)
    assert schema is not None, (
        f"alias namespace {at.claim_field!r} has no registered relationship schema"
    )
    return AliasProjection(
        parent_model=parent_model,
        alias_model=at.alias_model,
        fk_column=at.fk_name + "_id",
        claim_field=at.claim_field,
        schema=schema,
    )
