"""Resolution logic for relationship claims (credits, themes, gameplay features, tags,
abbreviations, aliases, parent hierarchies, corporate-entity locations).

Each ``_*_projection`` function builds the :class:`Projection` for one claim
namespace; :mod:`._dispatch` registers them and runs the shared
:func:`reconcile` loop.  The generic :class:`ThroughRowProjection` covers the
plain/payload/compound through-row shapes (themes, gameplay features, credits,
abbreviations, parents, corporate-entity locations); the case-folded
:class:`AliasProjection` is the one bespoke shape that lives here.  Media is its
own projection in :mod:`._media`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple, cast

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.validation import (
    RelationshipSchema,
    get_display_override,
    get_relationship_schema,
)

from ..engine.aliases import alias_type_for
from ..models import (
    CatalogModel,
    CorporateEntity,
    CorporateEntityLocation,
    Credit,
    CreditRole,
    GameplayFeature,
    Location,
    MachineModel,
    ModelAbbreviation,
    Person,
    RewardType,
    Tag,
    Theme,
    Title,
    TitleAbbreviation,
)
from ._claim_values import (
    AbbreviationClaimValue,
    AliasClaimValue,
    CreditClaimValue,
    GameplayFeatureClaimValue,
    LocationClaimValue,
    ParentClaimValue,
)
from ._engine import (
    Delta,
    ExtractedMember,
    MemberMap,
    RowState,
    ThroughRowProjection,
    _int_from_column,
    _int_or_none_from_column,
    _no_columns,
    _no_payload,
    _one_column,
    _str_from_column,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Shared tuple shapes
# ------------------------------------------------------------------


class CreditAssignment(NamedTuple):
    """A (person, role) pair materialised into a Credit row."""

    person_id: int
    role_id: int


# ------------------------------------------------------------------
# Through-model accessors (runtime-generated M2M descriptors)
# ------------------------------------------------------------------


def _m2m_through(m2m_attr: str) -> type[Model]:
    """Return the through model for a MachineModel M2M attribute."""
    through: type[Model] = getattr(MachineModel, m2m_attr).through
    return through


def _get_parents_through(parent: type[ClaimControlledModel]) -> type[Model]:
    """Return the through model for ``parent``'s self-referential ``parents`` M2M."""
    through: type[Model] = parent.parents.through  # type: ignore[attr-defined]
    return through


# ------------------------------------------------------------------
# Simple M2M relationships (themes, reward types, tags)
# ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class M2MFieldSpec:
    """Descriptor for a simple M2M relationship resolved from claims."""

    field_name: str  # claim field_name (also the value dict key): "theme", "tag"
    m2m_attr: str  # model attribute: "themes", "tags", "gameplay_features"
    target_model: type[CatalogModel]  # Theme, Tag, GameplayFeature


M2M_FIELDS: dict[str, M2MFieldSpec] = {
    "theme": M2MFieldSpec("theme", "themes", Theme),
    "reward_type": M2MFieldSpec("reward_type", "reward_types", RewardType),
    "tag": M2MFieldSpec("tag", "tags", Tag),
}


def _m2m_projection(spec: M2MFieldSpec) -> ThroughRowProjection[int, None]:
    """Build the projection for a simple MachineModel M2M relationship."""
    valid_pks = set(spec.target_model._default_manager.values_list("pk", flat=True))
    target_model_name = spec.target_model._meta.model_name
    assert target_model_name is not None
    target_column = target_model_name + "_id"

    def extract(claim: Claim) -> ExtractedMember[int, None] | None:
        val = cast(Mapping[str, object], claim.value)
        target_pk = val.get(spec.field_name)
        if type(target_pk) is not int or target_pk not in valid_pks:
            logger.warning(
                "Unresolved %s pk %r in claim (model pk=%s)",
                spec.field_name,
                target_pk,
                claim.object_id,
            )
            return None
        return ExtractedMember(target_pk, None)

    return ThroughRowProjection(
        subject_model=MachineModel,
        field_name=spec.field_name,
        through_model=_m2m_through(spec.m2m_attr),
        subject_column="machinemodel_id",
        key_columns=(target_column,),
        payload_columns=(),
        extract_member=extract,
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
    )


# ------------------------------------------------------------------
# Gameplay features (M2M with a count payload)
# ------------------------------------------------------------------


