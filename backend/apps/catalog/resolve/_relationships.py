"""Resolution logic for relationship claims (credits, themes, gameplay features, tags,
abbreviations, aliases, parent hierarchies, corporate-entity locations).

Every resolver here is a thin wrapper that builds a :class:`Projection` and runs
the shared :func:`reconcile` loop.  The generic :class:`ThroughRowProjection`
covers the plain/payload/compound through-row shapes (themes, gameplay features,
credits, abbreviations, parents, corporate-entity locations); the case-folded
:class:`AliasProjection` is the one bespoke shape that lives here.  Media is its
own projection in :mod:`._media`.
"""

from __future__ import annotations

import logging
from collections.abc import Hashable, Mapping
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
    Series,
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
from ._contracts import relationship_resolver
from ._engine import (
    Delta,
    ExtractedMember,
    MemberMap,
    RowState,
    reconcile,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Shared tuple shapes
# ------------------------------------------------------------------


class CreditAssignment(NamedTuple):
    """A (person, role) pair materialised into a Credit row."""

    person_id: int
    role_id: int


# ------------------------------------------------------------------
# Generic through-row projection
# ------------------------------------------------------------------


# Column <-> Member/Payload converters.  The ``*_to_columns`` direction takes
# ``object`` (a Member or Payload) — contravariantly assignable to any concrete
# param type — while the ``columns_to_*`` direction must return the precise type,
# so the scalar cases are spelled per result type (int / str / int|None).


def _int_from_column(columns: tuple[object, ...]) -> int:
    """Single int column → its value (FK target pk)."""
    return cast(int, columns[0])


def _str_from_column(columns: tuple[object, ...]) -> str:
    """Single str column → its value (abbreviation string)."""
    return cast(str, columns[0])


def _int_or_none_from_column(columns: tuple[object, ...]) -> int | None:
    """Single nullable int column → its value (gameplay count)."""
    return cast(int | None, columns[0])


def _one_column(value: object) -> tuple[object, ...]:
    """A scalar Member/Payload → its single column."""
    return (value,)


def _no_payload(columns: tuple[object, ...]) -> None:
    """Set membership: no payload columns → ``None`` payload."""
    return None


def _no_columns(payload: object) -> tuple[object, ...]:
    """Set membership: ``None`` payload → no payload columns."""
    return ()


@dataclass(frozen=True, slots=True)
class ThroughRowProjection[Member: Hashable, Payload]:
    """Generic membership projection over a through-table.

    The through model, its subject/member/payload columns and the create-time
    write flags are all data, so one class instantiates for themes, reward
    types, tags, gameplay features, credits, abbreviations, parent hierarchies
    and corporate-entity locations.  ``Member`` is a single pk/value or a
    compound :class:`~typing.NamedTuple` key; ``Payload`` is ``None`` for a set
    or a single attribute (e.g. gameplay ``count``) for a map.
    """

    subject_model: type[ClaimControlledModel]
    field_name: str
    through_model: type[Model]
    subject_column: str
    key_columns: tuple[str, ...]
    payload_columns: tuple[str, ...]
    extract_member: Callable[[Claim], ExtractedMember[Member, Payload] | None]
    columns_to_key: Callable[[tuple[object, ...]], Member]
    key_to_columns: Callable[[Member], tuple[object, ...]]
    columns_to_payload: Callable[[tuple[object, ...]], Payload]
    payload_to_columns: Callable[[Payload], tuple[object, ...]]
    ignore_conflicts: bool = False

    def claims(self, subjects: set[int] | None) -> Iterable[Claim]:
        ct = ContentType.objects.get_for_model(self.subject_model)
        claims_qs = Claim.objects.filter(content_type=ct, field_name=self.field_name)
        if subjects is not None:
            claims_qs = claims_qs.filter(object_id__in=subjects)
        return ranked_claims(claims_qs, "object_id", "claim_key")

    def subject(self, claim: Claim) -> int:
        return claim.object_id

    def extract(self, claim: Claim) -> ExtractedMember[Member, Payload] | None:
        return self.extract_member(claim)

    def read(
        self, subjects: set[int] | None
    ) -> MemberMap[int, Member, RowState[Payload]]:
        manager = self.through_model._default_manager
        if subjects is not None:
            rows_qs = manager.filter(**{f"{self.subject_column}__in": subjects})
        else:
            # A NULL subject column means the row belongs to a sibling namespace
            # sharing this table — Credit's model/series XOR is the only case.
            # A full-scope read must exclude those, or diff() would bucket them
            # under a null subject and delete them. A no-op for non-null columns.
            rows_qs = manager.filter(**{f"{self.subject_column}__isnull": False})

        nkeys = len(self.key_columns)
        columns = ("pk", self.subject_column, *self.key_columns, *self.payload_columns)
        existing: MemberMap[int, Member, RowState[Payload]] = {}
        for row in rows_qs.values_list(*columns):
            pk, subject_id = row[0], row[1]
            key = self.columns_to_key(row[2 : 2 + nkeys])
            payload = self.columns_to_payload(row[2 + nkeys :])
            existing.setdefault(subject_id, {})[key] = RowState(pk, payload)
        return existing

    def write(self, delta: Delta[int, Member, Payload]) -> None:
        manager = self.through_model._default_manager
        if delta.delete:
            manager.filter(pk__in=delta.delete).delete()
        if delta.create:
            rows = [
                self.through_model(
                    **{self.subject_column: row.subject},
                    **dict(
                        zip(
                            self.key_columns,
                            self.key_to_columns(row.key),
                            strict=True,
                        )
                    ),
                    **dict(
                        zip(
                            self.payload_columns,
                            self.payload_to_columns(row.payload),
                            strict=True,
                        )
                    ),
                )
                for row in delta.create
            ]
            manager.bulk_create(
                rows, batch_size=2000, ignore_conflicts=self.ignore_conflicts
            )
        if delta.update:
            fetched = manager.in_bulk([row.pk for row in delta.update])
            for row in delta.update:
                instance = fetched[row.pk]
                for column, value in zip(
                    self.payload_columns,
                    self.payload_to_columns(row.payload),
                    strict=True,
                ):
                    setattr(instance, column, value)
            manager.bulk_update(
                list(fetched.values()), list(self.payload_columns), batch_size=2000
            )


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


@relationship_resolver
def resolve_all_themes(*, subject_ids: set[int] | None = None) -> None:
    reconcile(_m2m_projection(M2M_FIELDS["theme"]), subject_ids)


@relationship_resolver
def resolve_all_reward_types(*, subject_ids: set[int] | None = None) -> None:
    reconcile(_m2m_projection(M2M_FIELDS["reward_type"]), subject_ids)


@relationship_resolver
def resolve_all_tags(*, subject_ids: set[int] | None = None) -> None:
    reconcile(_m2m_projection(M2M_FIELDS["tag"]), subject_ids)


# ------------------------------------------------------------------
# Gameplay features (M2M with a count payload)
# ------------------------------------------------------------------


@relationship_resolver
def resolve_all_gameplay_features(*, subject_ids: set[int] | None = None) -> None:
    """Bulk-resolve gameplay feature claims into through-rows carrying counts."""
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

    projection: ThroughRowProjection[int, int | None] = ThroughRowProjection(
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
    reconcile(projection, subject_ids)


# ------------------------------------------------------------------
# Credits (compound identity: person + role)
# ------------------------------------------------------------------


def _credit_key(columns: tuple[object, ...]) -> CreditAssignment:
    return CreditAssignment(cast(int, columns[0]), cast(int, columns[1]))


def _credit_columns(member: CreditAssignment) -> tuple[object, ...]:
    return (member.person_id, member.role_id)


def _resolve_credits(
    subject_model: type[ClaimControlledModel],
    fk_field: Literal["model", "series"],
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Subject-agnostic core for bulk credit resolution.

    Shared by the MachineModel and Series passes. ``fk_field`` is the ``Credit``
    FK attribute for this subject; ``Credit``'s model/series XOR constraint
    guarantees a row belongs to exactly one subject, so the two passes never
    touch each other's rows.
    """
    valid_person_pks = set(Person.objects.values_list("pk", flat=True))
    valid_role_pks = set(CreditRole.objects.values_list("pk", flat=True))
    if not valid_role_pks:
        logger.warning(
            "CreditRole table is empty — skipping bulk credit resolution. "
            "Apply the data patches that seed credit roles first."
        )
        return

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

    projection: ThroughRowProjection[CreditAssignment, None] = ThroughRowProjection(
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
    reconcile(projection, subject_ids)


@relationship_resolver
def resolve_all_credits(*, subject_ids: set[int] | None = None) -> None:
    """Bulk-resolve MachineModel credit claims into Credit rows."""
    _resolve_credits(MachineModel, "model", subject_ids=subject_ids)


@relationship_resolver
def resolve_all_series_credits(*, subject_ids: set[int] | None = None) -> None:
    """Bulk-resolve Series credit claims into Credit rows."""
    _resolve_credits(Series, "series", subject_ids=subject_ids)


# ------------------------------------------------------------------
# Abbreviations (string-valued membership, no FK target)
# ------------------------------------------------------------------


def _abbreviation_extract(claim: Claim) -> ExtractedMember[str, None]:
    val = cast(AbbreviationClaimValue, claim.value)
    return ExtractedMember(val["value"], None)


@relationship_resolver
def resolve_all_title_abbreviations(*, subject_ids: set[int] | None = None) -> None:
    """Bulk-resolve abbreviation claims into TitleAbbreviation rows."""
    projection: ThroughRowProjection[str, None] = ThroughRowProjection(
        subject_model=Title,
        field_name="abbreviation",
        through_model=TitleAbbreviation,
        subject_column="title_id",
        key_columns=("value",),
        payload_columns=(),
        extract_member=_abbreviation_extract,
        columns_to_key=_str_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
    )
    reconcile(projection, subject_ids)


@relationship_resolver
def resolve_all_model_abbreviations(*, subject_ids: set[int] | None = None) -> None:
    """Bulk-resolve abbreviation claims into ModelAbbreviation rows.

    Claim-local: the model's own winning abbreviations are materialized as-is,
    including any that also belong to its Title. The Title dedup is a read-time
    view (api.helpers.displayed_model_abbreviations), not a write-time
    subtraction — see docs/plans/provenance/ClaimResolutionRefactor.md.
    """
    projection: ThroughRowProjection[str, None] = ThroughRowProjection(
        subject_model=MachineModel,
        field_name="abbreviation",
        through_model=ModelAbbreviation,
        subject_column="machine_model_id",
        key_columns=("value",),
        payload_columns=(),
        extract_member=_abbreviation_extract,
        columns_to_key=_str_from_column,
        key_to_columns=_one_column,
        columns_to_payload=_no_payload,
        payload_to_columns=_no_columns,
    )
    reconcile(projection, subject_ids)


# ------------------------------------------------------------------
# Corporate-entity locations
# ------------------------------------------------------------------


@relationship_resolver
def resolve_all_corporate_entity_locations(
    *, subject_ids: set[int] | None = None
) -> None:
    """Sync CorporateEntityLocation rows from active 'location' claims.

    When *subject_ids* is ``None`` (the default), all CorporateEntity rows are
    considered so CEs whose claims were all deactivated also have stale rows
    removed.
    """
    valid_loc_pks = set(Location.objects.values_list("pk", flat=True))

    def extract(claim: Claim) -> ExtractedMember[int, None] | None:
        val = cast(LocationClaimValue, claim.value or {})
        loc_pk = val.get("location")
        if loc_pk and loc_pk in valid_loc_pks:
            return ExtractedMember(loc_pk, None)
        return None

    projection: ThroughRowProjection[int, None] = ThroughRowProjection(
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
    reconcile(projection, subject_ids)


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


def _resolve_aliases(parent_model: type[ClaimControlledModel]) -> None:
    """Bulk-resolve a parent entity's alias claims into its alias model rows.

    Everything about the alias type comes from the canonical alias registry, so
    callers supply only the parent model.  Resolves the parent's whole type
    (no subject scoping today).
    """
    at = alias_type_for(parent_model)
    assert at is not None, f"{parent_model.__name__} is not a registered alias type"
    schema = get_relationship_schema(at.claim_field)
    assert schema is not None, (
        f"alias namespace {at.claim_field!r} has no registered relationship schema"
    )
    projection = AliasProjection(
        parent_model=parent_model,
        alias_model=at.alias_model,
        fk_column=at.fk_name + "_id",
        claim_field=at.claim_field,
        schema=schema,
    )
    reconcile(projection, None)


# ------------------------------------------------------------------
# Parent hierarchy resolvers (Theme and GameplayFeature DAGs)
# ------------------------------------------------------------------


def _resolve_parents(
    parent_model: type[ClaimControlledModel], *, claim_field_prefix: str | None = None
) -> None:
    """Resolve parent hierarchy claims into self-referential M2M rows.

    Reads ``{claim_field_prefix}_parent`` claims on *parent_model* instances and
    materializes the self-referential ``parents`` M2M.  *claim_field_prefix*
    defaults to the model name but must be overridden when it differs from the
    claim-field convention (e.g. ``gameplayfeature`` vs ``gameplay_feature``).
    Resolves the parent's whole type (no subject scoping today).
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

    projection: ThroughRowProjection[int, None] = ThroughRowProjection(
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
    reconcile(projection, None)