def _gameplay_projection() -> ThroughRowProjection[int, int | None]:
    """Build the projection for gameplay-feature claims (carries a count)."""
    valid_pks = set(GameplayFeature.objects.values_list("pk", flat=True))

    def extract(claim: Claim) -> ExtractedMember[int, int | None] | None:
        val = cast(GameplayFeatureClaimValue, claim.value)
        feature_pk = val.get("gameplay_feature")
        if feature_pk not in valid_pks:
            logger.warning(
                "Unresolved gameplay_feature pk %r in claim (model pk=%s)",
                feature_pk,
                claim.object_id,
            )
            return None
        return ExtractedMember(feature_pk, val.get("count"))

    return ThroughRowProjection(
        subject_model=MachineModel,
        field_name="gameplay_feature",
        through_model=_m2m_through("gameplay_features"),
        subject_column="machinemodel_id",
        key_columns=("gameplayfeature_id",),
        payload_columns=("count",),
        extract_member=extract,
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_int_or_none_from_column,
        payload_to_columns=_one_column,
    )


# ------------------------------------------------------------------
# Credits (compound identity: person + role)
# ------------------------------------------------------------------


def _credit_key(columns: tuple[object, ...]) -> CreditAssignment:
    return CreditAssignment(cast(int, columns[0]), cast(int, columns[1]))


def _credit_columns(member: CreditAssignment) -> tuple[object, ...]:
    return (member.person_id, member.role_id)


def _credit_projection(
    subject_model: type[ClaimControlledModel],
    fk_field: Literal["model", "series"],
) -> ThroughRowProjection[CreditAssignment, None] | None:
    """Build the credit projection for a subject, or ``None`` to skip.

    Shared by the MachineModel and Series passes. ``fk_field`` is the ``Credit``
    FK attribute for this subject; ``Credit``'s model/series XOR constraint
    guarantees a row belongs to exactly one subject, so the two passes never
    touch each other's rows.  Returns ``None`` when the ``CreditRole`` vocabulary
    is unseeded — resolving then would drop every credit as invalid and delete
    the existing rows, so the caller skips resolution entirely.
    """
    valid_person_pks = set(Person.objects.values_list("pk", flat=True))
    valid_role_pks = set(CreditRole.objects.values_list("pk", flat=True))
    if not valid_role_pks:
        logger.warning(
            "CreditRole table is empty — skipping bulk credit resolution. "
            "Apply the data patches that seed credit roles first."
        )
        return None

    def extract(claim: Claim) -> ExtractedMember[CreditAssignment, None] | None:
        val = cast(CreditClaimValue, claim.value)
        person_pk = val.get("person")
        if person_pk not in valid_person_pks:
            logger.warning(
                "Unresolved person pk %r in credit claim (subject pk=%s)",
                person_pk,
                claim.object_id,
            )
            return None
        role_pk = val.get("role")
        if role_pk not in valid_role_pks:
            logger.warning(
                "Unresolved credit role pk %r in credit claim (subject pk=%s)",
                role_pk,
                claim.object_id,
            )
            return None
        return ExtractedMember(CreditAssignment(person_pk, role_pk), None)

    return ThroughRowProjection(
        subject_model=subject_model,
        field_name="credit",
        through_model=Credit,
        subject_column=f"{fk_field}_id",
        key_columns=("person_id", "role_id"),
        payload_columns=(),
        extract_member=extract,
        columns_to_key=_credit_key,
        key_to_columns=_credit_columns,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
    )


# ------------------------------------------------------------------
# Abbreviations (string-valued membership, no FK target)
# ------------------------------------------------------------------


def _abbreviation_extract(claim: Claim) -> ExtractedMember[str, None]:
    val = cast(AbbreviationClaimValue, claim.value)
    return ExtractedMember(val["value"], None)


def _abbreviation_projection(
    subject_model: type[ClaimControlledModel],
    through_model: type[Model],
    subject_column: str,
) -> ThroughRowProjection[str, None]:
    """Build an abbreviation projection (string member, no FK target)."""
    return ThroughRowProjection(
        subject_model=subject_model,
        field_name="abbreviation",
        through_model=through_model,
        subject_column=subject_column,
        key_columns=("value",),
        payload_columns=(),
        extract_member=_abbreviation_extract,
        columns_to_key=_str_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
    )


def _title_abbreviation_projection() -> ThroughRowProjection[str, None]:
    """Build the projection for Title abbreviation claims."""
    return _abbreviation_projection(Title, TitleAbbreviation, "title_id")


def _model_abbreviation_projection() -> ThroughRowProjection[str, None]:
    """Build the projection for MachineModel abbreviation claims.

    Claim-local: the model's own winning abbreviations are materialized as-is,
    including any that also belong to its Title. The Title dedup is a read-time
    view (api.helpers.displayed_model_abbreviations), not a write-time
    subtraction — see docs/plans/provenance/ClaimResolutionRefactor.md.
    """
    return _abbreviation_projection(MachineModel, ModelAbbreviation, "machine_model_id")


# ------------------------------------------------------------------
# Corporate-entity locations
# ------------------------------------------------------------------


def _corporate_entity_location_projection() -> ThroughRowProjection[int, None]:
    """Build the projection for CorporateEntity 'location' claims."""
    valid_loc_pks = set(Location.objects.values_list("pk", flat=True))

    def extract(claim: Claim) -> ExtractedMember[int, None] | None:
        val = cast(LocationClaimValue, claim.value or {})
        loc_pk = val.get("location")
        if loc_pk and loc_pk in valid_loc_pks:
            return ExtractedMember(loc_pk, None)
        return None

    return ThroughRowProjection(
        subject_model=CorporateEntity,
        field_name="location",
        through_model=CorporateEntityLocation,
        subject_column="corporate_entity_id",
        key_columns=("location_id",),
        payload_columns=(),
        extract_member=extract,
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
    )


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
    claim_field: str
    schema: RelationshipSchema

    def claims(self, subjects: set[int] | None) -> Iterable[Claim]:
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
        override = get_display_override(val, self.schema, "alias_value")
        # Schema registration pins ``alias_display.scalar_type`` to ``str``, so
        # the override (when present) is always a str at runtime.
        display = str(override) if override is not None else alias_val
        return ExtractedMember(alias_val, display)  # alias_val is already lowercase

    def read(self, subjects: set[int] | None) -> MemberMap[int, str, RowState[str]]:
        manager = self.alias_model._default_manager
        rows_qs = manager.all()
        if subjects is not None:
            rows_qs = rows_qs.filter(**{f"{self.fk_column}__in": subjects})
        existing: MemberMap[int, str, RowState[str]] = {}
        for pk, parent_id, value in rows_qs.values_list("pk", self.fk_column, "value"):
            existing.setdefault(parent_id, {})[value.lower()] = RowState(pk, value)
        return existing

    def write(self, delta: Delta[int, str, str]) -> None:
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


# ------------------------------------------------------------------
# Parent hierarchy resolvers (Theme and GameplayFeature DAGs)
# ------------------------------------------------------------------


def _parent_projection(
    parent_model: type[ClaimControlledModel], *, claim_field_prefix: str | None = None
) -> ThroughRowProjection[int, None]:
    """Build the parent-hierarchy projection for a self-referential ``parents`` M2M.

    Reads ``{claim_field_prefix}_parent`` claims on *parent_model* instances.
    *claim_field_prefix* defaults to the model name but must be overridden when
    it differs from the claim-field convention (e.g. ``gameplayfeature`` vs
    ``gameplay_feature``).
    """
    model_name = parent_model._meta.model_name
    prefix = claim_field_prefix or model_name
    claim_field_name = f"{prefix}_parent"
    valid_pks = set(parent_model._default_manager.values_list("pk", flat=True))

    def extract(claim: Claim) -> ExtractedMember[int, None] | None:
        val = cast(ParentClaimValue, claim.value)
        parent_pk = val.get("parent")
        if parent_pk not in valid_pks:
            logger.warning(
                "Unresolved %s parent pk %r for pk=%s",
                claim_field_name,
                parent_pk,
                claim.object_id,
            )
            return None
        return ExtractedMember(parent_pk, None)

    return ThroughRowProjection(
        subject_model=parent_model,
        field_name=claim_field_name,
        through_model=_get_parents_through(parent_model),
        subject_column=f"from_{model_name}_id",
        key_columns=(f"to_{model_name}_id",),
        payload_columns=(),
        extract_member=extract,
        columns_to_key=_int_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
        ignore_conflicts=True,
    )
